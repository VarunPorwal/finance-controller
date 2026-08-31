"""PRD §5.12. The router that proves Prompt 8's whole thesis: every decision
this system made is a query, not an assertion. ``GET /audit/verify-chain``
just fetches a range and hands it to ``fc.audit.ledger.verify_chain`` — it
does not know the hash-chain rules itself, only how to ask the question.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import AuthenticatedUser, current_user, db_session
from api.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from db.models import AuditEvent
from fc.audit.ledger import GENESIS_HASH, sequence_gaps, verify_chain

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    tenant_id: str
    run_id: str | None
    actor: str
    action: str
    subject_type: str
    subject_id: str
    payload: dict[str, Any]
    ruleset_hash: str | None
    prev_hash: str
    this_hash: str
    created_at: datetime


class SequenceGapOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    after_seq: int
    next_seq: int
    missing: int


class VerifyChainOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    checked: int
    first_break_seq: int | None = None
    reason: str | None = None
    #: Non-consecutive seq values in the verified range. Advisory: seq is a
    #: BIGSERIAL and PostgreSQL burns numbers on rolled-back transactions, so
    #: gaps are normal. A gap caused by an actual deletion breaks the hash link
    #: and shows up in ``valid``/``reason`` instead.
    gaps: list[SequenceGapOut] = []
    #: Present when the range verified clean but contains gaps worth a human
    #: glance. Never a failure.
    advisory: str | None = None


def _event_out(row: AuditEvent) -> AuditEventOut:
    return AuditEventOut(
        seq=row.seq,
        tenant_id=row.tenant_id,
        run_id=row.run_id,
        actor=row.actor,
        action=row.action,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        payload=row.payload,
        ruleset_hash=row.ruleset_hash,
        prev_hash=row.prev_hash,
        this_hash=row.this_hash,
        created_at=row.created_at,
    )


@router.get("", response_model=Page[AuditEventOut])
async def list_audit_events(
    subject_type: str | None = None,
    subject_id: str | None = None,
    actor: str | None = None,
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(DEFAULT_LIMIT, le=MAX_LIMIT, gt=0),
    cursor: str | None = None,
    session: AsyncSession = Depends(db_session),
) -> Page[AuditEventOut]:
    stmt = select(AuditEvent).order_by(AuditEvent.seq.desc())
    if subject_type is not None:
        stmt = stmt.where(AuditEvent.subject_type == subject_type)
    if subject_id is not None:
        stmt = stmt.where(AuditEvent.subject_id == subject_id)
    if actor is not None:
        stmt = stmt.where(AuditEvent.actor == actor)
    if from_ is not None:
        stmt = stmt.where(AuditEvent.created_at >= from_)
    if to is not None:
        stmt = stmt.where(AuditEvent.created_at <= to)
    if cursor is not None:
        stmt = stmt.where(AuditEvent.seq < int(decode_cursor(cursor)))
    rows = (await session.scalars(stmt.limit(limit + 1))).all()
    items = [_event_out(r) for r in rows[:limit]]
    next_cursor = encode_cursor(str(items[-1].seq)) if len(rows) > limit else None
    return Page(items=items, next_cursor=next_cursor)


@router.get("/verify-chain", response_model=VerifyChainOut)
async def get_verify_chain(
    from_seq: int = Query(1, ge=1),
    to_seq: int | None = Query(None, ge=1),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> VerifyChainOut:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.tenant_id == user.tenant_id, AuditEvent.seq >= from_seq)
        .order_by(AuditEvent.seq.asc())
    )
    if to_seq is not None:
        stmt = stmt.where(AuditEvent.seq <= to_seq)
    rows = (await session.scalars(stmt)).all()

    if not rows:
        return VerifyChainOut(valid=True, checked=0)

    # No range-start check. It used to return invalid whenever rows[0].seq !=
    # from_seq, and since from_seq defaults to 1 while this tenant's chain
    # starts at 702, the default call short-circuited with checked=0 — every
    # verification this endpoint ever performed verified nothing. A chain that
    # starts later than requested is not evidence of anything; a chain whose
    # *first* row is missing is, and passing GENESIS_HASH below catches that.
    events = [
        {
            "seq": r.seq,
            "prev_hash": r.prev_hash,
            "this_hash": r.this_hash,
            "payload": r.payload,
            "actor": r.actor,
            "action": r.action,
            "subject_id": r.subject_id,
        }
        for r in rows
    ]
    # A fetch from the beginning is the whole chain, so its first row must
    # chain from the genesis hash. Anything else means row one is gone. A
    # sub-range has no such anchor and is verified internally.
    expected_prev_hash = GENESIS_HASH if from_seq <= 1 else None
    valid, first_break_seq, reason = verify_chain(events, expected_prev_hash=expected_prev_hash)
    gaps = [
        SequenceGapOut(after_seq=after, next_seq=nxt, missing=nxt - after - 1)
        for after, nxt in sequence_gaps(events)
    ]
    advisory = None
    if valid and gaps:
        total = sum(g.missing for g in gaps)
        advisory = (
            f"{len(gaps)} sequence gap(s) totalling {total} unused seq value(s). "
            "The hash chain is intact across them, so these are BIGSERIAL numbers "
            "burned by rolled-back transactions, not deleted rows — a deletion "
            "would have broken the link."
        )
    return VerifyChainOut(
        valid=valid,
        checked=len(events),
        first_break_seq=first_break_seq,
        reason=reason,
        gaps=gaps,
        advisory=advisory,
    )


@router.get("/export")
async def export_audit(
    run_id: str | None = None,
    format: str = Query("jsonl", pattern="^(csv|jsonl)$"),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> StreamingResponse:
    """The one deliberately non-Pydantic response in this API: a file stream
    has no JSON shape to model, and PRD §5.12 names it as a file download."""
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.tenant_id == user.tenant_id)
        .order_by(AuditEvent.seq.asc())
    )
    if run_id is not None:
        stmt = stmt.where(AuditEvent.run_id == run_id)
    rows = (await session.scalars(stmt)).all()

    if format == "jsonl":

        def jsonl() -> str:
            buf = io.StringIO()
            for r in rows:
                buf.write(json.dumps(_event_out(r).model_dump(mode="json")) + "\n")
            return buf.getvalue()

        return StreamingResponse(
            iter([jsonl()]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=audit_export.jsonl"},
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "seq",
            "tenant_id",
            "run_id",
            "actor",
            "action",
            "subject_type",
            "subject_id",
            "created_at",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.seq,
                r.tenant_id,
                r.run_id,
                r.actor,
                r.action,
                r.subject_type,
                r.subject_id,
                r.created_at,
            ]
        )
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_export.csv"},
    )
