"""PRD §5.3. A run is where ingestion, matching, rules and exceptions all
land as one queryable unit; replay and diff are the two engine modules this
whole prompt was built to expose (fc.audit.replay).

**Scope decision, stated once**: there is no file-upload -> async-job
pipeline wired in this build (that would need a job-status table the frozen
12-table schema does not have, and CLAUDE.md is explicit: no schema change
after 28 Aug). ``POST /runs`` instead ingests the same generated corpus
``fc.eval.corpus.load_corpus()`` and ``make demo`` already use, synchronously,
in one transaction — real ingestion, real matching, real rule application,
real exceptions, not a stub. ``GET /runs/{run_id}/progress`` streams the real
stage list for a run that has already finished, since there is no live async
job to poll partway through; the SSE contract is real, its timing fidelity
is the thing this simplification gives up.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from api.audit_log import append_audit
from api.converters import event_from_row, exception_from_row
from api.deps import (
    AuthenticatedUser,
    LLMCallBuffer,
    current_user,
    db_session,
    finish,
    get_config,
    get_llm_buffer,
    get_llm_client,
    persist_llm_calls,
)
from api.errors import ApiError
from api.generation import generate_for_run
from api.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from api.ruleset import COMPOSITION_KEY, resolve_ruleset
from api.run_scope import event_source_run_id
from db.models import Cluster as ClusterRow
from db.models import ExceptionRow, Run, TransactionEventRow
from db.models import Match as MatchRow
from fc.audit.replay import ReplayDiff, diff_exceptions, replay
from fc.config import Config
from fc.eval.corpus import load_corpus
from fc.llm.client import LLMClient
from fc.models.ids import deterministic_factory, new_ulid
from fc.pipeline import PIPELINE_STAGES, PipelineResult, run_pipeline

router = APIRouter(prefix="/runs", tags=["runs"])


class RunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    tenant_id: str
    triggered_by: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    ruleset_hash: str
    period_start: date | None
    period_end: date | None
    record_count: int | None
    runtime_ms: int | None
    error: str | None
    parent_run_id: str | None
    replay_reason: str | None


class RunSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run: RunOut
    event_count: int
    match_count: int
    exception_count: int
    cluster_count: int
    escalated_count: int
    monitor_count: int


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = None
    seed: int = 7
    #: "demo" (default) loads the generated corpus from disk and reconciles
    #: it synchronously, as before. "empty" creates an open run with no
    #: events at all — the caller then ingests via POST /ingest/{razorpay,
    #: bank,ledger} against this run_id and calls POST /runs/{run_id}/finalize
    #: to run the cascade over whatever was actually uploaded.
    mode: Literal["demo", "empty"] = "demo"


class DiffOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_run_id: str
    to_run_id: str
    diff: ReplayDiff


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    seed: int = 8
    #: Pin the replay to the ruleset a previous run used, by its
    #: ``runs.ruleset_hash``. Omitted, the replay uses whatever is effective
    #: now — which is the point of replaying after a rule change. PRD §5.3's
    #: ``ruleset_version``: the hash is the version, and it now selects rather
    #: than merely records.
    ruleset_hash: str | None = None


class ReplayOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_run_id: str
    diff: ReplayDiff


def _run_out(row: Run) -> RunOut:
    return RunOut(
        run_id=row.run_id,
        tenant_id=row.tenant_id,
        triggered_by=row.triggered_by,
        started_at=row.started_at,
        finished_at=row.finished_at,
        status=row.status,
        ruleset_hash=row.ruleset_hash,
        period_start=row.period_start,
        period_end=row.period_end,
        record_count=row.record_count,
        runtime_ms=row.runtime_ms,
        error=row.error,
        parent_run_id=row.parent_run_id,
        replay_reason=row.replay_reason,
    )


#: Exception statuses a replay carries forward from its parent. A human
#: decision survives a recomputation; "superseded" and "open" are the
#: engine's own bookkeeping and do not.
_CARRIED_STATUSES = frozenset({"resolved", "written_off"})


@router.get("", response_model=Page[RunOut])
async def list_runs(
    limit: int = Query(DEFAULT_LIMIT, le=MAX_LIMIT, gt=0),
    cursor: str | None = None,
    kind: Literal["all", "original", "replay"] = "all",
    status: str | None = None,
    session: AsyncSession = Depends(db_session),
) -> Page[RunOut]:
    """``kind`` filters on replay lineage, ``status`` on run state.

    The frontend asks for ``kind=original&status=complete`` because "the
    current state of the books" is the newest real reconciliation, not the
    newest what-if replay and not a run that is still open for ingestion. It
    used to take the newest row of any kind, which is how the app came to open
    on a replay.
    """
    stmt = select(Run).order_by(Run.started_at.desc(), Run.run_id.desc())
    if kind == "original":
        stmt = stmt.where(Run.parent_run_id.is_(None))
    elif kind == "replay":
        stmt = stmt.where(Run.parent_run_id.is_not(None))
    if status is not None:
        stmt = stmt.where(Run.status == status)
    if cursor is not None:
        stmt = stmt.where(Run.run_id < decode_cursor(cursor))
    rows = (await session.scalars(stmt.limit(limit + 1))).all()
    items = [_run_out(r) for r in rows[:limit]]
    next_cursor = encode_cursor(items[-1].run_id) if len(rows) > limit else None
    return Page(items=items, next_cursor=next_cursor)


async def _load(session: AsyncSession, run_id: str) -> Run:
    row = await session.get(Run, run_id)
    if row is None:
        raise ApiError(404, "not found", f"no run {run_id}")
    return row


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: str, session: AsyncSession = Depends(db_session)) -> RunOut:
    return _run_out(await _load(session, run_id))


async def _count(
    session: AsyncSession, model: type, run_id_col: InstrumentedAttribute[str], run_id: str
) -> int:
    total = await session.scalar(
        select(func.count()).select_from(model).where(run_id_col == run_id)
    )
    return total or 0


@router.get("/{run_id}/summary", response_model=RunSummaryOut)
async def get_run_summary(
    run_id: str, session: AsyncSession = Depends(db_session)
) -> RunSummaryOut:
    row = await _load(session, run_id)
    escalated = await session.scalar(
        select(func.count())
        .select_from(ExceptionRow)
        .where(ExceptionRow.run_id == run_id, ExceptionRow.tier == "escalate")
    )
    monitor = await session.scalar(
        select(func.count())
        .select_from(ExceptionRow)
        .where(ExceptionRow.run_id == run_id, ExceptionRow.tier == "monitor")
    )
    return RunSummaryOut(
        run=_run_out(row),
        # Through the lineage: a replay cites its parent's events, so counting
        # on run_id alone reported 0 records under a record_count of 1571.
        event_count=await _count(
            session,
            TransactionEventRow,
            TransactionEventRow.run_id,
            await event_source_run_id(session, run_id),
        ),
        match_count=await _count(session, MatchRow, MatchRow.run_id, run_id),
        exception_count=await _count(session, ExceptionRow, ExceptionRow.run_id, run_id),
        cluster_count=await _count(session, ClusterRow, ClusterRow.run_id, run_id),
        escalated_count=escalated or 0,
        monitor_count=monitor or 0,
    )


@router.get("/{run_id}/progress")
async def get_run_progress(
    run_id: str, session: AsyncSession = Depends(db_session)
) -> StreamingResponse:
    row = await _load(session, run_id)

    async def events() -> AsyncIterator[str]:
        for stage in PIPELINE_STAGES:
            status = "done" if row.status == "complete" else row.status
            yield f'event: stage\ndata: {{"stage": "{stage}", "status": "{status}"}}\n\n'
            await asyncio.sleep(0)
        yield f'event: run\ndata: {{"run_id": "{run_id}", "status": "{row.status}"}}\n\n'

    return StreamingResponse(events(), media_type="text/event-stream")


def _persist_pipeline_result(
    session: AsyncSession,
    *,
    run_id: str,
    tenant_id: str,
    result: PipelineResult,
    persist_events: bool = True,
) -> None:
    """``persist_events=False`` is for ``finalize_run`` and ``replay_run``:
    the events already exist as rows — ingested via ``POST /ingest/*`` before
    the pipeline ran, or belonging to the parent run being replayed — and
    ``result.events`` is the exact same sequence passed in either way. A
    second insert would collide on the primary key, not create anything new.
    """
    if persist_events:
        for event in result.events:
            session.add(
                TransactionEventRow(
                    event_id=event.event_id,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    source=event.source,
                    source_row_id=event.source_row_id,
                    amount_paise=event.amount_paise,
                    direction=event.direction,
                    currency=event.currency,
                    txn_date=event.txn_date,
                    value_date=event.value_date,
                    settled_at=event.settled_at,
                    utr=event.utr,
                    rrn=event.rrn,
                    settlement_id=event.settlement_id,
                    order_id=event.order_id,
                    payment_id=event.payment_id,
                    voucher_number=event.voucher_number,
                    voucher_guid=event.voucher_guid,
                    counterparty=event.counterparty,
                    counterparty_norm=event.counterparty_norm,
                    method=event.method,
                    rail=event.rail,
                    txn_type=event.txn_type,
                    raw_narration=event.raw_narration,
                    fee_paise=event.fee_paise,
                    tax_paise=event.tax_paise,
                    on_hold=event.on_hold,
                    ledger_account=event.ledger_account,
                    voucher_type=event.voucher_type,
                    raw=event.raw,
                    ingested_at=event.ingested_at,
                )
            )
    for match in result.cascade.matches:
        session.add(
            MatchRow(
                match_id=match.match_id,
                run_id=run_id,
                tenant_id=tenant_id,
                group_key=match.group_key,
                event_ids=match.event_ids,
                sources_covered=match.sources_covered,
                stage=match.stage,
                confidence=match.confidence,
                residual_paise=match.residual_paise,
                rule_version_hash=match.rule_version_hash,
                evidence=[leg.model_dump(mode="json") for leg in match.evidence],
                auto_closed=match.auto_closed,
                created_at=match.created_at,
            )
        )
    for cluster in result.clusters:
        session.add(
            ClusterRow(
                cluster_id=cluster.cluster_id,
                run_id=run_id,
                tenant_id=tenant_id,
                root_cause=cluster.root_cause,
                label=cluster.label,
                grouping_key=cluster.grouping_key,
                member_count=cluster.member_count,
                total_paise=cluster.total_paise,
                max_tier=cluster.max_tier,
                suggested_fix=cluster.suggested_fix,
                created_at=cluster.created_at,
            )
        )
    for exc in result.exceptions:
        session.add(
            ExceptionRow(
                exception_id=exc.exception_id,
                run_id=run_id,
                tenant_id=tenant_id,
                event_ids=exc.event_ids,
                category=exc.category,
                amount_paise=exc.amount_paise,
                residual_paise=exc.residual_paise,
                confidence=exc.confidence,
                tier=exc.tier,
                priority_score=exc.priority_score,
                cluster_id=exc.cluster_id,
                rules_applied=[r.model_dump(mode="json") for r in exc.rules_applied],
                recommended_action=exc.recommended_action,
                consequence=exc.consequence,
                deadline=exc.deadline,
                recheck_at=exc.recheck_at,
                recheck_count=exc.recheck_count,
                status=exc.status,
                # The lifecycle fields the engine set alongside status. Dropping
                # them wrote an auto-resolved exception with resolved_by NULL,
                # so the row said "resolved" with no record of who or why.
                resolved_by=exc.resolved_by,
                resolved_at=exc.resolved_at,
                resolution_reason=exc.resolution_reason,
                signature=exc.signature,
                created_at=exc.created_at,
            )
        )


@router.post("", response_model=RunOut)
async def create_run(
    body: CreateRunRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
    client: LLMClient = Depends(get_llm_client),
    buffer: LLMCallBuffer = Depends(get_llm_buffer),
) -> RunOut:
    started_at = datetime.now(UTC)

    if body.mode == "demo":
        # `fc.eval.corpus.load_corpus()` always returns the exact same
        # content — same event ids, same `voucher_guid`s and other
        # source-content fields, several of which carry a *global* unique
        # index (`ix_te_guid`: real idempotency, the same physical voucher
        # must not double-book). So the demo corpus can be inserted at most
        # once, ever, per tenant — a second "Run demo corpus" click cannot
        # create an independent second run of it, because there is no second
        # copy of the data to run one over. Rather than fail on the insert,
        # short-circuit here: if it is already loaded, hand back that run
        # untouched (no new row, no re-run) instead of pretending a fresh
        # run happened. Keyed on the first event's own `(source,
        # source_row_id)`, which is stable source content, unlike `event_id`.
        anchor = load_corpus().events[0]
        existing_anchor = await session.scalar(
            select(TransactionEventRow).where(
                TransactionEventRow.tenant_id == user.tenant_id,
                TransactionEventRow.source == anchor.source,
                TransactionEventRow.source_row_id == anchor.source_row_id,
            )
        )
        if existing_anchor is not None:
            existing_run = await _load(session, existing_anchor.run_id)
            return _run_out(existing_run)

    run_id = new_ulid("run_")
    ruleset = await resolve_ruleset(session, tenant_id=user.tenant_id)
    issue_id = deterministic_factory(seed=body.seed, epoch_ms=int(started_at.timestamp() * 1000))

    # Secrets never land in an auditable JSONB column, even the config
    # snapshot replay reads back later.
    _SECRET_FIELDS = {
        "jwt_secret",
        "resend_api_key",
        "gemini_api_key",
        "groq_api_key",
        "fc_app_password",
    }
    run_row = Run(
        run_id=run_id,
        tenant_id=user.tenant_id,
        triggered_by=user.user_id,
        started_at=started_at,
        status="running",
        ruleset_hash=ruleset.ruleset_hash,
        input_hashes=({"corpus": ruleset.ruleset_hash} if body.mode == "demo" else {})
        | {COMPOSITION_KEY: ruleset.composition},
        config=cfg.model_dump(mode="json", exclude=_SECRET_FIELDS),
    )
    session.add(run_row)
    await session.flush()

    if body.mode == "empty":
        # No corpus, no pipeline: an open shell the ingest endpoints can
        # write into. `finalize_run` is the only path from here to `complete`.
        await append_audit(
            session,
            tenant_id=user.tenant_id,
            actor=f"user:{user.user_id}",
            action="run.create_empty",
            subject_type="run",
            subject_id=run_id,
            payload={"label": body.label, "dry_run": dry_run},
            created_at=started_at,
            run_id=run_id,
            ruleset_hash=ruleset.ruleset_hash,
        )
        result_out = _run_out(run_row)
        await finish(session, dry_run=dry_run)
        return result_out

    # Reached only for mode="demo" with the corpus not already loaded (the
    # already-loaded case returned above). `event_id` is still remapped to
    # this call's own `issue_id` rather than trusting `load_corpus()`'s
    # fixed-seed ids verbatim — belt and suspenders for the same collision,
    # in case a row with a matching anchor was deleted without deleting the
    # rest (nothing in this codebase does that today, but the cost of
    # assuming it can't happen is a much less legible crash than this one
    # kept being).
    corpus = load_corpus()
    events = tuple(
        event.model_copy(update={"event_id": issue_id("evt_")}) for event in corpus.events
    )
    result = run_pipeline(
        events,
        cfg=cfg,
        rules=ruleset.rules,
        run_id=run_id,
        tenant_id=user.tenant_id,
        issue_id=issue_id,
        created_at=started_at,
    )
    _persist_pipeline_result(session, run_id=run_id, tenant_id=user.tenant_id, result=result)

    finished_at = datetime.now(UTC)
    run_row.finished_at = finished_at
    run_row.status = "complete"
    run_row.record_count = len(result.events)
    run_row.runtime_ms = int((finished_at - started_at).total_seconds() * 1000)
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="run.create",
        subject_type="run",
        subject_id=run_id,
        payload={
            "label": body.label,
            "record_count": run_row.record_count,
            "exception_count": len(result.exceptions),
            "match_count": len(result.cascade.matches),
            "dry_run": dry_run,
        },
        created_at=finished_at,
        run_id=run_id,
        ruleset_hash=ruleset.ruleset_hash,
    )
    # §7.10: prose after the numbers, never before. The run is already
    # reconciled and persisted; this adds three batched calls' worth of
    # wording, and any failure inside leaves the deterministic label and
    # template in place. A dry run skips it — there would be no rows to label.
    if not dry_run:
        await generate_for_run(session, run_id=run_id, tenant_id=user.tenant_id, client=client)
        await persist_llm_calls(session, buffer, tenant_id=user.tenant_id)

    result_out = _run_out(run_row)
    await finish(session, dry_run=dry_run)
    return result_out


@router.post("/{run_id}/finalize", response_model=RunOut)
async def finalize_run(
    run_id: str,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
    client: LLMClient = Depends(get_llm_client),
    buffer: LLMCallBuffer = Depends(get_llm_buffer),
) -> RunOut:
    """The other half of ``mode="empty"``: run the cascade over whatever the
    ingest endpoints actually wrote for this run, then close it out exactly
    the way ``create_run`` closes a demo-corpus run — same pipeline call,
    same persistence, same post-run prose. Reads events back from the
    database rather than taking them as a parameter, the same way
    ``replay_run`` does, so this is the one place a run's stored events and
    what actually got reconciled can never drift apart.
    """
    run_row = await _load(session, run_id)
    if run_row.status not in ("queued", "running"):
        raise ApiError(
            409, "invalid state", f"run {run_id} is {run_row.status!r}, not open to finalize"
        )
    event_rows = (
        await session.scalars(
            select(TransactionEventRow).where(TransactionEventRow.run_id == run_id)
        )
    ).all()
    if not event_rows:
        raise ApiError(409, "nothing to finalize", f"run {run_id} has no ingested events")
    events = [event_from_row(e) for e in event_rows]

    ruleset = await resolve_ruleset(session, tenant_id=user.tenant_id)
    run_row.input_hashes = dict(run_row.input_hashes or {}) | {COMPOSITION_KEY: ruleset.composition}
    issue_id = deterministic_factory(seed=7, epoch_ms=int(run_row.started_at.timestamp() * 1000))
    result = run_pipeline(
        events,
        cfg=cfg,
        rules=ruleset.rules,
        run_id=run_id,
        tenant_id=user.tenant_id,
        issue_id=issue_id,
        created_at=run_row.started_at,
    )
    _persist_pipeline_result(
        session, run_id=run_id, tenant_id=user.tenant_id, result=result, persist_events=False
    )

    finished_at = datetime.now(UTC)
    run_row.finished_at = finished_at
    run_row.status = "complete"
    run_row.record_count = len(result.events)
    run_row.runtime_ms = int((finished_at - run_row.started_at).total_seconds() * 1000)
    run_row.ruleset_hash = ruleset.ruleset_hash
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="run.finalize",
        subject_type="run",
        subject_id=run_id,
        payload={
            "record_count": run_row.record_count,
            "exception_count": len(result.exceptions),
            "match_count": len(result.cascade.matches),
            "dry_run": dry_run,
        },
        created_at=finished_at,
        run_id=run_id,
        ruleset_hash=ruleset.ruleset_hash,
    )
    if not dry_run:
        await generate_for_run(session, run_id=run_id, tenant_id=user.tenant_id, client=client)
        await persist_llm_calls(session, buffer, tenant_id=user.tenant_id)

    result_out = _run_out(run_row)
    await finish(session, dry_run=dry_run)
    return result_out


@router.post("/{run_id}/replay", response_model=ReplayOut)
async def replay_run(
    run_id: str,
    body: ReplayRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> ReplayOut:
    """Reads the parent run's own stored config and events — never today's
    active rules on its own — replays under the currently *active* ruleset
    (the caller-specified target; PRD §5.3's ``ruleset_version`` selects a
    hash this build resolves to "whatever is active now", since there is no
    UI yet to pick an arbitrary historical version by hash).

    The input never changes, so nothing about it is re-persisted:
    ``_persist_pipeline_result`` runs with ``persist_events=False`` exactly
    as ``finalize_run`` does. Two independent constraints make a second copy
    impossible even if it were desired — ``transaction_events.event_id`` is
    a bare primary key (one row per event, ever, not per run) and
    ``ix_te_guid`` treats a ledger voucher as booked at most once per tenant
    — so the new run's exceptions simply cite the parent run's own
    ``event_id`` values. ``diff_exceptions`` depends on exactly this: it
    matches "the same underlying transaction" across two runs by comparing
    ``event_ids`` verbatim (see ``fc.audit.replay``'s module docstring), so
    reusing them rather than minting fresh ones is what keeps the diff
    correct, not an oversight to fix later.
    """
    parent = await _load(session, run_id)
    # Through the lineage, so replaying a replay works: the grandparent owns
    # the rows and every generation cites them (api/run_scope.py).
    parent_event_rows = (
        await session.scalars(
            select(TransactionEventRow).where(
                TransactionEventRow.run_id == await event_source_run_id(session, run_id)
            )
        )
    ).all()
    if not parent_event_rows:
        raise ApiError(409, "nothing to replay", f"run {run_id} has no events")
    parent_exception_rows = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.run_id == run_id))
    ).all()

    events = [event_from_row(e) for e in parent_event_rows]
    parent_exceptions = [exception_from_row(e) for e in parent_exception_rows]

    ruleset = await resolve_ruleset(
        session, tenant_id=user.tenant_id, target_hash=body.ruleset_hash
    )
    new_run_id = new_ulid("run_")
    started_at = datetime.now(UTC)
    issue_id = deterministic_factory(seed=body.seed, epoch_ms=int(started_at.timestamp() * 1000))

    new_run_row = Run(
        run_id=new_run_id,
        tenant_id=user.tenant_id,
        triggered_by=user.user_id,
        started_at=started_at,
        status="running",
        ruleset_hash=ruleset.ruleset_hash,
        # The parent's other input hashes carry over; the ruleset composition
        # is this run's own, so a replay under a changed ruleset records what
        # it actually used rather than inheriting a stale claim.
        input_hashes=dict(parent.input_hashes) | {COMPOSITION_KEY: ruleset.composition},
        config=dict(parent.config),
        parent_run_id=run_id,
        replay_reason=body.reason,
    )
    session.add(new_run_row)
    await session.flush()

    result = replay(
        parent_run_id=run_id,
        parent_exceptions=parent_exceptions,
        events=events,
        cfg=cfg,
        rules=ruleset.rules,
        new_run_id=new_run_id,
        tenant_id=user.tenant_id,
        issue_id=issue_id,
        created_at=started_at,
    )
    _persist_pipeline_result(
        session,
        run_id=new_run_id,
        tenant_id=user.tenant_id,
        result=result.pipeline,
        persist_events=False,
    )

    # A replay recomputes the engine's opinion; it must not silently undo a
    # human's. fc.audit.replay deliberately excludes lifecycle fields from the
    # diff and starts every recomputed exception at status="open" (that is the
    # engine staying pure), which left the caller to carry the decision across
    # — and nothing did. Sixteen resolutions and two write-offs on the demo run
    # reverted to open on every replay.
    #
    # event_ids is the key for the same reason diff_exceptions uses it: it
    # identifies the same underlying transaction across runs, where
    # exception_id and signature do not.
    await session.flush()
    prior_decisions = {
        tuple(sorted(e.event_ids)): e
        for e in parent_exception_rows
        if e.status in _CARRIED_STATUSES
    }
    carried = 0
    for exc in result.pipeline.exceptions:
        prior = prior_decisions.get(tuple(sorted(exc.event_ids)))
        if prior is None:
            continue
        await session.execute(
            update(ExceptionRow)
            .where(ExceptionRow.exception_id == exc.exception_id)
            .values(
                status=prior.status,
                resolved_by=prior.resolved_by,
                resolved_by_user=prior.resolved_by_user,
                resolved_via=prior.resolved_via,
                resolution_reason=prior.resolution_reason,
                resolution_category=prior.resolution_category,
                resolved_at=prior.resolved_at,
            )
        )
        carried += 1

    # Appendix E: replay supersedes -> every parent exception this diff
    # touched (changed or removed) is superseded by the new run's decision.
    superseded_ids = [
        e.exception_id_before
        for e in (result.diff.changed + result.diff.removed)
        if e.exception_id_before
    ]
    if superseded_ids:
        await session.execute(
            update(ExceptionRow)
            .where(ExceptionRow.exception_id.in_(superseded_ids))
            .values(status="superseded")
        )

    finished_at = datetime.now(UTC)
    new_run_row.finished_at = finished_at
    new_run_row.status = "complete"
    new_run_row.record_count = len(result.pipeline.events)
    new_run_row.runtime_ms = int((finished_at - started_at).total_seconds() * 1000)
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="run.replay",
        subject_type="run",
        subject_id=new_run_id,
        payload={
            "parent_run_id": run_id,
            "reason": body.reason,
            "changed": len(result.diff.changed),
            "added": len(result.diff.added),
            "removed": len(result.diff.removed),
            "resolutions_carried": carried,
            "dry_run": dry_run,
        },
        created_at=finished_at,
        run_id=new_run_id,
        ruleset_hash=ruleset.ruleset_hash,
    )
    await finish(session, dry_run=dry_run)
    return ReplayOut(new_run_id=new_run_id, diff=result.diff)


@router.get("/{from_run_id}/diff/{to_run_id}", response_model=DiffOut)
async def diff_runs(
    from_run_id: str, to_run_id: str, session: AsyncSession = Depends(db_session)
) -> DiffOut:
    await _load(session, from_run_id)
    await _load(session, to_run_id)
    before = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.run_id == from_run_id))
    ).all()
    after = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.run_id == to_run_id))
    ).all()
    diff = diff_exceptions(
        [exception_from_row(e) for e in before], [exception_from_row(e) for e in after]
    )
    return DiffOut(from_run_id=from_run_id, to_run_id=to_run_id, diff=diff)


@router.delete("/{run_id}", status_code=204)
async def delete_run(
    run_id: str,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> None:
    """Soft delete: ``status`` moves to ``'deleted'``, nothing is removed —
    the audit trail and every row a run produced stay queryable, which is
    the whole point of an append-only ledger."""
    row = await _load(session, run_id)
    before_status = row.status
    row.status = "deleted"
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="run.delete",
        subject_type="run",
        subject_id=run_id,
        payload={"before_status": before_status, "dry_run": dry_run},
        created_at=datetime.now(UTC),
        run_id=run_id,
    )
    await finish(session, dry_run=dry_run)
