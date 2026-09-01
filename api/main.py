"""FastAPI application — PRD §5. CORS restricted to the exact frontend
origin (never ``*``): a wildcard would defeat the point of Bearer auth, since
any origin could then read the response of an authenticated request.

``python -m api.main --openapi`` prints the OpenAPI document to stdout and
exits, which is what ``scripts/dev.ps1``'s ``client`` target pipes into
``openapi-typescript`` to regenerate ``web/lib/api.ts``.

The scheduler starts from ``lifespan`` below, which only runs on a real ASGI
``startup`` event — not on module import, and not under this repo's own
httpx/``ASGITransport`` test transport, which never sends that event. See
``api/scheduler.py``'s module docstring for the second, independent gate.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import scheduler as scheduler_module
from api.deps import get_config, scoped_session
from api.errors import register_exception_handlers
from api.routers import (
    agent,
    audit,
    auth,
    cash,
    clusters,
    events,
    exceptions,
    ingest,
    llm,
    matches,
    meta,
    rules,
    runs,
)
from api.routers import eval as eval_router
from api.routers import (
    settings as settings_router,
)
from api.ruleset import seed_bundled_rule_sets, seed_rules_from_yaml
from fc.config import Config


async def _seed_rules(cfg: Config) -> None:
    """Import data/rules/deductions.yaml into the ``rules`` table, once.

    The YAML is a provision-time seed now, not a run-time read (api/ruleset.py).
    Doing it here rather than in a migration keeps rules as data the Rulebook
    owns — a migration would re-assert the file's opinion over anything a human
    has since changed, which is exactly the coupling being removed. The import
    is idempotent on ``(rule_id, version)``, so a redeploy is a no-op.

    Failure is logged and swallowed: an API that will not start because a seed
    file is unreadable is worse than one running on the rules already in the
    table.
    """
    # No database configured means nothing to seed — and it keeps the promise
    # that driving the lifespan (tests/unit/test_scheduler.py does exactly that)
    # touches no database and no network. Without this guard the seed opened an
    # asyncpg connection inside the no-DB unit suite.
    if not cfg.tenant_id or not cfg.database_url:
        return
    try:
        async with scoped_session(cfg.tenant_id, "owner") as session:
            now = datetime.now(UTC)
            inserted = await seed_rules_from_yaml(session, tenant_id=cfg.tenant_id, created_at=now)
            # Every rulebook the repo ships, each into its own set, so having
            # the second dataset configured never costs you the demo's rules.
            inserted += await seed_bundled_rule_sets(
                session, tenant_id=cfg.tenant_id, created_at=now
            )
            await session.commit()
        _LOG.info("rule seed: %d rule version(s) imported for %s", inserted, cfg.tenant_id)
    except Exception:  # noqa: BLE001
        _LOG.exception("rule seed failed; continuing with the rules already in the table")


_LOG = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    cfg = get_config()
    await _seed_rules(cfg)
    running = scheduler_module.start(cfg)
    try:
        yield
    finally:
        scheduler_module.stop(running)


app = FastAPI(
    title="AI Finance Controller",
    version="0.1.0",
    description="Reconciles Razorpay settlements, bank statements and Tally ledger exports.",
    lifespan=lifespan,
)

register_exception_handlers(app)

_cfg = get_config()
if _cfg.frontend_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_cfg.frontend_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(meta.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(matches.router, prefix="/api/v1")
app.include_router(exceptions.router, prefix="/api/v1")
app.include_router(clusters.router, prefix="/api/v1")
app.include_router(rules.router, prefix="/api/v1")
app.include_router(cash.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(eval_router.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(settings_router.router, prefix="/api/v1")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--openapi" in args:
        json.dump(app.openapi(), sys.stdout, indent=2)
        return 0
    print("usage: python -m api.main --openapi", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
