"""FastAPI dependencies — PRD §4.4, §5.2.

The application connects as ``fc_app_user`` (``DATABASE_URL_APP``), a non-owner
role with no ``BYPASSRLS``. That is what makes the row-level security policies
bind: the migration owner (``DATABASE_URL``) is superuser-equivalent on Neon and
bypasses them, which is correct for migrations and wrong for request handling.

``SET LOCAL`` scopes the tenant to the transaction, so a connection returned to
the pool cannot carry another tenant's context into the next request — ``SET``
(without ``LOCAL``) would persist for the lifetime of the pooled connection and
leak into whichever request picks it up next, making tenant isolation
decorative. ``db_session`` never auto-commits: every mutating route decides
for itself, via :func:`finish`, whether the transaction it built commits or
rolls back — that decision *is* the ``dry_run`` contract (PRD §5.1 — "computes
and returns the full effect without persisting anything"). A route that
forgets to call ``finish`` still cannot leave a dangling transaction on a
pooled connection: the ``finally`` block below rolls back anything still open.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

import jwt
from fastapi import Depends, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "engine" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "engine" / "src"))

from api.errors import ApiError  # noqa: E402
from fc.config import Config, asyncpg_url, load_config  # noqa: E402

__all__ = [
    "AuthenticatedUser",
    "current_user",
    "db_session",
    "finish",
    "get_config",
    "get_engine",
    "get_sessionmaker",
    "scoped_session",
]

_JWT_ALGORITHM = "HS256"


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config(env_file=str(ROOT / ".env"))


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    config = get_config()
    url = config.database_url_app or config.database_url
    if not url:
        raise RuntimeError("neither DATABASE_URL_APP nor DATABASE_URL is set")
    return create_async_engine(
        asyncpg_url(url),
        pool_size=config.db_pool_size,
        max_overflow=config.db_max_overflow,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


class AuthenticatedUser(BaseModel):
    """Resolved from the bearer token — PRD §5.2. Never constructed from
    anything a client sends directly; only ``current_user`` builds one."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: str
    tenant_id: str
    role: str
    email: str
    display_name: str


#: The buildathon demo identity for PRD §5.1's "static demo token": a fixed
#: bearer value matching `Config.demo_token`, resolved without a database
#: round trip so the demo works even against a cold connection pool.
_DEMO_USER_ID = "u_demo"
_DEMO_ROLE = "owner"
_DEMO_DISPLAY_NAME = "Demo Owner"


async def current_user(authorization: str | None = Header(default=None)) -> AuthenticatedUser:
    """Bearer auth (PRD §5.2): either the static demo token or an HS256 JWT.

    A JWT's claims name the tenant and role directly — this dependency never
    queries the database, so ``db_session`` (which needs a resolved tenant and
    role to run ``SET LOCAL``) has no ordering dependency on a prior query.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "unauthorized", "missing Authorization: Bearer <token> header")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise ApiError(401, "unauthorized", "empty bearer token")

    cfg = get_config()
    if cfg.demo_token and token == cfg.demo_token:
        return AuthenticatedUser(
            user_id=_DEMO_USER_ID,
            tenant_id=cfg.tenant_id,
            role=_DEMO_ROLE,
            email="demo@aarambhlabs.dev",
            display_name=_DEMO_DISPLAY_NAME,
        )

    if not cfg.jwt_secret:
        raise ApiError(
            401, "unauthorized", "no JWT secret configured and token is not the demo token"
        )
    try:
        claims = jwt.decode(token, cfg.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise ApiError(401, "unauthorized", f"invalid token: {exc}") from exc

    try:
        return AuthenticatedUser(
            user_id=claims["sub"],
            tenant_id=claims["tenant_id"],
            role=claims["role"],
            email=claims.get("email", ""),
            display_name=claims.get("display_name", ""),
        )
    except KeyError as exc:
        raise ApiError(401, "unauthorized", f"token is missing claim {exc}") from exc


@asynccontextmanager
async def scoped_session(tenant_id: str, role: str) -> AsyncIterator[AsyncSession]:
    """A session scoped to one tenant and one role for one transaction.

    ``SET LOCAL app.tenant_id = :t`` looks like the obvious way to write this
    and does not work: Postgres's ``SET`` statement takes its value as a
    syntactic literal, not a bind parameter, so asyncpg's prepared-statement
    protocol rejects it with a syntax error at ``$1`` — a failure that only
    shows up the moment a real query runs, which is exactly why the original
    stub (identical code) went untested until the dry_run/RLS integration
    tests actually exercised it. ``set_config(name, value, is_local)`` is the
    parameterisable equivalent — ``is_local=true`` gives the same
    transaction-scoped revert ``SET LOCAL`` would, but as an ordinary
    function call that accepts a bind parameter like anything else.

    Shared by :func:`db_session` (per-request, tenant from the bearer token)
    and ``api.scheduler`` (per-tenant loop over every active tenant — a
    background job has no single request to scope to, so it opens one of
    these per tenant per run instead).
    """
    async with get_sessionmaker()() as session:
        await session.begin()
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id}
        )
        await session.execute(text("SELECT set_config('app.role', :r, true)"), {"r": role})
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.rollback()


async def db_session(
    user: AuthenticatedUser = Depends(current_user),
) -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session. ``db_session`` never auto-commits:
    every mutating route decides for itself, via :func:`finish`, whether the
    transaction it built commits or rolls back — that decision *is* the
    ``dry_run`` contract (PRD §5.1). A route that forgets to call ``finish``
    still cannot leave a dangling transaction on a pooled connection:
    :func:`scoped_session`'s own ``finally`` rolls back anything still open.
    """
    async with scoped_session(user.tenant_id, user.role) as session:
        yield session


async def finish(session: AsyncSession, *, dry_run: bool) -> None:
    """The entire ``dry_run`` contract in one call: commit for real, or throw
    the transaction away. Every mutating route calls this exactly once, after
    building the complete effect (including derived rows), and returns its
    response built from data already computed in memory — never re-reads
    after a rollback, since there would be nothing left to read."""
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
