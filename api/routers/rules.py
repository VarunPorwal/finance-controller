"""PRD §5.9. Rules are immutable per version (CLAUDE.md hard rule 8) — this
router never UPDATEs a ``rules`` row's ``deductions``/``scope``/``tolerance``;
a change is always a new version, enforced twice over (the DB trigger, and
this router never attempting it). Bulk import is cut per §0.1.

``backtest`` and ``suggestions`` both need a historical case's original
``gap_paise``/``gross_paise`` (§2.6 D4/D5), which the schema stores nowhere
on ``exceptions`` — only ``amount_paise`` and ``residual_paise`` survive past
the run that produced them. Both approximate ``gap_paise`` with
``residual_paise`` and ``gross_paise`` with ``amount_paise``; noted here once
rather than at each call site.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit_log import append_audit
from api.converters import event_from_row, rule_from_row
from api.deps import AuthenticatedUser, current_user, db_session, finish, get_config
from api.errors import ApiError
from db.models import ExceptionRow, TransactionEventRow
from db.models import Rule as RuleRow
from fc.config import Config
from fc.models.ids import new_ulid
from fc.models.rule import Deduction, Rule, RuleStatus, Scope, Tolerance
from fc.rules.backtest import BacktestResult, CaseTruth, HistoricalCase, backtest
from fc.rules.evaluator import evaluate_deductions
from fc.rules.learner import Resolution, detect_drafts
from fc.rules.loader import version_hash

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
    cases: list[HistoricalCase] = []
    for row in rows:
        if not row.event_ids:
            continue
        event_row = await session.get(TransactionEventRow, row.event_ids[0])
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
    )


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
        payload={"reason": body.reason, "version_hash": row.version_hash, "dry_run": dry_run},
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
    session: AsyncSession = Depends(db_session), user: AuthenticatedUser = Depends(current_user)
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
