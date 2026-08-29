"""PRD §5.13. Liveness/readiness only — ``/metrics`` is Phase 2, not built here."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from api.deps import get_config, get_engine
from fc.config import Config

router = APIRouter(tags=["meta"])


class HealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    environment: str
    time: datetime


class ReadinessOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    database: bool


@router.get("/health", response_model=HealthOut)
async def health(cfg: Config = Depends(get_config)) -> HealthOut:
    return HealthOut(status="ok", environment=cfg.environment, time=datetime.now(UTC))


@router.get("/health/ready", response_model=ReadinessOut)
async def health_ready(engine: AsyncEngine = Depends(get_engine)) -> ReadinessOut:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return ReadinessOut(status="ok", database=True)
    except Exception:  # noqa: BLE001 - readiness reports, never raises
        return ReadinessOut(status="degraded", database=False)
