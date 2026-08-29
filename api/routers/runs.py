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

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from api.audit_log import append_audit
from api.converters import event_from_row, exception_from_row
from api.deps import AuthenticatedUser, current_user, db_session, finish, get_config
from api.errors import ApiError
from api.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from db.models import Cluster as ClusterRow
from db.models import ExceptionRow, Run, TransactionEventRow
from db.models import Match as MatchRow
from fc.audit.replay import ReplayDiff, diff_exceptions, replay
from fc.config import Config
from fc.eval.corpus import load_corpus
from fc.models.ids import deterministic_factory, new_ulid
from fc.pipeline import PIPELINE_STAGES, PipelineResult, run_pipeline
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules

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


class DiffOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_run_id: str
    to_run_id: str
    diff: ReplayDiff


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    seed: int = 8


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


@router.get("", response_model=Page[RunOut])
async def list_runs(
    limit: int = Query(DEFAULT_LIMIT, le=MAX_LIMIT, gt=0),
    cursor: str | None = None,
    session: AsyncSession = Depends(db_session),
) -> Page[RunOut]:
    stmt = select(Run).order_by(Run.started_at.desc(), Run.run_id.desc())
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
        event_count=await _count(session, TransactionEventRow, TransactionEventRow.run_id, run_id),
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
    session: AsyncSession, *, run_id: str, tenant_id: str, result: PipelineResult
) -> None:
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
) -> RunOut:
    started_at = datetime.now(UTC)
    run_id = new_ulid("run_")
    ruleset = load_rules(DEFAULT_RULES_PATH, tenant_id=user.tenant_id, created_at=started_at)
    corpus = load_corpus()
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
        input_hashes={"corpus": ruleset.ruleset_hash},
        config=cfg.model_dump(mode="json", exclude=_SECRET_FIELDS),
    )
    session.add(run_row)
    await session.flush()

    result = run_pipeline(
        corpus.events,
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
    """
    parent = await _load(session, run_id)
    parent_event_rows = (
        await session.scalars(
            select(TransactionEventRow).where(TransactionEventRow.run_id == run_id)
        )
    ).all()
    if not parent_event_rows:
        raise ApiError(409, "nothing to replay", f"run {run_id} has no events")
    parent_exception_rows = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.run_id == run_id))
    ).all()

    events = [event_from_row(e) for e in parent_event_rows]
    parent_exceptions = [exception_from_row(e) for e in parent_exception_rows]

    ruleset = load_rules(DEFAULT_RULES_PATH, tenant_id=user.tenant_id, created_at=datetime.now(UTC))
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
        input_hashes=dict(parent.input_hashes),
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
        session, run_id=new_run_id, tenant_id=user.tenant_id, result=result.pipeline
    )

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
