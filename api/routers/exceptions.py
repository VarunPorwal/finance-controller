"""PRD §5.7. The ranked human queue: read it, and the handful of verbs that
close, defer, or reshape one item. Every mutating verb is validate -> call
the engine's own pure functions (tier_for, priority_score, amount_band) for
anything that is a *decision* -> serialise; the router itself only moves
rows and logs the audit event (CLAUDE.md: "Routers validate, call engine,
serialise. No business logic in api/routers/.").
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit_log import append_audit
from api.converters import event_from_row, exception_from_row, match_from_row
from api.deps import AuthenticatedUser, current_user, db_session, finish, get_config
from api.errors import ApiError
from api.notify import notify_escalation
from api.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from db.models import ExceptionRow, TransactionEventRow
from db.models import Match as MatchRow
from fc.config import Config
from fc.exceptions.priority import priority_score
from fc.exceptions.tier import tier_for
from fc.models.exception_ import Exception_, ExceptionCategory, ExceptionStatus, Tier
from fc.models.ids import new_ulid
from fc.models.match import MatchResult
from fc.models.transaction import TransactionEvent
from fc.rules.learner import amount_band

router = APIRouter(prefix="/exceptions", tags=["exceptions"])

_RESOLVABLE_FROM: frozenset[ExceptionStatus] = frozenset(
    {"open", "monitoring", "snoozed", "escalated"}
)


class ExceptionEvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception: Exception_
    events: list[TransactionEvent]
    matches: list[MatchResult]


class ExceptionEntriesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_id: str
    events: list[TransactionEvent]


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str
    resolution_category: str | None = None


class WriteOffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class EscalateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class SnoozeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    until: date
    reason: str


class ReclassifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ExceptionCategory
    reason: str


class LinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    reason: str


class LinkOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception: Exception_
    residual_exception: Exception_ | None
    amount_delta_paise: int


class BulkAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_ids: list[str]
    action: Literal["resolve", "write_off", "escalate"]
    reason: str


class BulkResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_id: str
    ok: bool
    detail: str | None = None


class BulkOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[BulkResultOut]


@router.get("", response_model=Page[Exception_])
async def list_exceptions(
    run_id: str | None = None,
    status: ExceptionStatus | None = None,
    tier: Tier | None = None,
    category: ExceptionCategory | None = None,
    cluster_id: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, le=MAX_LIMIT, gt=0),
    cursor: str | None = None,
    session: AsyncSession = Depends(db_session),
) -> Page[Exception_]:
    stmt = select(ExceptionRow).order_by(
        ExceptionRow.priority_score.desc(), ExceptionRow.exception_id.desc()
    )
    if run_id is not None:
        stmt = stmt.where(ExceptionRow.run_id == run_id)
    if status is not None:
        stmt = stmt.where(ExceptionRow.status == status)
    if tier is not None:
        stmt = stmt.where(ExceptionRow.tier == tier)
    if category is not None:
        stmt = stmt.where(ExceptionRow.category == category)
    if cluster_id is not None:
        stmt = stmt.where(ExceptionRow.cluster_id == cluster_id)
    if cursor is not None:
        after_score, _, after_id = decode_cursor(cursor).partition("\0")
        stmt = stmt.where(
            (ExceptionRow.priority_score < Decimal(after_score))
            | (
                (ExceptionRow.priority_score == Decimal(after_score))
                & (ExceptionRow.exception_id < after_id)
            )
        )
    rows = (await session.scalars(stmt.limit(limit + 1))).all()
    page = rows[:limit]
    narrations = await _narrations(session, page)
    items = [exception_from_row(r, narrations=narrations.get(r.exception_id, ())) for r in page]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.priority_score}\0{last.exception_id}")
    return Page(items=items, next_cursor=next_cursor)


async def _load(session: AsyncSession, exception_id: str) -> ExceptionRow:
    row = await session.get(ExceptionRow, exception_id)
    if row is None:
        raise ApiError(404, "not found", f"no exception {exception_id}")
    return row


async def _narrations(
    session: AsyncSession, rows: Sequence[ExceptionRow]
) -> dict[str, list[str | None]]:
    """Linked narrations per exception, in one query for the whole page.

    Feeds the ``suspicious_narration`` flag (PRD §10.3 layer 6), which is
    derived on read rather than stored — there is no column for it and the
    schema is frozen, and recomputing means a sharpened heuristic applies to
    history rather than only to newly ingested rows.
    """
    event_ids = sorted({eid for row in rows for eid in row.event_ids})
    if not event_ids:
        return {}
    pairs = (
        await session.execute(
            select(TransactionEventRow.event_id, TransactionEventRow.raw_narration).where(
                TransactionEventRow.event_id.in_(event_ids)
            )
        )
    ).all()
    by_event = {event_id: narration for event_id, narration in pairs}
    return {
        row.exception_id: [by_event.get(eid) for eid in row.event_ids if eid in by_event]
        for row in rows
    }


@router.get("/{exception_id}", response_model=Exception_)
async def get_exception(
    exception_id: str, session: AsyncSession = Depends(db_session)
) -> Exception_:
    row = await _load(session, exception_id)
    narrations = await _narrations(session, [row])
    return exception_from_row(row, narrations=narrations.get(exception_id, ()))


@router.get("/{exception_id}/evidence", response_model=ExceptionEvidenceOut)
async def get_evidence(
    exception_id: str, session: AsyncSession = Depends(db_session)
) -> ExceptionEvidenceOut:
    row = await _load(session, exception_id)
    events = (
        await session.scalars(
            select(TransactionEventRow).where(TransactionEventRow.event_id.in_(row.event_ids))
        )
    ).all()
    # Scoped to the exception's own run. Without it the overlap predicate
    # returned the same logical match once per run that had ever reconciled
    # these events — four identical "Exact ref 100%" rows in the evidence pack
    # after four runs, growing by one on every reconciliation.
    matches = (
        await session.scalars(
            select(MatchRow).where(
                MatchRow.run_id == row.run_id,
                MatchRow.event_ids.overlap(row.event_ids),
            )
        )
    ).all()
    return ExceptionEvidenceOut(
        exception=exception_from_row(row, narrations=[e.raw_narration for e in events]),
        events=[event_from_row(e) for e in events],
        matches=[match_from_row(m) for m in matches],
    )


@router.get("/{exception_id}/entries", response_model=ExceptionEntriesOut)
async def get_entries(
    exception_id: str, session: AsyncSession = Depends(db_session)
) -> ExceptionEntriesOut:
    row = await _load(session, exception_id)
    events = (
        await session.scalars(
            select(TransactionEventRow).where(TransactionEventRow.event_id.in_(row.event_ids))
        )
    ).all()
    return ExceptionEntriesOut(
        exception_id=exception_id, events=[event_from_row(e) for e in events]
    )


def _require_resolvable(row: ExceptionRow) -> None:
    if row.status not in _RESOLVABLE_FROM:
        raise ApiError(
            409, "invalid transition", f"exception {row.exception_id} is already {row.status!r}"
        )


@router.post("/{exception_id}/resolve", response_model=Exception_)
async def resolve_exception(
    exception_id: str,
    body: ResolveRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> Exception_:
    row = await _load(session, exception_id)
    _require_resolvable(row)
    now = datetime.now(UTC)
    before_status = row.status

    row.status = "resolved"
    row.resolved_by = "human"
    row.resolved_by_user = user.user_id
    row.resolved_via = body.reason
    row.resolution_reason = body.reason
    row.resolution_category = body.resolution_category
    row.resolved_at = now
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="exception.resolve",
        subject_type="exception",
        subject_id=exception_id,
        payload={
            "before_status": before_status,
            "after_status": "resolved",
            "reason": body.reason,
            "resolution_category": body.resolution_category,
            "dry_run": dry_run,
        },
        created_at=now,
        run_id=row.run_id,
    )
    # Built before finish(): a rollback (dry_run=True) unconditionally expires
    # every ORM attribute on `row` — unlike commit, which respects
    # expire_on_commit=False — so reading row.* afterward would either raise
    # or silently reload the pre-mutation values from the database.
    result = exception_from_row(row)
    await finish(session, dry_run=dry_run)
    return result


@router.post("/{exception_id}/write-off", response_model=Exception_)
async def write_off_exception(
    exception_id: str,
    body: WriteOffRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> Exception_:
    row = await _load(session, exception_id)
    _require_resolvable(row)
    now = datetime.now(UTC)
    before_status = row.status

    row.status = "written_off"
    row.resolved_by = "human"
    row.resolved_by_user = user.user_id
    row.resolved_via = body.reason
    row.resolution_reason = body.reason
    row.resolution_category = "written_off"
    row.resolved_at = now
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="exception.write_off",
        subject_type="exception",
        subject_id=exception_id,
        payload={"before_status": before_status, "reason": body.reason, "dry_run": dry_run},
        created_at=now,
        run_id=row.run_id,
    )
    result = exception_from_row(row)
    await finish(session, dry_run=dry_run)
    return result


@router.post("/{exception_id}/escalate", response_model=Exception_)
async def escalate_exception(
    exception_id: str,
    body: EscalateRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> Exception_:
    row = await _load(session, exception_id)
    now = datetime.now(UTC)
    before_tier = row.tier

    row.status = "escalated"
    row.tier = "escalate"
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="exception.escalate",
        subject_type="exception",
        subject_id=exception_id,
        payload={"before_tier": before_tier, "reason": body.reason, "dry_run": dry_run},
        created_at=now,
        run_id=row.run_id,
    )
    result = exception_from_row(row)
    amount_paise = row.amount_paise
    await finish(session, dry_run=dry_run)
    if not dry_run:
        # N1 (§2.5.9). After the commit, so an email never announces a change
        # that was rolled back — and fire-and-forget, so Resend being down
        # cannot fail an escalation that has already happened.
        await notify_escalation(
            cfg,
            exception_id=exception_id,
            reason=body.reason,
            amount_paise=amount_paise,
        )
    return result


@router.post("/{exception_id}/snooze", response_model=Exception_)
async def snooze_exception(
    exception_id: str,
    body: SnoozeRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> Exception_:
    row = await _load(session, exception_id)
    now = datetime.now(UTC)

    row.status = "snoozed"
    row.recheck_at = datetime.combine(body.until, datetime.min.time(), tzinfo=UTC)
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="exception.snooze",
        subject_type="exception",
        subject_id=exception_id,
        payload={"until": body.until.isoformat(), "reason": body.reason, "dry_run": dry_run},
        created_at=now,
        run_id=row.run_id,
    )
    result = exception_from_row(row)
    await finish(session, dry_run=dry_run)
    return result


@router.post("/{exception_id}/reclassify", response_model=Exception_)
async def reclassify_exception(
    exception_id: str,
    body: ReclassifyRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> Exception_:
    row = await _load(session, exception_id)
    now = datetime.now(UTC)
    before_category = row.category

    row.category = body.category
    # Reclassifying can change everything tier_for gates on (NEVER_AUTO
    # membership, AUTO_SAFE membership) — recomputed via the same engine
    # function the pipeline itself uses, not re-derived here.
    decision = tier_for(body.category, confidence=row.confidence, cfg=cfg)
    row.tier = decision.tier
    row.recheck_at = decision.recheck_at
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="exception.reclassify",
        subject_type="exception",
        subject_id=exception_id,
        payload={
            "before_category": before_category,
            "after_category": body.category,
            "after_tier": decision.tier,
            "reason": body.reason,
            "dry_run": dry_run,
        },
        created_at=now,
        run_id=row.run_id,
    )
    result = exception_from_row(row)
    await finish(session, dry_run=dry_run)
    return result


@router.post("/{exception_id}/link", response_model=LinkOut)
async def link_exception(
    exception_id: str,
    body: LinkRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> LinkOut:
    """A human found the counterpart transaction the pipeline couldn't prove.

    Computes the amount delta between what the linked event covers and the
    exception's residual. If that closes the gap within tolerance, the
    exception resolves outright. If it doesn't, the *original* exception
    still resolves (the human's link is itself evidence, logged verbatim),
    but the money that remains unexplained becomes a brand new exception —
    same reasoning fc.rules.apply uses for a rule that only partially
    explains a gap ("a rule shrinks an exception, it doesn't pass or fail
    it"), applied to a human-supplied link instead of a rule.
    """
    row = await _load(session, exception_id)
    _require_resolvable(row)
    linked_event = await session.get(TransactionEventRow, body.event_id)
    if linked_event is None:
        raise ApiError(404, "not found", f"no event {body.event_id}")

    now = datetime.now(UTC)
    amount_delta_paise = linked_event.amount_paise
    new_residual_paise = abs(row.residual_paise - amount_delta_paise)
    tolerance_paise = cfg.tolerance_abs_paise
    merged_event_ids = sorted(set(row.event_ids) | {linked_event.event_id})

    row.event_ids = merged_event_ids
    row.status = "resolved"
    row.resolved_by = "human"
    row.resolved_by_user = user.user_id
    row.resolved_via = body.reason
    row.resolution_reason = body.reason
    row.resolution_category = (
        "linked" if new_residual_paise <= tolerance_paise else "linked_partial"
    )
    row.resolved_at = now
    row.residual_paise = new_residual_paise
    await session.flush()

    residual_exception: ExceptionRow | None = None
    if new_residual_paise > tolerance_paise:
        residual_confidence = Decimal("0.5000")
        decision = tier_for(row.category, confidence=residual_confidence, cfg=cfg)  # type: ignore[arg-type]
        priority = priority_score(
            amount_paise=new_residual_paise,
            tier=decision.tier,
            confidence=residual_confidence,
            deadline=None,
            as_of=now.date(),
            cluster_size=0,
        )
        residual_exception = ExceptionRow(
            exception_id=new_ulid("exc_"),
            run_id=row.run_id,
            tenant_id=user.tenant_id,
            event_ids=merged_event_ids,
            category=row.category,
            amount_paise=new_residual_paise,
            residual_paise=new_residual_paise,
            confidence=residual_confidence,
            tier=decision.tier,
            priority_score=priority,
            cluster_id=None,
            rules_applied=[],
            recommended_action=f"review the residual left after linking {linked_event.event_id}",
            recheck_at=decision.recheck_at,
            status="open",
            signature=f"{row.category}:linked_residual:{amount_band(new_residual_paise)}",
            created_at=now,
        )
        session.add(residual_exception)
        await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="exception.link",
        subject_type="exception",
        subject_id=exception_id,
        payload={
            "linked_event_id": linked_event.event_id,
            "amount_delta_paise": amount_delta_paise,
            "new_residual_paise": new_residual_paise,
            "residual_exception_id": residual_exception.exception_id
            if residual_exception
            else None,
            "reason": body.reason,
            "dry_run": dry_run,
        },
        created_at=now,
        run_id=row.run_id,
    )
    result = LinkOut(
        exception=exception_from_row(row),
        residual_exception=exception_from_row(residual_exception) if residual_exception else None,
        amount_delta_paise=amount_delta_paise,
    )
    await finish(session, dry_run=dry_run)
    return result


@router.post("/bulk", response_model=BulkOut)
async def bulk_action(
    body: BulkAction,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> BulkOut:
    now = datetime.now(UTC)
    results: list[BulkResultOut] = []
    for exception_id in body.exception_ids:
        row = await session.get(ExceptionRow, exception_id)
        if row is None:
            results.append(BulkResultOut(exception_id=exception_id, ok=False, detail="not found"))
            continue
        if row.status not in _RESOLVABLE_FROM:
            results.append(
                BulkResultOut(exception_id=exception_id, ok=False, detail=f"already {row.status}")
            )
            continue
        row.status = (
            "resolved"
            if body.action == "resolve"
            else ("written_off" if body.action == "write_off" else "escalated")
        )
        if body.action != "escalate":
            row.resolved_by = "human"
            row.resolved_by_user = user.user_id
            row.resolved_via = body.reason
            row.resolution_reason = body.reason
            row.resolved_at = now
        results.append(BulkResultOut(exception_id=exception_id, ok=True))

    await session.flush()
    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action=f"exception.bulk_{body.action}",
        subject_type="exception",
        subject_id=",".join(body.exception_ids),
        payload={
            "exception_ids": body.exception_ids,
            "action": body.action,
            "reason": body.reason,
            "dry_run": dry_run,
        },
        created_at=now,
    )
    await finish(session, dry_run=dry_run)
    return BulkOut(results=results)
