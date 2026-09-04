"""Tenant-level settings stored in ``tenants.settings`` (JSONB) — no schema
change, the column already exists and already held ``default_run_id`` before
that was retired (``api/routers/runs.py``).

Two settings: the "Email me when a run finishes" toggle, off by default (a
run must not start emailing a tenant's finance team until someone opts in),
and the address that email goes to. When no address is set the run-complete
email falls back to the tenant's finance users, as it always did.

``POST /settings/send-run-summary`` sends the same run-complete email for the
current run on demand, so the toggle can be exercised without waiting for a
run, and so a judge can watch an email arrive.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit_log import append_audit
from api.deps import AuthenticatedUser, current_user, db_session, finish, get_config
from api.errors import ApiError
from api.notify import notify_run_complete
from api.routers.cash import _compute as compute_bridge
from api.run_scope import event_source_run_id
from db.models import EvalResult, ExceptionRow, Run, Tenant, TransactionEventRow, User
from fc.config import Config
from fc.models.money import fmt_inr

router = APIRouter(prefix="/settings", tags=["settings"])

_EMAIL_TOGGLE_KEY = "email_on_run_complete"
_EMAIL_LAST_SENT_KEY = "email_last_sent_at"
_EMAIL_TO_KEY = "notify_email"
_EMAIL_ROLES = ("finance_manager", "finance_exec")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class TenantSettingsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_on_run_complete: bool
    email_last_sent_at: datetime | None = None
    notify_email: str | None = None
    #: Whether a Resend key is configured. False means "send" logs and does
    #: nothing; the UI says so instead of pretending an email went out.
    email_configured: bool = False


class TenantSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_on_run_complete: bool
    notify_email: str | None = None

    @field_validator("notify_email")
    @classmethod
    def _valid_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) > 254 or not _EMAIL_RE.match(value):
            raise ValueError("not a valid email address")
        return value


class SendSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    recipients: list[str]
    headline: str
    #: False when no Resend key or no recipient is configured; the email was
    #: not sent and ``reason`` says why.
    sent: bool
    reason: str | None = None


def _settings_out(settings: dict[str, object], cfg: Config) -> TenantSettingsOut:
    sent = settings.get(_EMAIL_LAST_SENT_KEY)
    to = settings.get(_EMAIL_TO_KEY)
    return TenantSettingsOut(
        email_on_run_complete=bool(settings.get(_EMAIL_TOGGLE_KEY, False)),
        email_last_sent_at=datetime.fromisoformat(str(sent)) if sent else None,
        notify_email=str(to) if to else None,
        email_configured=bool(cfg.resend_api_key),
    )


@router.get("", response_model=TenantSettingsOut)
async def get_settings(
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> TenantSettingsOut:
    tenant = await session.get(Tenant, user.tenant_id)
    return _settings_out(dict((tenant.settings or {}) if tenant else {}), cfg)


@router.patch("", response_model=TenantSettingsOut)
async def update_settings(
    body: TenantSettingsUpdate,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> TenantSettingsOut:
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise ApiError(404, "not found", f"no tenant {user.tenant_id}")
    settings = dict(tenant.settings or {})
    settings[_EMAIL_TOGGLE_KEY] = body.email_on_run_complete
    if body.notify_email is None:
        settings.pop(_EMAIL_TO_KEY, None)
    else:
        settings[_EMAIL_TO_KEY] = body.notify_email
    tenant.settings = settings
    await session.flush()
    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="settings.update",
        subject_type="tenant",
        subject_id=user.tenant_id,
        payload={
            "email_on_run_complete": body.email_on_run_complete,
            "notify_email": body.notify_email,
            "dry_run": dry_run,
        },
        created_at=datetime.now(UTC),
    )
    result = _settings_out(settings, cfg)
    await finish(session, dry_run=dry_run)
    return result


async def _recipients(
    session: AsyncSession, tenant_id: str, settings: dict[str, object]
) -> list[str]:
    to = settings.get(_EMAIL_TO_KEY)
    if to:
        return [str(to)]
    rows = (
        await session.scalars(
            select(User.email).where(
                User.tenant_id == tenant_id,
                User.role.in_(_EMAIL_ROLES),
                User.status == "active",
            )
        )
    ).all()
    return [r for r in rows if r]


@router.post("/send-run-summary", response_model=SendSummaryOut)
async def send_run_summary(
    run_id: str | None = Query(None),
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> SendSummaryOut:
    """Email the run-complete summary for ``run_id`` (default: the newest
    complete run) to the configured address, right now.

    Same body as the automatic email, built from what the run persisted: the
    exceptions table, the cash bridge and the eval row. ``dry_run`` builds the
    headline and resolves recipients without sending.
    """
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise ApiError(404, "not found", f"no tenant {user.tenant_id}")
    settings = dict(tenant.settings or {})

    if run_id is None:
        newest = await session.scalar(
            select(Run)
            .where(Run.status == "complete")
            .order_by(Run.started_at.desc(), Run.run_id.desc())
            .limit(1)
        )
        if newest is None:
            raise ApiError(404, "not found", "this tenant has no completed run yet")
        run_id = newest.run_id
    run = await session.get(Run, run_id)
    if run is None:
        raise ApiError(404, "not found", f"no run {run_id}")

    exceptions = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.run_id == run_id))
    ).all()
    event_run_id = await event_source_run_id(session, run_id)
    event_ids = (
        await session.scalars(
            select(TransactionEventRow.event_id).where(TransactionEventRow.run_id == event_run_id)
        )
    ).all()
    event_count = len(event_ids)
    bridge = await compute_bridge(session, run_id)
    eval_row = await session.get(EvalResult, run_id)
    false_auto = eval_row.false_auto_resolutions if eval_row is not None else 0

    needing_attention = sum(1 for e in exceptions if e.tier != "auto")
    settled_automatically = max(event_count - len(exceptions), 0)
    deadlines = [e.deadline for e in exceptions if e.deadline is not None]
    headline = (
        f"{needing_attention} item{'s' if needing_attention != 1 else ''} need your decision, "
        f"{fmt_inr(bridge.unexplained_paise)} unexplained"
    )
    finished = run.finished_at or run.started_at
    if deadlines:
        days = (min(deadlines) - finished.date()).days
        headline += f", first deadline in {days} day{'s' if days != 1 else ''}"

    top = sorted(exceptions, key=lambda e: e.amount_paise, reverse=True)[:5]
    top_exceptions: list[dict[str, object]] = [
        {"category": e.category, "amount_paise": e.amount_paise, "deadline": e.deadline}
        for e in top
    ]

    recipients = await _recipients(session, user.tenant_id, settings)
    reason: str | None = None
    if not cfg.resend_api_key:
        reason = "no RESEND_API_KEY configured; nothing was sent"
    elif not recipients:
        reason = "no recipient: set an address in Settings"
    sent = reason is None and not dry_run

    if sent:
        asyncio.create_task(
            notify_run_complete(
                cfg,
                run_id=run_id,
                headline=headline,
                records_processed=event_count,
                settled_automatically=settled_automatically,
                needing_attention=needing_attention,
                false_auto_resolutions=false_auto,
                top_exceptions=top_exceptions,
                app_url=cfg.frontend_origin or "http://localhost:3000",
                to=recipients,
            )
        )
        settings[_EMAIL_LAST_SENT_KEY] = datetime.now(UTC).isoformat()
        tenant.settings = settings
        await session.flush()
        await append_audit(
            session,
            tenant_id=user.tenant_id,
            actor=f"user:{user.user_id}",
            action="settings.send_run_summary",
            subject_type="run",
            subject_id=run_id,
            payload={"recipients": recipients, "headline": headline},
            created_at=datetime.now(UTC),
        )

    await finish(session, dry_run=dry_run)
    return SendSummaryOut(
        run_id=run_id, recipients=recipients, headline=headline, sent=sent, reason=reason
    )
