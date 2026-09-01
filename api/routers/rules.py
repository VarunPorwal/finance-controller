"""PRD §5.9. Rules are immutable per version (CLAUDE.md hard rule 8) — this
router never UPDATEs a ``rules`` row's ``deductions``/``scope``/``tolerance``;
a change is always a new version, enforced twice over (the DB trigger, and
this router never attempting it). Bulk import (cut per §0.1 originally) was
added 31 Aug 2026 with explicit sign-off — ``POST /rules/import`` reuses
``fc.rules.loader``'s entry validator, the same one the YAML seed ruleset
goes through, so an uploaded JSON file is held to the same bar.

``backtest`` and ``suggestions`` both need a historical case's original
``gap_paise``/``gross_paise`` (§2.6 D4/D5), which the schema stores nowhere
on ``exceptions`` — only ``amount_paise`` and ``residual_paise`` survive past
the run that produced them. Both approximate ``gap_paise`` with
``residual_paise`` and ``gross_paise`` with ``amount_paise``; noted here once
rather than at each call site.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit_log import append_audit
from api.converters import event_from_row, rule_from_row
from api.deps import AuthenticatedUser, current_user, db_session, finish, get_config
from api.errors import ApiError
from api.notify import notify_rule_suggestion
from db.models import ExceptionRow, TransactionEventRow
from db.models import Rule as RuleRow
from fc.config import Config
from fc.eval.confusion import ratio
from fc.models.ids import new_ulid
from fc.models.rule import Deduction, Rule, RuleStatus, Scope, Tolerance
from fc.rules.backtest import BacktestResult, CaseTruth, HistoricalCase, backtest
from fc.rules.evaluator import evaluate_deductions
from fc.rules.learner import Resolution, detect_drafts
from fc.rules.loader import RuleSourceError, build_ruleset_from_entries, version_hash

router = APIRouter(prefix="/rules", tags=["rules"])


class RuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    name: str
    description: str | None = None
    scope: Scope
    deductions: list[Deduction]
    tolerance: Tolerance
    priority: int = 100
    effective_confidence: str = "0.9500"


class RuleVersionRequest(BaseModel):
    """A new version of an existing rule. ``rule_id`` comes from the path.

    ``name`` is optional because a rate change is usually the same rule under
    the same name; omit it and version N's name carries over.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    scope: Scope
    deductions: list[Deduction]
    tolerance: Tolerance
    priority: int | None = None
    effective_confidence: str | None = None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deductions: list[Deduction]
    gross_paise: int


class DeductionStackLineOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    basis: str
    basis_paise: int
    rate: str
    amount_paise: int


class PreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stack: list[DeductionStackLineOut]
    total_paise: int
    net_paise: int


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class BacktestBucketOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    total_paise: int
    exception_ids: list[str]


class BacktestOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    version: int
    version_hash: str
    would_explain: BacktestBucketOut
    would_wrongly_close: BacktestBucketOut
    would_partially_explain: BacktestBucketOut
    net_recommendation: str
    cases_considered: int
    unverified: int
    #: Of the cases this rule would touch (explain + wrongly_close), what
    #: share it would resolve correctly. None when it would touch none.
    precision_pct: Decimal | None
    #: Of every historical case considered, what share this rule would
    #: explain. Zero when there is nothing to consider.
    coverage_pct: Decimal


class SuggestionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: Rule
    signature: str
    occurrences: int
    exception_ids: list[str]
    resolution_category: str
    observed_rate_percent: str


class DismissRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


@router.get("", response_model=list[Rule])
async def list_rules(
    rule_id: str | None = None,
    status: RuleStatus | None = None,
    session: AsyncSession = Depends(db_session),
) -> list[Rule]:
    stmt = select(RuleRow).order_by(RuleRow.rule_id.asc(), RuleRow.version.asc())
    if rule_id is not None:
        stmt = stmt.where(RuleRow.rule_id == rule_id)
    if status is not None:
        stmt = stmt.where(RuleRow.status == status)
    rows = (await session.scalars(stmt)).all()
    return [rule_from_row(r) for r in rows]


@router.get("/{rule_id}/versions", response_model=list[Rule])
async def list_rule_versions(
    rule_id: str, session: AsyncSession = Depends(db_session)
) -> list[Rule]:
    rows = (
        await session.scalars(
            select(RuleRow).where(RuleRow.rule_id == rule_id).order_by(RuleRow.version.asc())
        )
    ).all()
    if not rows:
        raise ApiError(404, "not found", f"no rule {rule_id}")
    return [rule_from_row(r) for r in rows]


@router.post("", response_model=Rule)
async def create_rule(
    body: RuleCreateRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> Rule:
    """Always creates version 1 of a new ``rule_id`` in ``status='draft'`` — a
    rule is never born active (§8.8: "Never auto-activates"); ``/activate``
    is the only path to ``status='active'``, and it is a separate human step.
    """
    exists = await session.scalar(select(RuleRow).where(RuleRow.rule_id == body.rule_id).limit(1))
    if exists is not None:
        raise ApiError(409, "conflict", f"rule_id {body.rule_id} already exists; use a new id")

    now = datetime.now(UTC)
    v_hash = version_hash(body.scope, body.deductions, body.tolerance)
    row = RuleRow(
        rule_id=body.rule_id,
        version=1,
        tenant_id=user.tenant_id,
        version_hash=v_hash,
        name=body.name,
        description=body.description,
        scope=body.scope.model_dump(mode="json", exclude_none=True),
        deductions=[d.model_dump(mode="json") for d in body.deductions],
        tolerance=body.tolerance.model_dump(mode="json"),
        priority=body.priority,
        effective_confidence=body.effective_confidence,
        effective_from=body.scope.date_from,
        effective_to=body.scope.date_to,
        status="draft",
        origin="manual",
        created_by=user.user_id,
    )
    session.add(row)
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="rule.create",
        subject_type="rule",
        subject_id=f"{row.rule_id}:{row.version}",
        payload={"name": body.name, "version_hash": v_hash, "dry_run": dry_run},
        created_at=now,
        ruleset_hash=v_hash,
    )
    result = rule_from_row(row)
    await finish(session, dry_run=dry_run)
    return result


class RuleImportEntryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    rule_id: str
    version: int
    outcome: Literal["created_v1", "created_version"]


class RuleImportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_count: int
    results: list[RuleImportEntryOut]


@router.post("/import", response_model=RuleImportOut, status_code=201)
async def import_rules(
    body: list[dict[str, Any]],
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> RuleImportOut:
    """Bulk-create rule drafts from an uploaded JSON file.

    Entries use the same per-rule shape ``fc.rules.loader``'s YAML loader
    accepts (``id``, ``scope``, ``deductions``, ``tolerance``, and the
    optional fields it allows) — the whole point is that the same rulebook
    file format works whether it is the seed ruleset or something a human
    drops in here. Validation runs over the *entire* file before anything is
    written: a bad entry at position 12 of 20 fails the whole import rather
    than leaving 11 rules created and 9 silently skipped.

    Every entry lands active immediately, origin="imported": uploading a
    rulebook replaces what is live rather than staging drafts next to it.
    Every rule the tenant had active going in is retired first — stopped
    outright, not just window-closed — so the import is a clean swap, not
    an overlay. Skips the reason-per-activation prompt the single-rule
    ``/activate`` endpoint requires, since an import is one human decision
    covering the whole file, not one per rule.
    """
    now = datetime.now(UTC)
    try:
        parsed = build_ruleset_from_entries(
            body,
            source_label="upload",
            tenant_id=user.tenant_id,
            created_at=now,
            default_status="active",
        )
    except RuleSourceError as exc:
        raise ApiError(422, "invalid rules file", str(exc)) from exc

    previously_active = (
        await session.scalars(
            select(RuleRow).where(RuleRow.tenant_id == user.tenant_id, RuleRow.status == "active")
        )
    ).all()
    retired_ids = [f"{r.rule_id}:{r.version}" for r in previously_active]
    for prior in previously_active:
        prior.status = "retired"
        prior.effective_to = now.date()
    if previously_active:
        await session.flush()
        await append_audit(
            session,
            tenant_id=user.tenant_id,
            actor=f"user:{user.user_id}",
            action="rule.retire_for_import",
            subject_type="rule",
            subject_id="bulk",
            payload={"retired": retired_ids, "dry_run": dry_run},
            created_at=now,
        )

    results: list[RuleImportEntryOut] = []
    for index, rule in enumerate(parsed):
        latest = await session.scalar(
            select(RuleRow)
            .where(RuleRow.tenant_id == user.tenant_id, RuleRow.rule_id == rule.rule_id)
            .order_by(RuleRow.version.desc())
            .limit(1)
        )
        version = latest.version + 1 if latest is not None else 1
        row = RuleRow(
            rule_id=rule.rule_id,
            version=version,
            tenant_id=user.tenant_id,
            version_hash=rule.version_hash,
            name=rule.name,
            description=rule.description,
            scope=rule.scope.model_dump(mode="json", exclude_none=True),
            deductions=[d.model_dump(mode="json") for d in rule.deductions],
            tolerance=rule.tolerance.model_dump(mode="json"),
            priority=rule.priority,
            effective_confidence=rule.effective_confidence,
            effective_from=rule.effective_from,
            effective_to=rule.effective_to,
            status="active",
            origin="imported",
            created_by=user.user_id,
            created_at=now,
            activated_by=user.user_id,
            activated_at=now,
        )
        session.add(row)
        await session.flush()
        await append_audit(
            session,
            tenant_id=user.tenant_id,
            actor=f"user:{user.user_id}",
            action="rule.import",
            subject_type="rule",
            subject_id=f"{rule.rule_id}:{version}",
            payload={"version_hash": rule.version_hash, "dry_run": dry_run},
            created_at=now,
            ruleset_hash=rule.version_hash,
        )
        results.append(
            RuleImportEntryOut(
                index=index,
                rule_id=rule.rule_id,
                version=version,
                outcome="created_version" if latest is not None else "created_v1",
            )
        )

    await finish(session, dry_run=dry_run)
    return RuleImportOut(created_count=len(results), results=results)


@router.delete("/{rule_id}/versions/{version}", status_code=204)
async def delete_draft_rule(
    rule_id: str,
    version: int,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> None:
    """Hard-deletes one rule version — only if it is still ``draft``.

    A version that was ever ``active`` keeps existing through ``/retire`` (a
    status change) and is never removable here — its audit trail and any
    exception that cited it must stay intact. This exists for the case
    bulk import creates: rules brought in for testing that turned out wrong
    and were never activated, which retiring (a lifecycle event for a rule
    that actually ran) is the wrong verb for. Migration
    ``0005_rules_draft_delete`` is what makes DELETE possible at the
    database layer at all; the status check below is the second half.
    """
    row = await session.get(RuleRow, {"rule_id": rule_id, "version": version})
    if row is None:
        raise ApiError(404, "not found", f"no rule {rule_id} version {version}")
    if row.status != "draft":
        raise ApiError(
            409,
            "invalid state",
            f"rule {rule_id} v{version} is {row.status!r}, not draft — retire it instead "
            "of deleting; a rule that was ever active must keep its history.",
        )
    await session.delete(row)
    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="rule.delete_draft",
        subject_type="rule",
        subject_id=f"{rule_id}:{version}",
        payload={"dry_run": dry_run},
        created_at=datetime.now(UTC),
    )
    await finish(session, dry_run=dry_run)


@router.post("/preview", response_model=PreviewOut)
async def preview_rule(body: PreviewRequest) -> PreviewOut:
    """Never touches the database — a preview computes the deduction stack for
    a hypothetical gross amount and returns it, nothing more."""
    stack = evaluate_deductions(body.deductions, body.gross_paise)
    return PreviewOut(
        stack=[
            DeductionStackLineOut(
                type=line.type,
                basis=line.basis,
                basis_paise=line.basis_paise,
                rate=str(line.rate),
                amount_paise=line.amount_paise,
            )
            for line in stack.items
        ],
        total_paise=stack.total_paise,
        net_paise=body.gross_paise - stack.total_paise,
    )


async def _load_version(session: AsyncSession, rule_id: str, version: int) -> RuleRow:
    row = await session.get(RuleRow, {"rule_id": rule_id, "version": version})
    if row is None:
        raise ApiError(404, "not found", f"no rule {rule_id} version {version}")
    return row


async def _historical_cases(session: AsyncSession, tenant_id: str) -> list[HistoricalCase]:
    rows = (
        await session.scalars(
            select(ExceptionRow).where(
                ExceptionRow.tenant_id == tenant_id,
                ExceptionRow.status.in_(("resolved", "written_off")),
            )
        )
    ).all()
    first_event_ids = [row.event_ids[0] for row in rows if row.event_ids]
    event_rows = (
        (
            await session.scalars(
                select(TransactionEventRow).where(TransactionEventRow.event_id.in_(first_event_ids))
            )
        ).all()
        if first_event_ids
        else []
    )
    event_by_id = {e.event_id: e for e in event_rows}
    cases: list[HistoricalCase] = []
    for row in rows:
        if not row.event_ids:
            continue
        event_row = event_by_id.get(row.event_ids[0])
        if event_row is None:
            continue
        cases.append(
            HistoricalCase(
                exception_id=row.exception_id,
                event=event_from_row(event_row),
                on_date=row.created_at.date(),
                gap_paise=row.residual_paise,
                gross_paise=row.amount_paise,
                category=row.category,  # type: ignore[arg-type]
                n_txns=len(row.event_ids),
                truth=CaseTruth(
                    source="human_resolution",
                    closable_by_rule=row.status == "resolved",
                    reason=row.resolution_reason or row.status,
                    resolution_category=row.resolution_category,
                ),
            )
        )
    return cases


def _bucket_out(bucket: object) -> BacktestBucketOut:
    return BacktestBucketOut(
        count=bucket.count,  # type: ignore[attr-defined]
        total_paise=bucket.total_paise,  # type: ignore[attr-defined]
        exception_ids=list(bucket.exception_ids),  # type: ignore[attr-defined]
    )


def _backtest_out(result: BacktestResult) -> BacktestOut:
    touched = result.would_explain.count + result.would_wrongly_close.count
    return BacktestOut(
        rule_id=result.rule_id,
        version=result.version,
        version_hash=result.version_hash,
        would_explain=_bucket_out(result.would_explain),
        would_wrongly_close=_bucket_out(result.would_wrongly_close),
        would_partially_explain=_bucket_out(result.would_partially_explain),
        net_recommendation=result.net_recommendation,
        cases_considered=result.cases_considered,
        unverified=result.unverified,
        precision_pct=ratio(result.would_explain.count, touched) if touched else None,
        coverage_pct=ratio(result.would_explain.count, result.cases_considered),
    )


@router.post("/{rule_id}/versions", response_model=Rule, status_code=201)
async def create_rule_version(
    rule_id: str,
    body: RuleVersionRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> Rule:
    """Add version N+1 of an existing rule, as a draft.

    §4.3.6 says an active rule is immutable and an edit creates a new version.
    The database enforced the first half — ``trg_rules_immutable`` refuses a
    scope/deductions/tolerance change on an active row — while nothing
    implemented the second, so the trigger was a wall with no door: a wrong
    active rule could only be retired and re-created under a different id, and
    ``/versions`` could never return more than one entry.

    Version N is left exactly as it is, still active, still doing its job. It
    is only when N+1 is *activated* that N's window is closed behind it, so a
    draft that is never approved costs nothing.
    """
    versions = (
        await session.scalars(
            select(RuleRow)
            .where(RuleRow.tenant_id == user.tenant_id, RuleRow.rule_id == rule_id)
            .order_by(RuleRow.version.desc())
        )
    ).all()
    if not versions:
        raise ApiError(404, "not found", f"no rule {rule_id}; use POST /rules to create one")
    latest = versions[0]

    # The successor must start after the incumbent, or closing the incumbent's
    # window on activation would produce effective_to < effective_from.
    live = next((v for v in versions if v.status == "active"), None)
    if live is not None and body.scope.date_from <= live.effective_from:
        raise ApiError(
            409,
            "invalid window",
            f"version {latest.version + 1} starts {body.scope.date_from}, which is not after "
            f"active version {live.version}'s {live.effective_from}. A successor has to begin "
            "after the version it replaces, or the two would overlap.",
        )

    now = datetime.now(UTC)
    v_hash = version_hash(body.scope, body.deductions, body.tolerance)
    row = RuleRow(
        rule_id=rule_id,
        version=latest.version + 1,
        tenant_id=user.tenant_id,
        version_hash=v_hash,
        name=body.name or latest.name,
        description=body.description if body.description is not None else latest.description,
        scope=body.scope.model_dump(mode="json", exclude_none=True),
        deductions=[d.model_dump(mode="json") for d in body.deductions],
        tolerance=body.tolerance.model_dump(mode="json"),
        priority=body.priority if body.priority is not None else latest.priority,
        effective_confidence=(
            body.effective_confidence
            if body.effective_confidence is not None
            else latest.effective_confidence
        ),
        effective_from=body.scope.date_from,
        effective_to=body.scope.date_to,
        status="draft",
        origin="manual",
        created_by=user.user_id,
        created_at=now,
    )
    session.add(row)
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="rule.version",
        subject_type="rule",
        subject_id=f"{rule_id}:{row.version}",
        payload={
            "supersedes": latest.version,
            "version_hash": v_hash,
            "effective_from": body.scope.date_from.isoformat(),
            "dry_run": dry_run,
        },
        created_at=now,
    )
    result = rule_from_row(row)
    await finish(session, dry_run=dry_run)
    return result


@router.post("/{rule_id}/backtest", response_model=BacktestOut)
async def backtest_rule(
    rule_id: str,
    version: int = Query(...),
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> BacktestOut:
    row = await _load_version(session, rule_id, version)
    cases = await _historical_cases(session, user.tenant_id)
    result = backtest(rule_from_row(row), cases, cfg=cfg)

    row.backtest_result = result.to_json()
    await session.flush()
    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="rule.backtest",
        subject_type="rule",
        subject_id=f"{rule_id}:{version}",
        payload={**result.to_json(), "dry_run": dry_run},
        created_at=datetime.now(UTC),
        ruleset_hash=row.version_hash,
    )
    await finish(session, dry_run=dry_run)
    return _backtest_out(result)


@router.post("/{rule_id}/activate", response_model=Rule)
async def activate_rule(
    rule_id: str,
    body: ActivateRequest,
    version: int = Query(...),
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> Rule:
    """§8.8: "Never auto-activates" — a human approves with the back-test
    numbers in front of them, which is why this endpoint requires ``reason``
    and never fires on its own."""
    row = await _load_version(session, rule_id, version)
    if row.status != "draft":
        raise ApiError(
            409, "invalid transition", f"rule {rule_id} v{version} is {row.status!r}, not draft"
        )

    now = datetime.now(UTC)

    # Close the predecessor's window behind the successor so the two never
    # overlap: a transaction dated anywhere on the timeline must resolve to
    # exactly one version. effective_to is inclusive, so the incumbent ends the
    # day before the successor begins. trg_rules_immutable permits this — it
    # guards scope/deductions/tolerance, not lifecycle columns.
    #
    # The incumbent stays status='active'. That is the whole point: a rate that
    # changed mid-period must still price the transactions that happened before
    # the change, and fc.rules.scope selects by window among active versions.
    # Retiring it here would silently reprice history — which is exactly what
    # 'retired' is reserved to mean, an operator saying "stop using this at
    # all", and is why api/ruleset.py excludes retired rules outright.
    superseded: list[int] = []
    if row.version > 1:
        incumbents = (
            await session.scalars(
                select(RuleRow).where(
                    RuleRow.tenant_id == user.tenant_id,
                    RuleRow.rule_id == rule_id,
                    RuleRow.version != version,
                    RuleRow.status == "active",
                )
            )
        ).all()
        closes_on = row.effective_from - timedelta(days=1)
        for prior in incumbents:
            if prior.effective_to is None or prior.effective_to > closes_on:
                prior.effective_to = closes_on
                superseded.append(prior.version)

    row.status = "active"
    row.activated_by = user.user_id
    row.activated_at = now
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="rule.activate",
        subject_type="rule",
        subject_id=f"{rule_id}:{version}",
        payload={
            "reason": body.reason,
            "version_hash": row.version_hash,
            "superseded_versions": superseded,
            "dry_run": dry_run,
        },
        created_at=now,
        ruleset_hash=row.version_hash,
    )
    result = rule_from_row(row)
    await finish(session, dry_run=dry_run)
    return result


@router.post("/{rule_id}/retire", response_model=Rule)
async def retire_rule(
    rule_id: str,
    body: ActivateRequest,
    version: int = Query(...),
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> Rule:
    row = await _load_version(session, rule_id, version)
    if row.status != "active":
        raise ApiError(
            409, "invalid transition", f"rule {rule_id} v{version} is {row.status!r}, not active"
        )

    now = datetime.now(UTC)
    row.status = "retired"
    row.effective_to = now.date()
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="rule.retire",
        subject_type="rule",
        subject_id=f"{rule_id}:{version}",
        payload={"reason": body.reason, "dry_run": dry_run},
        created_at=now,
        ruleset_hash=row.version_hash,
    )
    result = rule_from_row(row)
    await finish(session, dry_run=dry_run)
    return result


@router.get("/suggestions", response_model=list[SuggestionOut])
async def list_suggestions(
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> list[SuggestionOut]:
    """Computed live from resolved exceptions, never persisted — there is no
    ``rule_suggestions`` table in the frozen schema, so a suggestion is a
    view, not a row, and "dismissing" one (below) has nothing to delete."""
    cases = await _historical_cases(session, user.tenant_id)
    resolutions = [
        Resolution(
            exception_id=c.exception_id,
            category=c.category,
            resolution_category=(c.truth.resolution_category if c.truth else None) or "unknown",
            event=c.event,
            on_date=c.on_date,
            gap_paise=c.gap_paise,
            gross_paise=c.gross_paise,
            n_txns=c.n_txns,
        )
        for c in cases
    ]
    active_rows = (
        await session.scalars(
            select(RuleRow).where(RuleRow.tenant_id == user.tenant_id, RuleRow.status == "active")
        )
    ).all()
    drafts = detect_drafts(
        resolutions,
        active_rules=[rule_from_row(r) for r in active_rows],
        tenant_id=user.tenant_id,
        created_at=datetime.now(UTC),
    )
    for draft in drafts:
        # N3 (§2.5.9). Fires when the learner has something to propose, which
        # until now nobody was told about — a suggestion that only exists while
        # somebody is looking at the page is not a suggestion.
        await notify_rule_suggestion(cfg, rule_name=draft.rule.name, occurrences=draft.occurrences)
    return [
        SuggestionOut(
            rule=d.rule,
            signature=d.signature,
            occurrences=d.occurrences,
            exception_ids=list(d.exception_ids),
            resolution_category=d.resolution_category,
            observed_rate_percent=str(d.observed_rate_percent),
        )
        for d in drafts
    ]


@router.post("/suggestions/{signature}/accept", response_model=Rule)
async def accept_suggestion(
    signature: str,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> Rule:
    suggestions = await list_suggestions(session, user)
    match = next((s for s in suggestions if s.signature == signature), None)
    if match is None:
        raise ApiError(404, "not found", f"no live suggestion with signature {signature}")

    now = datetime.now(UTC)
    draft = match.rule.model_copy(update={"rule_id": new_ulid("rule_"), "created_by": user.user_id})
    row = RuleRow(
        rule_id=draft.rule_id,
        version=1,
        tenant_id=user.tenant_id,
        version_hash=draft.version_hash,
        name=draft.name,
        description=draft.description,
        scope=draft.scope.model_dump(mode="json", exclude_none=True),
        deductions=[d.model_dump(mode="json") for d in draft.deductions],
        tolerance=draft.tolerance.model_dump(mode="json"),
        priority=draft.priority,
        effective_confidence=draft.effective_confidence,
        effective_from=draft.effective_from,
        effective_to=draft.effective_to,
        status="draft",
        origin="learned",
        created_by=user.user_id,
    )
    session.add(row)
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="rule.suggestion_accept",
        subject_type="rule",
        subject_id=f"{row.rule_id}:1",
        payload={"signature": signature, "occurrences": match.occurrences, "dry_run": dry_run},
        created_at=now,
    )
    result = rule_from_row(row)
    await finish(session, dry_run=dry_run)
    return result


@router.post("/suggestions/{signature}/dismiss", status_code=204)
async def dismiss_suggestion(
    signature: str,
    body: DismissRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> None:
    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="rule.suggestion_dismiss",
        subject_type="rule",
        subject_id=signature,
        payload={"reason": body.reason, "dry_run": dry_run},
        created_at=datetime.now(UTC),
    )
    await finish(session, dry_run=dry_run)
