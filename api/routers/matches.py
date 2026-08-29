"""PRD §5.6. Read-only: matches are formed by the pipeline, never edited here."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.converters import event_from_row, match_from_row
from api.deps import db_session
from api.errors import ApiError
from api.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from db.models import Match as MatchRow
from db.models import TransactionEventRow
from fc.models.match import MatchResult, MatchStage
from fc.models.transaction import TransactionEvent

router = APIRouter(prefix="/matches", tags=["matches"])


class MatchEvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match: MatchResult
    events: list[TransactionEvent]


@router.get("", response_model=Page[MatchResult])
async def list_matches(
    run_id: str | None = None,
    stage: MatchStage | None = None,
    auto_closed: bool | None = None,
    limit: int = Query(DEFAULT_LIMIT, le=MAX_LIMIT, gt=0),
    cursor: str | None = None,
    session: AsyncSession = Depends(db_session),
) -> Page[MatchResult]:
    stmt = select(MatchRow).order_by(MatchRow.confidence.desc(), MatchRow.match_id.desc())
    if run_id is not None:
        stmt = stmt.where(MatchRow.run_id == run_id)
    if stage is not None:
        stmt = stmt.where(MatchRow.stage == stage)
    if auto_closed is not None:
        stmt = stmt.where(MatchRow.auto_closed == auto_closed)
    if cursor is not None:
        after_confidence, _, after_id = decode_cursor(cursor).partition("\0")
        stmt = stmt.where(
            (MatchRow.confidence < Decimal(after_confidence))
            | ((MatchRow.confidence == Decimal(after_confidence)) & (MatchRow.match_id < after_id))
        )
    rows = (await session.scalars(stmt.limit(limit + 1))).all()
    items = [match_from_row(r) for r in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.confidence}\0{last.match_id}")
    return Page(items=items, next_cursor=next_cursor)


async def _load(session: AsyncSession, match_id: str) -> MatchRow:
    row = await session.get(MatchRow, match_id)
    if row is None:
        raise ApiError(404, "not found", f"no match {match_id}")
    return row


@router.get("/{match_id}", response_model=MatchResult)
async def get_match(match_id: str, session: AsyncSession = Depends(db_session)) -> MatchResult:
    return match_from_row(await _load(session, match_id))


@router.get("/{match_id}/evidence", response_model=MatchEvidenceOut)
async def get_match_evidence(
    match_id: str, session: AsyncSession = Depends(db_session)
) -> MatchEvidenceOut:
    row = await _load(session, match_id)
    events = (
        await session.scalars(
            select(TransactionEventRow).where(TransactionEventRow.event_id.in_(row.event_ids))
        )
    ).all()
    return MatchEvidenceOut(match=match_from_row(row), events=[event_from_row(e) for e in events])
