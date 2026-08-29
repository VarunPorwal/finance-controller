"""PRD §5.12/§12.5. Read-only: nothing here computes accuracy — that is
``fc.eval.report`` (CLAUDE.md: the Prompt 10 harness), which writes one row
per run to ``eval_results``. This router only serves what is already there.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import db_session
from api.errors import ApiError
from db.models import EvalResult

router = APIRouter(prefix="/eval", tags=["eval"])


class EvalResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision_pct: Decimal | None
    recall_pct: Decimal | None
    f1: Decimal | None
    abstention_pct: Decimal | None
    false_auto_resolutions: int
    auto_threshold: Decimal
    computed_at: datetime


class CoverageCurveOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    points: list[dict[str, Any]]


class ConfusionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    by_category: dict[str, Any]
    by_stage: dict[str, Any]


async def _load(session: AsyncSession, run_id: str) -> EvalResult:
    row = await session.get(EvalResult, run_id)
    if row is None:
        raise ApiError(404, "not found", f"no eval result for run {run_id}")
    return row


@router.get("/{run_id}", response_model=EvalResultOut)
async def get_eval_result(
    run_id: str, session: AsyncSession = Depends(db_session)
) -> EvalResultOut:
    row = await _load(session, run_id)
    return EvalResultOut(
        run_id=row.run_id,
        true_positive=row.true_positive,
        false_positive=row.false_positive,
        true_negative=row.true_negative,
        false_negative=row.false_negative,
        precision_pct=row.precision_pct,
        recall_pct=row.recall_pct,
        f1=row.f1,
        abstention_pct=row.abstention_pct,
        false_auto_resolutions=row.false_auto_resolutions,
        auto_threshold=row.auto_threshold,
        computed_at=row.computed_at,
    )


@router.get("/{run_id}/coverage-curve", response_model=CoverageCurveOut)
async def get_coverage_curve(
    run_id: str, session: AsyncSession = Depends(db_session)
) -> CoverageCurveOut:
    row = await _load(session, run_id)
    return CoverageCurveOut(run_id=run_id, points=list(row.coverage_curve))


@router.get("/{run_id}/confusion", response_model=ConfusionOut)
async def get_confusion(run_id: str, session: AsyncSession = Depends(db_session)) -> ConfusionOut:
    row = await _load(session, run_id)
    return ConfusionOut(
        run_id=run_id, by_category=dict(row.by_category), by_stage=dict(row.by_stage)
    )
