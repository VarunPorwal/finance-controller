"""PRD §5.5. Read-only: transaction events are written by ingestion, never
edited here. ``/events/{id}/similar`` (pgvector cosine search) is omitted —
``narration_vec`` shipped in the schema but embeddings themselves are cut
per §0.1, so there is nothing for that endpoint to search yet.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.converters import event_from_row
from api.deps import db_session
from api.errors import ApiError
from api.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from api.run_scope import event_source_run_id
from db.models import TransactionEventRow
from fc.models.transaction import Direction, Source, TransactionEvent

router = APIRouter(prefix="/events", tags=["events"])


class RawEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    source: Source
    raw: dict[str, Any]


@router.get("", response_model=Page[TransactionEvent])
async def list_events(
    run_id: str | None = None,
    source: Source | None = None,
    direction: Direction | None = None,
    settlement_id: str | None = None,
    order_id: str | None = None,
    utr: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, le=MAX_LIMIT, gt=0),
    cursor: str | None = None,
    session: AsyncSession = Depends(db_session),
) -> Page[TransactionEvent]:
    stmt = select(TransactionEventRow).order_by(TransactionEventRow.event_id.desc())
    if run_id is not None:
        # Resolve through the lineage so ?run_id=<a replay> lists the events
        # that replay actually reconciled rather than nothing.
        stmt = stmt.where(TransactionEventRow.run_id == await event_source_run_id(session, run_id))
    if source is not None:
        stmt = stmt.where(TransactionEventRow.source == source)
    if direction is not None:
        stmt = stmt.where(TransactionEventRow.direction == direction)
    if settlement_id is not None:
        stmt = stmt.where(TransactionEventRow.settlement_id == settlement_id)
    if order_id is not None:
        stmt = stmt.where(TransactionEventRow.order_id == order_id)
    if utr is not None:
        stmt = stmt.where(TransactionEventRow.utr == utr)
    if cursor is not None:
        stmt = stmt.where(TransactionEventRow.event_id < decode_cursor(cursor))
    rows = (await session.scalars(stmt.limit(limit + 1))).all()
    items = [event_from_row(r) for r in rows[:limit]]
    next_cursor = encode_cursor(items[-1].event_id) if len(rows) > limit else None
    return Page(items=items, next_cursor=next_cursor)


class EventCountOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_source: dict[str, int]
    total: int


@router.get("/count", response_model=EventCountOut)
async def count_events(
    run_id: str | None = None, session: AsyncSession = Depends(db_session)
) -> EventCountOut:
    """A plain ``GROUP BY source, count(*)`` behind the same RLS-scoped
    session every other read uses. ``Page[T]`` deliberately carries no total
    (PRD: cursor pagination, not offset), so screens that only need "how
    many, by source" — Reconcile's Sources card, Records, Data Sources —
    would otherwise have to page through every row just to count them.
    """
    stmt = select(TransactionEventRow.source, func.count()).group_by(TransactionEventRow.source)
    if run_id is not None:
        stmt = stmt.where(TransactionEventRow.run_id == await event_source_run_id(session, run_id))
    rows = (await session.execute(stmt)).all()
    by_source = {source: count for source, count in rows}
    return EventCountOut(by_source=by_source, total=sum(by_source.values()))


async def _load(session: AsyncSession, event_id: str) -> TransactionEventRow:
    row = await session.get(TransactionEventRow, event_id)
    if row is None:
        raise ApiError(404, "not found", f"no event {event_id}")
    return row


@router.get("/{event_id}", response_model=TransactionEvent)
async def get_event(event_id: str, session: AsyncSession = Depends(db_session)) -> TransactionEvent:
    return event_from_row(await _load(session, event_id))


@router.get("/{event_id}/raw", response_model=RawEventOut)
async def get_event_raw(event_id: str, session: AsyncSession = Depends(db_session)) -> RawEventOut:
    row = await _load(session, event_id)
    return RawEventOut(event_id=row.event_id, source=row.source, raw=row.raw)  # type: ignore[arg-type]
