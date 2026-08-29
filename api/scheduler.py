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
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, text

from api.audit_log import append_audit
from api.deps import get_llm_client, scoped_session
from api.notify import (
    notify_daily_digest,
    notify_deadline_reminder,
    notify_escalation,
)
from db.models import ExceptionRow, Match, Tenant
from fc.config import Config
from fc.models.money import fmt_inr

__all__ = [
    "build_scheduler",
    "cache_refresh_job",
    "daily_digest_job",
    "deadline_reminder_job",
    "keep_alive_job",
    "recheck_job",
    "start",
    "stop",
]

_LOG = logging.getLogger("fc.scheduler")

RECHECK_INTERVAL = timedelta(hours=6)
CACHE_REFRESH_INTERVAL = timedelta(minutes=55)
KEEP_ALIVE_INTERVAL = timedelta(minutes=4)

#: N4 fires this far ahead of a deadline (§2.5.9).
_DEADLINE_HORIZON = timedelta(hours=48)

#: The digest and the deadline sweep both mean "still in the queue".
_OPEN_STATUSES = ("open", "monitoring", "snoozed", "escalated")

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
    """Refreshes the Gemini context cache — PRD §7.6.

    Fifty-five minutes against a one-hour TTL, so the cache never lapses
    between refreshes. The text-to-SQL system prompt carries the schema, the
    column semantics and twenty worked examples — around 8k tokens reused on
    every question — so caching it explicitly is most of the input cost of the
    Ask tab.

    Failure here is not an outage: the calls simply pay full input rate, which
    is why ``refresh_context_cache`` logs and returns ``None`` rather than
    raising. In ``cache_only`` or ``off`` mode it does nothing at all.
    """
    if cfg.offline:
        _LOG.info("cache_refresh: skipped (LLM_MODE=%s)", cfg.llm_mode)
        return
    name = await get_llm_client().refresh_context_cache()
    if name is None:
        _LOG.info("cache_refresh: no cache created; text_to_sql pays full input rate")
    else:
        _LOG.info("cache_refresh: text_to_sql context cache is %s", name)


async def daily_digest_job(cfg: Config) -> None:
    """N2 (§2.5.9). One message per tenant: what the queue looks like today.

    Built from counts and sums the database computed, formatted here — there is
    no model on this path, so a digest is never wrong about a number even when
    every provider is down.
    """
    for tenant_id in await _active_tenant_ids():
        async with scoped_session(tenant_id, _SCHEDULER_ROLE) as session:
            rows = (
                await session.scalars(
                    select(ExceptionRow).where(ExceptionRow.status.in_(_OPEN_STATUSES))
                )
            ).all()
            if not rows:
                _LOG.info("daily_digest: nothing open for %s", tenant_id)
                continue
            await notify_daily_digest(cfg, summary=_digest(rows))


def _digest(rows: Sequence[ExceptionRow]) -> str:
    by_tier: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for row in rows:
        by_tier[row.tier] = by_tier.get(row.tier, 0) + 1
        by_category[row.category] = by_category.get(row.category, 0) + 1
    unexplained = sum(r.residual_paise for r in rows)
    largest = max(rows, key=lambda r: r.amount_paise)
    lines = [
        f"{len(rows)} open items, {fmt_inr(unexplained)} unexplained.",
        "",
        "By tier:",
        *(f"  {tier:<12} {count}" for tier, count in sorted(by_tier.items())),
        "",
        "By category:",
        *(
            f"  {category:<28} {count}"
            for category, count in sorted(by_category.items(), key=lambda kv: -kv[1])
        ),
        "",
        f"Largest: {largest.exception_id} — {fmt_inr(largest.amount_paise)} "
        f"({largest.category.replace('_', ' ')})",
    ]
    return "\n".join(lines)


async def deadline_reminder_job(cfg: Config) -> None:
    """N4 (§2.5.9). Forty-eight hours before a consequence lands.

    A chargeback contest window closing is not the kind of thing to learn about
    on the day. The window itself is computed by ``fc.exceptions.consequence``
    at classification time; this only reads the date it wrote.
    """
    horizon = (datetime.now(UTC) + _DEADLINE_HORIZON).date()
    today = datetime.now(UTC).date()
    for tenant_id in await _active_tenant_ids():
        async with scoped_session(tenant_id, _SCHEDULER_ROLE) as session:
            due = (
                await session.scalars(
                    select(ExceptionRow).where(
                        ExceptionRow.status.in_(_OPEN_STATUSES),
                        ExceptionRow.deadline.is_not(None),
                        ExceptionRow.deadline <= horizon,
                        ExceptionRow.deadline >= today,
                    )
                )
            ).all()
            for exc in due:
                assert exc.deadline is not None
                await notify_deadline_reminder(
                    cfg,
                    exception_id=exc.exception_id,
                    deadline=exc.deadline,
                    consequence=exc.consequence or "a deadline on this item is about to pass",
                    amount_paise=exc.amount_paise,
                )


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
    # Daily, at 07:00 UTC — 12:30 IST, which lands in a finance team's morning
    # rather than overnight. The only cron trigger here; everything else is an
    # interval, because everything else is about elapsed time, not a time of day.
    scheduler.add_job(
        daily_digest_job,
        CronTrigger(hour=7, minute=0),
        args=[cfg],
        id="daily_digest",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        deadline_reminder_job,
        CronTrigger(hour=7, minute=15),
        args=[cfg],
        id="deadline_reminder",
        replace_existing=True,
        misfire_grace_time=3600,
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
    _LOG.info(
        "scheduler started: recheck=6h cache_refresh=55m keep_alive=4m "
        "daily_digest=07:00Z deadline_reminder=07:15Z"
    )
    return scheduler


def stop(scheduler: AsyncIOScheduler | None) -> None:
    if scheduler is not None:
        scheduler.shutdown(wait=False)
