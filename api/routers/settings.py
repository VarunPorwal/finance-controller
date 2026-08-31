"""Tenant-level settings stored in ``tenants.settings`` (JSONB) — no schema
change, the column already exists and already held ``default_run_id`` before
that was retired (``api/routers/runs.py``).

Currently one setting: the "Email me when a run finishes" toggle on the
Reconcile screen. Off by default — a run must not start emailing a tenant's
finance team until someone opts in.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit_log import append_audit
from api.deps import AuthenticatedUser, current_user, db_session, finish
from api.errors import ApiError
from db.models import Tenant

router = APIRouter(prefix="/settings", tags=["settings"])

_EMAIL_TOGGLE_KEY = "email_on_run_complete"
_EMAIL_LAST_SENT_KEY = "email_last_sent_at"


class TenantSettingsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_on_run_complete: bool
    email_last_sent_at: datetime | None = None


class TenantSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_on_run_complete: bool


def _settings_out(settings: dict[str, object]) -> TenantSettingsOut:
    sent = settings.get(_EMAIL_LAST_SENT_KEY)
    return TenantSettingsOut(
        email_on_run_complete=bool(settings.get(_EMAIL_TOGGLE_KEY, False)),
        email_last_sent_at=datetime.fromisoformat(str(sent)) if sent else None,
    )


@router.get("", response_model=TenantSettingsOut)
async def get_settings(
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> TenantSettingsOut:
    tenant = await session.get(Tenant, user.tenant_id)
    return _settings_out(dict((tenant.settings or {}) if tenant else {}))


@router.patch("", response_model=TenantSettingsOut)
async def update_settings(
    body: TenantSettingsUpdate,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> TenantSettingsOut:
    tenant = await session.get(Tenant, user.tenant_id)
    if tenant is None:
        raise ApiError(404, "not found", f"no tenant {user.tenant_id}")
    settings = dict(tenant.settings or {})
    settings[_EMAIL_TOGGLE_KEY] = body.email_on_run_complete
    tenant.settings = settings
    await session.flush()
    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="settings.update",
        subject_type="tenant",
        subject_id=user.tenant_id,
        payload={"email_on_run_complete": body.email_on_run_complete, "dry_run": dry_run},
        created_at=datetime.now(UTC),
    )
    result = _settings_out(settings)
    await finish(session, dry_run=dry_run)
    return result
