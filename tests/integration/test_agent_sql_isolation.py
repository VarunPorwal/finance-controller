"""The two layers under the sqlglot guard — PRD §7.8.

The guard is proven without a database in ``tests/unit/test_llm_sql_guard.py``.
This file proves the other two, because "three independent layers" is only a
claim until each one is shown to hold **on its own**:

1. a mutating statement that somehow got past the guard is refused by Postgres,
   because the transaction is read-only
2. a query for another tenant's data returns nothing, because it runs as
   ``fc_app_user`` under RLS

The first test deliberately bypasses ``guard()`` and feeds raw SQL to the
executor. That is the point: if the only thing standing between a generated
DELETE and the data is the parser, then there is one layer, not three.

Mirrors the connection/seed/skip pattern in ``test_api_dry_run.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy import text

from fc.config import load_config
from fc.llm.sql_guard import guard
from tests.integration.conftest import ADMIN, purge, run

asyncpg = pytest.importorskip("asyncpg", reason="asyncpg is not installed")

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_TENANT_A = "t_agent_sql_a"
_TENANT_B = "t_agent_sql_b"
_USER_A = "u_agent_sql_a"
_RUN_A = "run_agent_sql_a"
_RUN_B = "run_agent_sql_b"
_TENANTS = (_TENANT_A, _TENANT_B)


def _run_async[T](body: Callable[[Any], Awaitable[T]]) -> T:
    """One shared loop, one shared admin connection — see conftest.

    The read-only sessionmaker cache is still cleared, because these tests
    change what ``DATABASE_URL_READONLY`` resolves to and a cached maker would
    outlive that; the engine cache is not, since one loop for the session keeps
    its pool valid.
    """
    from api.deps import get_readonly_sessionmaker

    get_readonly_sessionmaker.cache_clear()

    async def main() -> T:
        conn = ADMIN
        await _seed(conn)
        try:
            return await body(conn)
        finally:
            await purge(conn, _TENANTS)

    return cast("T", run(main))


async def _seed(conn: Any) -> None:
    await purge(conn, _TENANTS)
    for tenant, run_id in ((_TENANT_A, _RUN_A), (_TENANT_B, _RUN_B)):
        await conn.execute(
            "INSERT INTO tenants (tenant_id, name, status) VALUES ($1, $2, 'active')",
            tenant,
            f"agent sql test {tenant}",
        )
        await conn.execute(
            "INSERT INTO users (user_id, tenant_id, email, display_name, role, status) "
            "VALUES ($1, $2, $3, $4, 'owner', 'active')",
            f"u_{tenant}",
            tenant,
            f"u_{tenant}@example.invalid",
            f"u_{tenant}",
        )
        await conn.execute(
            "INSERT INTO runs (run_id, tenant_id, triggered_by, status, ruleset_hash, "
            "input_hashes, config) "
            "VALUES ($1, $2, $3, 'complete', 'deadbeef', '{}'::jsonb, '{}'::jsonb)",
            run_id,
            tenant,
            f"u_{tenant}",
        )
        await conn.execute(
            "INSERT INTO exceptions (exception_id, run_id, tenant_id, event_ids, category, "
            "amount_paise, residual_paise, confidence, tier, priority_score, "
            "recommended_action, status, signature, created_at) "
            "VALUES ($1, $2, $3, ARRAY[]::text[], 'amount_variance', 100000, 100000, 0.9, "
            "'monitor', 0.5, 'review', 'open', 'sig', $4)",
            f"exc_{tenant}",
            run_id,
            tenant,
            _AT,
        )


async def _cleanup(conn: Any) -> None:
    await purge(conn, _TENANTS)


def test_a_mutating_statement_that_bypassed_the_guard_is_refused_by_postgres() -> None:
    """Layer 2, on its own.

    The SQL below never goes near ``guard()`` — it is handed straight to the
    executor, which is exactly the situation the read-only transaction exists
    for. If this passes only because the parser would have caught it first,
    the "three independent layers" claim is one layer wearing three hats.
    """

    async def body(conn: Any) -> None:
        from api.deps import readonly_session

        before = await conn.fetchval(
            "SELECT count(*) FROM exceptions WHERE tenant_id = $1", _TENANT_A
        )
        assert before == 1

        for statement in (
            f"DELETE FROM exceptions WHERE tenant_id = '{_TENANT_A}'",
            f"UPDATE exceptions SET status = 'resolved' WHERE tenant_id = '{_TENANT_A}'",
            "CREATE TABLE agent_sql_should_not_exist (id text)",
        ):
            async with readonly_session(_TENANT_A, "owner") as session:
                with pytest.raises(Exception) as caught:  # noqa: B017 - driver-specific
                    await session.execute(text(statement))
                assert "read-only" in str(caught.value).lower(), (
                    f"Postgres allowed {statement!r} in what should be a read-only transaction"
                )

        after = await conn.fetchval(
            "SELECT count(*) FROM exceptions WHERE tenant_id = $1", _TENANT_A
        )
        assert after == before, "a write landed despite the read-only transaction"

    _run_async(body)


def test_a_query_for_another_tenants_run_returns_nothing_under_rls() -> None:
    """Layer 3, in this path specifically rather than inferred from the routers.

    The query is scoped to tenant A's session but asks for tenant B's run by
    name. RLS makes it return zero rows rather than another tenant's data —
    the IDOR control in §10.2, proven here rather than assumed to carry over.
    """

    async def body(conn: Any) -> None:
        from api.deps import readonly_session

        # The row genuinely exists — the owner connection can see it.
        assert (
            await conn.fetchval("SELECT count(*) FROM exceptions WHERE tenant_id = $1", _TENANT_B)
            == 1
        )

        async with readonly_session(_TENANT_A, "owner") as session:
            own = await session.execute(
                text("SELECT exception_id FROM exceptions WHERE run_id = :r"), {"r": _RUN_A}
            )
            assert len(own.fetchall()) == 1, "RLS hid the session's own tenant"

            other = await session.execute(
                text("SELECT exception_id FROM exceptions WHERE run_id = :r"), {"r": _RUN_B}
            )
            assert other.fetchall() == [], "a cross-tenant query returned rows"

    _run_async(body)


def test_the_guard_and_the_transaction_are_each_sufficient_on_their_own() -> None:
    """Belt and braces, stated as a test rather than as a comment.

    The guard refuses the statement without a database; the database refuses it
    without the guard. Neither is load-bearing alone, which is the property that
    makes the layering worth having.
    """
    from fc.llm.sql_guard import SqlRejected

    hostile = f"DELETE FROM exceptions WHERE tenant_id = '{_TENANT_A}'"
    with pytest.raises(SqlRejected):
        guard(hostile, tenant_id=_TENANT_A)


def test_a_guarded_query_still_runs_and_is_scoped_to_the_session_tenant() -> None:
    """The whole path end to end: generated SQL, guarded, executed read-only,
    under RLS — and it returns the right answer for the right tenant."""

    async def body(conn: Any) -> None:
        from api.deps import readonly_session

        safe = guard("SELECT COUNT(*) AS n FROM exceptions", tenant_id=_TENANT_A)
        assert f"tenant_id = '{_TENANT_A}'" in safe
        async with readonly_session(_TENANT_A, "owner") as session:
            assert (await session.execute(text(safe))).scalar_one() == 1

        # The same guarded query, run in tenant B's session, sees only B's row —
        # the injected predicate and RLS agree rather than one masking the other.
        safe_b = guard("SELECT COUNT(*) AS n FROM exceptions", tenant_id=_TENANT_B)
        async with readonly_session(_TENANT_B, "owner") as session:
            assert (await session.execute(text(safe_b))).scalar_one() == 1

        # And a predicate for the *wrong* tenant returns nothing even inside a
        # session scoped to a real one.
        async with readonly_session(_TENANT_A, "owner") as session:
            assert (await session.execute(text(safe_b))).scalar_one() == 0

    _run_async(body)


def test_the_statement_timeout_is_set_on_the_transaction() -> None:
    """§7.8's third constraint. A generated query that would run for a minute
    is a denial of service on a free-tier database."""

    async def body(conn: Any) -> None:
        from api.deps import readonly_session

        async with readonly_session(_TENANT_A, "owner") as session:
            timeout = (await session.execute(text("SHOW statement_timeout"))).scalar_one()
        assert timeout in ("3s", "3000ms"), f"statement_timeout was {timeout!r}"

    _run_async(body)


def test_sql_isolation_reports_which_layers_are_actually_active() -> None:
    """``/agent/health`` says what is standing between a query and the data, so
    the answer is visible rather than assumed. The read-only *role* is optional
    hardening and appears only when one is genuinely configured."""
    from api.deps import readonly_url, sql_isolation_layers

    layers = sql_isolation_layers()
    assert layers[:4] == ["sqlglot_guard", "read_only_transaction", "statement_timeout", "rls"]
    assert ("readonly_role" in layers) == (readonly_url() is not None)


def test_a_readonly_url_equal_to_the_owner_url_is_not_treated_as_a_layer() -> None:
    """On Neon the role that variable usually names carries ``rolbypassrls``.
    Using it would trade RLS away to gain a read-only guarantee the transaction
    already provides — one real layer where the docs claim two."""
    from api.deps import readonly_url

    cfg = load_config()
    if cfg.database_url_readonly and cfg.database_url_readonly != cfg.database_url:
        pytest.skip("a genuinely distinct read-only role is configured")
    assert readonly_url() is None
