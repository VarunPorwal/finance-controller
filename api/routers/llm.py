"""Read-only listing of ``llm_calls`` — the per-call ledger
``api.deps.persist_llm_calls`` already writes (CLAUDE.md: "the router cannot
log to llm_calls ... it emits LLMCallRecord to an injected sink"). Nothing
here computes anything; it serves what generation and matching already
wrote, for Controller Activity's LLM-cost view. No dollar-cost field exists
on the table (only token counts), so cost stays a client-side computation
against a pricing table — this endpoint hands back tokens, not money.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import db_session
from api.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from db.models import LLMCall

router = APIRouter(prefix="/llm", tags=["llm"])


class LLMCallOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    call_id: str
    run_id: str | None
    purpose: str
    provider: str
    model: str
    tier: str
    ladder_position: int
    cached: bool
    input_tokens: int | None
    output_tokens: int | None
    thinking_tokens: int | None
    latency_ms: int | None
    outcome: str
    verified: bool | None
    created_at: datetime


def _call_out(row: LLMCall) -> LLMCallOut:
    return LLMCallOut(
        call_id=row.call_id,
        run_id=row.run_id,
        purpose=row.purpose,
        provider=row.provider,
        model=row.model,
        tier=row.tier,
        ladder_position=row.ladder_position,
        cached=row.cached,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        thinking_tokens=row.thinking_tokens,
        latency_ms=row.latency_ms,
        outcome=row.outcome,
        verified=row.verified,
        created_at=row.created_at,
    )


@router.get("/calls", response_model=Page[LLMCallOut])
async def list_llm_calls(
    run_id: str | None = None,
    purpose: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, le=MAX_LIMIT, gt=0),
    cursor: str | None = None,
    session: AsyncSession = Depends(db_session),
) -> Page[LLMCallOut]:
    stmt = select(LLMCall).order_by(LLMCall.created_at.desc(), LLMCall.call_id.desc())
    if run_id is not None:
        stmt = stmt.where(LLMCall.run_id == run_id)
    if purpose is not None:
        stmt = stmt.where(LLMCall.purpose == purpose)
    if cursor is not None:
        stmt = stmt.where(LLMCall.call_id < decode_cursor(cursor))
    rows = (await session.scalars(stmt.limit(limit + 1))).all()
    items = [_call_out(r) for r in rows[:limit]]
    next_cursor = encode_cursor(items[-1].call_id) if len(rows) > limit else None
    return Page(items=items, next_cursor=next_cursor)
