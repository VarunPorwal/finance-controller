"""PRD §5.11. The bridge is recomputed live from a run's own stored events and
exceptions via ``fc.cash.bridge.compute_cash_bridge`` — the same pure engine
function the pipeline calls — never persisted separately, so there is no
stored bridge that can drift from what the events actually say.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.converters import event_from_row, exception_from_row
from api.deps import db_session
from api.errors import ApiError
from api.run_scope import event_source_run_id
from db.models import ExceptionRow, TransactionEventRow
from fc.cash.bridge import CashBridge, compute_cash_bridge

router = APIRouter(prefix="/cash", tags=["cash"])


class BridgeSegmentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    #: This segment's place in the bridge arithmetic. For "Unexplained" that is
    #: expected_net - actual_bank, the residual the whole bridge balances on.
    amount_paise: int
    event_ids: list[str]
    exception_ids: list[str]
    #: What ``exception_ids`` actually total. Not the same quantity as
    #: ``amount_paise`` and not reconcilable with it — the residual is net over
    #: the corpus, these are gross per-discrepancy amounts. A drill-down must
    #: display this one, or it shows rows that do not add up to its own heading.
    attributed_paise: int = 0


class CashBridgeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    gross_collected_paise: int
    deductions: list[BridgeSegmentOut]
    expected_net_paise: int
    actual_bank_paise: int
    unexplained_paise: int
    segments: list[BridgeSegmentOut]
    cash_at_risk_paise: int
    reserve_pending_release_paise: int
    gst_input_credit_claimable_paise: int


def _segment_out(segment: object) -> BridgeSegmentOut:
    return BridgeSegmentOut(
        label=segment.label,  # type: ignore[attr-defined]
        amount_paise=segment.amount_paise,  # type: ignore[attr-defined]
        event_ids=list(segment.event_ids),  # type: ignore[attr-defined]
        exception_ids=list(segment.exception_ids),  # type: ignore[attr-defined]
        attributed_paise=segment.attributed_paise,  # type: ignore[attr-defined]
    )


def _bridge_out(run_id: str, bridge: CashBridge) -> CashBridgeOut:
    return CashBridgeOut(
        run_id=run_id,
        gross_collected_paise=bridge.gross_collected_paise,
        deductions=[_segment_out(s) for s in bridge.deductions],
        expected_net_paise=bridge.expected_net_paise,
        actual_bank_paise=bridge.actual_bank_paise,
        unexplained_paise=bridge.unexplained_paise,
        segments=[_segment_out(s) for s in bridge.segments],
        cash_at_risk_paise=bridge.cash_at_risk_paise,
        reserve_pending_release_paise=bridge.reserve_pending_release_paise,
        gst_input_credit_claimable_paise=bridge.gst_input_credit_claimable_paise,
    )


async def _compute(session: AsyncSession, run_id: str) -> CashBridge:
    # A replay cites its parent's events (api/run_scope.py). Filtering on
    # run_id alone is what made this endpoint 404 on every replayed run.
    event_run_id = await event_source_run_id(session, run_id)
    events = (
        await session.scalars(
            select(TransactionEventRow).where(TransactionEventRow.run_id == event_run_id)
        )
    ).all()
    if not events:
        raise ApiError(404, "not found", f"no events for run {run_id}")
    exceptions = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.run_id == run_id))
    ).all()
    return compute_cash_bridge(
        [event_from_row(e) for e in events], [exception_from_row(x) for x in exceptions]
    )


@router.get("/bridge", response_model=CashBridgeOut)
async def get_bridge(
    run_id: str = Query(...), session: AsyncSession = Depends(db_session)
) -> CashBridgeOut:
    return _bridge_out(run_id, await _compute(session, run_id))


@router.get("/at-risk", response_model=CashBridgeOut)
async def get_at_risk(
    run_id: str = Query(...), session: AsyncSession = Depends(db_session)
) -> CashBridgeOut:
    """Same computation as ``/bridge`` — ``cash_at_risk_paise`` and the
    segments that make it up are already fields on the one bridge object;
    this endpoint exists as the narrower, purpose-named view PRD §5.11 lists."""
    return _bridge_out(run_id, await _compute(session, run_id))


@router.get("/reserve", response_model=CashBridgeOut)
async def get_reserve(
    run_id: str = Query(...), session: AsyncSession = Depends(db_session)
) -> CashBridgeOut:
    return _bridge_out(run_id, await _compute(session, run_id))


@router.get("/gst-input", response_model=CashBridgeOut)
async def get_gst_input(
    run_id: str = Query(...), session: AsyncSession = Depends(db_session)
) -> CashBridgeOut:
    return _bridge_out(run_id, await _compute(session, run_id))
