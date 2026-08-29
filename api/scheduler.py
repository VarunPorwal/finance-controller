"""APScheduler jobs — PRD §2.5.4 E8 (recheck), §0.4 (cache refresh, Prompt 9),
keep-alive.

Started only from FastAPI's lifespan handler in ``api/main.py``, never at
import time — importing this module, or ``api.main`` itself, must never
start a background job on its own. That is exactly the failure mode this
gets built to rule out: pytest collecting ``api.main`` (which every router
test in this repo does), or ``python -m api.main --openapi`` regenerating
the TypeScript client, must not have a recheck job silently mutating
``exceptions`` rows mid-run. Two independent gates enforce it:

1. ``build_scheduler``/``start`` are only ever called from the lifespan
   context manager, which only fires on a real ASGI ``startup`` event —
   plain module import, and this repo's own httpx/``ASGITransport`` tests
   (which never send the lifespan messages), can't reach it.
2. ``Config.scheduler_enabled`` defaults to ``False``. Even a future test
   harness that *does* trigger ASGI lifespan (Starlette's ``TestClient`` used
   as a context manager, say) still starts nothing unless a real deployment's
   environment explicitly turns this on.

**Single instance only** (documented Tier-1 limitation): this scheduler runs
in-process with no leader election and no distributed lock. Two API
replicas would each fire their own copy of every job — correct for one
instance, wrong the moment there are two.

Each job loops over every active tenant, opening its own
``api.deps.scoped_session`` per tenant: a background job has no bearer token
to resolve a tenant from, and RLS hides every row from ``fc_app_user`` until
``app.tenant_id`` is set, so there is no such thing as a single cross-tenant
query here — only a loop of single-tenant ones. ``tenants`` itself carries
no RLS (db/migrations: "the table the tenant id is resolved *from*"), so
listing active tenants needs no scope at all.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, text

from api.audit_log import append_audit
from api.deps import scoped_session
from api.notify import notify_escalation
from db.models import ExceptionRow, Match, Tenant
from fc.config import Config

__all__ = ["build_scheduler", "cache_refresh_job", "keep_alive_job", "recheck_job", "start", "stop"]

_LOG = logging.getLogger("fc.scheduler")

RECHECK_INTERVAL = timedelta(hours=6)
CACHE_REFRESH_INTERVAL = timedelta(minutes=55)
KEEP_ALIVE_INTERVAL = timedelta(minutes=4)

_SCHEDULER_ROLE = "system"


async def _active_tenant_ids() -> list[str]:
    async with scoped_session("", _SCHEDULER_ROLE) as session:
        # tenants carries no RLS, so app.tenant_id being empty here is fine —
        # this is the one query in the whole job that is meant to see every
        # tenant, not one.
        rows = await session.scalars(select(Tenant.tenant_id).where(Tenant.status == "active"))
        return list(rows.all())


async def recheck_job(cfg: Config) -> None:
    """§2.5.4 E8: every monitoring exception past its ``recheck_at`` gets one
    more look. Resolved if a match has since covered its event_ids (a later
    run proved what this one couldn't); otherwise ``recheck_count`` climbs,
    and three failures escalates it — ``Config.max_rechecks`` is the same
    constant the pipeline's own tiering reads, so "three" is defined once.
    """
    now = datetime.now(UTC)
    for tenant_id in await _active_tenant_ids():
        async with scoped_session(tenant_id, _SCHEDULER_ROLE) as session:
            due = await session.scalars(
                select(ExceptionRow).where(
                    ExceptionRow.status == "monitoring", ExceptionRow.recheck_at <= now
                )
            )
            for exc in due.all():
                now_matched = await session.scalar(
                    select(Match.match_id).where(Match.event_ids.overlap(exc.event_ids)).limit(1)
                )
                if now_matched is not None:
                    exc.status = "resolved"
                    exc.resolved_by = "recheck"
                    exc.resolved_at = now
                    exc.resolution_reason = "matched by a later run"
                    await append_audit(
                        session,
                        tenant_id=tenant_id,
                        actor="scheduler",
                        action="exception.recheck_resolved",
                        subject_type="exception",
                        subject_id=exc.exception_id,
                        payload={"match_id": now_matched},
                        created_at=now,
                        run_id=exc.run_id,
                    )
                    continue

                exc.recheck_count += 1
                if exc.recheck_count >= cfg.max_rechecks:
                    exc.status = "escalated"
                    exc.tier = "escalate"
                    await append_audit(
                        session,
                        tenant_id=tenant_id,
                        actor="scheduler",
                        action="exception.recheck_escalated",
                        subject_type="exception",
                        subject_id=exc.exception_id,
                        payload={"recheck_count": exc.recheck_count},
                        created_at=now,
                        run_id=exc.run_id,
                    )
                    # Fire-and-forget: notify_escalation never raises, so a
                    # Resend outage can't abort the recheck loop partway
                    # through a tenant's exceptions.
                    await notify_escalation(
                        cfg,
                        exception_id=exc.exception_id,
                        reason=f"{exc.recheck_count} failed rechecks",
                    )
                else:
                    exc.recheck_at = now + timedelta(days=cfg.recheck_interval_days)
                    await append_audit(
                        session,
                        tenant_id=tenant_id,
                        actor="scheduler",
                        action="exception.recheck_deferred",
                        subject_type="exception",
                        subject_id=exc.exception_id,
                        payload={
                            "recheck_count": exc.recheck_count,
                            "next": exc.recheck_at.isoformat(),
                        },
                        created_at=now,
                        run_id=exc.run_id,
                    )
            await session.commit()


async def cache_refresh_job(cfg: Config) -> None:
    """Refreshes the Gemini context cache. A no-op until Prompt 9 builds
    ``fc.llm`` — logged, not silently skipped, so its absence is visible in
    the scheduler's own logs rather than looking like a job that ran and
    found nothing to do."""
    _LOG.info("cache_refresh: no-op — fc.llm is not yet built (Prompt 9)")


async def keep_alive_job(cfg: Config) -> None:
    """Pings Neon so the free-tier database doesn't suspend from inactivity.
    The only job here that touches no tenant data, so it needs no RLS scope
    at all — a bare ``SELECT 1`` over the owner-agnostic connection."""
    async with scoped_session("", _SCHEDULER_ROLE) as session:
        await session.execute(text("SELECT 1"))


def build_scheduler(cfg: Config) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        recheck_job,
        IntervalTrigger(seconds=RECHECK_INTERVAL.total_seconds()),
        args=[cfg],
        id="recheck",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        cache_refresh_job,
        IntervalTrigger(seconds=CACHE_REFRESH_INTERVAL.total_seconds()),
        args=[cfg],
        id="cache_refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        keep_alive_job,
        IntervalTrigger(seconds=KEEP_ALIVE_INTERVAL.total_seconds()),
        args=[cfg],
        id="keep_alive",
        replace_existing=True,
        misfire_grace_time=60,
    )
    return scheduler


def start(cfg: Config) -> AsyncIOScheduler | None:
    """Returns the running scheduler, or ``None`` if ``scheduler_enabled`` is
    off — the only entry point ``api.main``'s lifespan handler calls."""
    if not cfg.scheduler_enabled:
        _LOG.info("scheduler disabled (SCHEDULER_ENABLED is not set)")
        return None
    scheduler = build_scheduler(cfg)
    scheduler.start()
    _LOG.info("scheduler started: recheck=6h cache_refresh=55m keep_alive=4m")
    return scheduler


def stop(scheduler: AsyncIOScheduler | None) -> None:
    if scheduler is not None:
        scheduler.shutdown(wait=False)
