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

import logging
import sys
import threading
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
from fc.llm.client import LLMClient  # noqa: E402
from fc.llm.schemas import LLMCallRecord  # noqa: E402
from fc.llm.sql_guard import STATEMENT_TIMEOUT_MS  # noqa: E402

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


# --- LLM wiring (PRD §7) -----------------------------------------------------


_LOG = logging.getLogger(__name__)


class LLMCallBuffer:
    """Holds the records the router emitted until a session can write them.

    The router cannot write ``llm_calls`` itself — ``tests/unit/test_architecture.py``
    forbids importing ``sqlalchemy`` anywhere under ``engine/src``, and that is
    the right constraint: the engine has no business knowing a database exists.
    So it emits :class:`~fc.llm.schemas.LLMCallRecord` values to this sink and a
    request handler drains them into its own transaction afterwards.

    One buffer serves the whole process, so concurrent requests can drain each
    other's records. That is harmless — every record carries its own tenant and
    run id, so nothing is mis-attributed; only the transaction a row lands in is
    shared, and a row is never lost because a drain removes what it returns.
    """

    def __init__(self) -> None:
        self._records: list[LLMCallRecord] = []
        self._lock = threading.Lock()

    def sink(self, record: LLMCallRecord) -> None:
        with self._lock:
            self._records.append(record)

    def drain(self) -> list[LLMCallRecord]:
        with self._lock:
            drained, self._records = self._records, []
        return drained

    def pending(self) -> bool:
        with self._lock:
            return bool(self._records)


@lru_cache(maxsize=1)
def get_llm_buffer() -> LLMCallBuffer:
    return LLMCallBuffer()


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    """One router per process. Health counters and the disk cache live on it,
    so a fresh client per request would defeat both."""
    return LLMClient(get_config(), sink=get_llm_buffer().sink)


# --- the text-to-SQL execution path (PRD §7.8) -------------------------------


@lru_cache(maxsize=1)
def readonly_url() -> str | None:
    """``DATABASE_URL_READONLY``, but only when it is genuinely a *different* role.

    On Neon the connection string that variable usually holds points at
    ``neondb_owner``, which carries ``rolbypassrls`` through ``neon_superuser``.
    Running generated SQL there would trade RLS away to gain a read-only
    guarantee the transaction below already provides — one real layer where the
    documentation claims three. So it is used only when it is set and differs
    from ``DATABASE_URL``, and it is reported in ``/agent/health`` either way so
    the active combination is visible rather than assumed.
    """
    cfg = get_config()
    url = cfg.database_url_readonly
    if not url or url == cfg.database_url:
        return None
    return url


@lru_cache(maxsize=1)
def get_readonly_sessionmaker() -> async_sessionmaker[AsyncSession] | None:
    url = readonly_url()
    if url is None:
        return None
    engine = create_async_engine(asyncpg_url(url), pool_size=2, max_overflow=2, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def readonly_session(tenant_id: str, role: str) -> AsyncIterator[AsyncSession]:
    """A transaction that cannot write, cannot run long, and cannot see another
    tenant — the three layers §7.8 asks for, in the order they must be applied.

    ``SET TRANSACTION READ ONLY`` has to be the first statement in the
    transaction (Postgres rejects it once a query has run), which is why this
    opens its own session rather than reusing the request's: ``scoped_session``
    has already issued two ``set_config`` calls by the time a handler sees it.
    """
    maker = get_readonly_sessionmaker() or get_sessionmaker()
    async with maker() as session:
        await session.begin()
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"))
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id}
        )
        await session.execute(text("SELECT set_config('app.role', :r, true)"), {"r": role})
        try:
            yield session
        finally:
            await session.rollback()


def sql_isolation_layers() -> list[str]:
    """What is actually standing between a generated query and the data."""
    layers = ["sqlglot_guard", "read_only_transaction", "statement_timeout", "rls"]
    if readonly_url() is not None:
        layers.append("readonly_role")
    return layers


async def persist_llm_calls(
    session: AsyncSession, buffer: LLMCallBuffer, *, tenant_id: str
) -> None:
    """Drain the router's records into ``llm_calls`` (PRD §7.11).

    Runs inside the caller's transaction, so the rows commit or roll back with
    the work they describe — a dry run leaves no trace of its own calls, which
    is right.

    It does **not** swallow failures, and the reason is worth stating: a failed
    INSERT poisons the SQLAlchemy transaction, so "catch and carry on" would
    turn one clear error into a confusing one several statements later. There
    is no foreign key on this table and nothing to violate, so a failure here
    means schema drift or an RLS misconfiguration — both of which should be
    loud. The router's own sink is the layer that never raises (it catches
    around this being called), so an observability problem still cannot fail an
    LLM call; it can only fail the request that was already writing to the
    database.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from db.models import LLMCall

    # Upsert on call_id, not insert. A purpose in HAS_DOWNSTREAM_CHECK is
    # logged twice for one call — once by ``call`` and once by
    # ``confirm``/``reject`` when the deterministic check rules — and the two
    # records now share an id, so the second updates the verdict on the first
    # row. Inserting both is what made twenty-two sql_narrate rows out of
    # eleven calls, half of them with an empty prompt_hash, and doubled the
    # apparent cost of every ask.
    records = list(buffer.drain())
    if not records:
        return
    # A single multi-row INSERT ... ON CONFLICT cannot affect the same row
    # twice, so the call/confirm pair sharing a call_id (see above) has to be
    # collapsed here rather than left for Postgres to upsert twice: keep the
    # first record's full row (it carries prompt_hash and token counts) and
    # let a later record for the same call_id only override verified/outcome,
    # matching what the old row-by-row upsert did.
    merged: dict[str, dict] = {}
    for record in records:
        values = dict(
            call_id=record.call_id,
            tenant_id=record.tenant_id or tenant_id,
            run_id=record.run_id,
            purpose=record.purpose,
            provider=record.provider,
            model=record.model,
            tier=record.tier,
            ladder_position=record.ladder_position,
            prompt_hash=record.prompt_hash,
            cached=record.cached,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            thinking_tokens=record.thinking_tokens,
            latency_ms=record.latency_ms,
            outcome=record.outcome,
            verified=record.verified,
        )
        existing = merged.get(record.call_id)
        if existing is None:
            merged[record.call_id] = values
        else:
            existing["verified"] = values["verified"]
            existing["outcome"] = values["outcome"]
    stmt = pg_insert(LLMCall).values(list(merged.values()))
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[LLMCall.call_id],
            # Only what the downstream check can change. prompt_hash and the
            # token counts stay as the original call recorded them — the
            # confirm record carries neither.
            set_={"verified": stmt.excluded.verified, "outcome": stmt.excluded.outcome},
        )
    )
    await session.flush()


async def persist_llm_calls_detached(buffer: LLMCallBuffer, *, tenant_id: str, role: str) -> None:
    """Record LLM calls in their own transaction, for a request that is failing.

    :func:`persist_llm_calls` deliberately writes inside the caller's
    transaction, so a dry run leaves no trace of its own calls. That is right
    for a dry run and wrong for a rejection: a PDF extraction that fails its
    balance check still reached the provider and still spent quota, but the 422
    rolls the request back and takes the cost record with it. No pdf_extract row
    has ever been written for that reason.

    Opening a separate session keeps the cost even though the work is discarded.
    Failures are swallowed — losing an observability row must not turn a
    well-formed 422 into a 500.
    """
    if not buffer.pending():
        return
    try:
        async with scoped_session(tenant_id, role) as session:
            await persist_llm_calls(session, buffer, tenant_id=tenant_id)
            await session.commit()
    except Exception:  # noqa: BLE001
        _LOG.exception("could not record llm_calls out of band; the calls still happened")


async def rescope(session: AsyncSession, user: AuthenticatedUser) -> None:
    """Re-apply the tenant scope after somebody else ended the transaction.

    ``set_config(..., is_local=true)`` is scoped to a *transaction*, which is
    what makes it safe on a pooled connection — and what makes it disappear the
    moment anything commits or rolls back. ``/agent/execute`` calls the same
    endpoint functions a click does, and each of those calls :func:`finish`,
    so by the time the agent handler appends its own audit event the scope its
    session started with is gone and RLS refuses the insert.

    Calling this after dispatching is the fix, and it is preferable to the
    alternatives: not letting the inner endpoints commit would mean not reusing
    them, and reusing them is the property that makes "an instruction cannot do
    what a click cannot" true rather than asserted.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": user.tenant_id}
    )
    await session.execute(text("SELECT set_config('app.role', :r, true)"), {"r": user.role})
