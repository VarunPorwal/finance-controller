"""Shared harness for the integration suite — one loop, one connection, one pool.

The suite talks to Neon in Singapore. A connection costs ~0.93s to open and a
round trip ~0.19s, so what dominated the runtime was never query time: it was
34 tests each opening their own admin connection, each clearing the SQLAlchemy
engine cache and rebuilding a pool, and each issuing a dozen separate DELETEs
to tidy up. Setup was most of a seven-minute gate.

Three things fix that, and they are all in this file:

* **One event loop for the whole session.** SQLAlchemy's async engine binds its
  pool to the loop it first ran on, which is why every test used to clear
  ``get_engine``'s cache — a per-test ``asyncio.run`` left the previous pool
  holding connections against a closed loop. Keeping one loop open lets the
  pool be built once and reused.
* **One admin connection**, reconnecting on demand, rather than one per test.
* **Batched cleanup.** Purging a tenant was 6–8 statements, run twice per test.
  It is one round trip now.

What this deliberately does *not* do is wrap each test in a transaction that
rolls back. That is the usual trick and it cannot work here: most of these
tests drive the real FastAPI app, which has its own connection pool, and an
uncommitted row on the admin connection is invisible to it. Isolation comes
from per-test tenant ids and an explicit purge instead — slower than a rollback
by one round trip, and actually correct.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any

import pytest

from fc.config import asyncpg_url, load_config

asyncpg = pytest.importorskip("asyncpg", reason="asyncpg is not installed")

#: Set by ``dev.ps1 check``. When on, a database that cannot be reached is a
#: **failure**, not a skip — see :func:`require_db`.
REQUIRE_DB_ENV = "FC_REQUIRE_DB"

#: Every tenant-scoped table, ordered so foreign keys are satisfied.
_PURGE_ORDER = (
    "llm_calls",
    "audit_events",
    "eval_results",
    "clusters",
    "exceptions",
    "matches",
    "transaction_events",
    "rules",
    "runs",
    "counterparty_aliases",
    "users",
    "tenants",
)

_loop: asyncio.AbstractEventLoop | None = None
_conn: Any = None


def owner_url() -> str:
    cfg = load_config()
    url = cfg.database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        require_db("no DATABASE_URL configured")
    return asyncpg_url(url).replace("postgresql+asyncpg://", "postgresql://")


def require_db(reason: str) -> Any:
    """Skip, or fail, depending on whether this run is allowed to skip.

    A skipped test is an unrun proof that pytest reports as success. Earlier in
    this build 21–29 integration tests skipped silently on a green run, which
    meant the RLS and read-only-transaction proofs — the two things the
    text-to-SQL safety claim rests on — had never actually executed. ``check``
    sets ``FC_REQUIRE_DB=1`` so that cannot happen again; a developer running
    ``pytest`` on a plane still gets a skip.
    """
    if os.environ.get(REQUIRE_DB_ENV) == "1":
        pytest.fail(f"database required but unavailable: {reason}", pytrace=False)
    pytest.skip(f"database unavailable: {reason}")


def loop() -> asyncio.AbstractEventLoop:
    """The one loop the whole session runs on."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def run(body: Callable[[], Awaitable[Any]]) -> Any:
    """``asyncio.run``, but on the shared loop so pools survive between tests."""
    return loop().run_until_complete(body())


async def admin() -> Any:
    """The shared owner connection, reconnected if Neon dropped it.

    The free tier closes idle connections, and these tests interleave short
    bursts of admin SQL with long stretches of HTTP work on a different pool —
    so the admin side sits idle for minutes at a time. Reconnecting on demand
    puts that flake where it belongs: nowhere.
    """
    global _conn
    if _conn is None or _conn.is_closed():
        try:
            _conn = await asyncio.wait_for(asyncpg.connect(owner_url()), timeout=20)
        except (TimeoutError, OSError, asyncpg.PostgresError) as exc:
            require_db(str(exc))
    return _conn


async def purge(conn: Any, tenants: Iterable[str]) -> None:
    """Remove every trace of these tenants in a single round trip.

    Twelve DELETEs at 0.19s each, twice per test, was most of the suite's
    runtime. The tenant ids are module constants in the test files, never user
    input, so inlining them is safe and buys eleven round trips per call.
    """
    names = [t for t in tenants if t]
    if not names:
        return
    literals = ", ".join("'" + t.replace("'", "''") + "'" for t in names)
    statements = ";".join(
        f"DELETE FROM {table} WHERE tenant_id IN ({literals})" for table in _PURGE_ORDER
    )
    await conn.execute(statements)


class Admin:
    """Thin wrapper so test bodies keep using ``conn.fetchval(...)`` unchanged."""

    async def execute(self, *args: Any) -> Any:
        return await (await admin()).execute(*args)

    async def fetch(self, *args: Any) -> Any:
        return await (await admin()).fetch(*args)

    async def fetchrow(self, *args: Any) -> Any:
        return await (await admin()).fetchrow(*args)

    async def fetchval(self, *args: Any) -> Any:
        return await (await admin()).fetchval(*args)


ADMIN = Admin()


@pytest.fixture(scope="session", autouse=True)
def _shared_loop() -> Any:
    """Keep one loop open for the session and tear the shared state down once."""
    yield loop()
    if _conn is not None and not _conn.is_closed():
        loop().run_until_complete(_conn.close())
    # The app's engine holds pooled connections against this loop; dispose
    # before closing it or asyncpg logs "Event loop is closed" on exit.
    try:
        from api.deps import get_engine

        if get_engine.cache_info().currsize:
            loop().run_until_complete(get_engine().dispose())
    except Exception:  # noqa: BLE001 - teardown must not fail a green run
        pass
    if _loop is not None and not _loop.is_closed():
        _loop.close()


def seeded(tenants: Sequence[str], seed: Callable[[Any], Awaitable[None]]) -> Any:
    """Purge, seed, hand back the admin connection. Used by every test module."""

    async def go() -> Any:
        conn = ADMIN
        await purge(conn, tenants)
        await seed(conn)
        return conn

    return go
