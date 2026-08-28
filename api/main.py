"""FastAPI application entrypoint.

Routers land in a later prompt (PRD §5). Routers validate, call the engine and
serialise; no business logic lives in ``api/routers/``.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.deps import get_config

app = FastAPI(
    title="AI Finance Controller",
    version="0.1.0",
    description="Reconciles Razorpay settlements, Indian bank statements and Tally ledgers.",
)


@app.get("/health")
async def health() -> dict[str, str]:
    config = get_config()
    return {
        "status": "ok",
        "environment": config.environment,
        "llm_mode": config.llm_mode,
    }
