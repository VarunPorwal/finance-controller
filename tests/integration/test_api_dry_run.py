"""dry_run persists nothing, and SET LOCAL scopes RLS to one request — the
two guarantees Prompt 8's API layer rests on, proven against the real
Postgres and the real FastAPI app (ASGI transport, no live server needed).

Mirrors ``test_rules_immutability.py``'s connection/seed/skip pattern: an
owner connection seeds and inspects raw state (bypassing RLS on purpose, so
row counts reflect ground truth rather than what one tenant's session can
see); the HTTP calls go through the real ``fc_app_user`` / ``SET LOCAL``
path via ``api.main.app``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any, cast

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from fc.config import load_config
from tests.integration.conftest import ADMIN, purge, run

asyncpg = pytest.importorskip("asyncpg", reason="asyncpg is not installed")

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_TENANT_A = "t_api_dry_run_a"
_TENANT_B = "t_api_dry_run_b"
_USER_A = "u_api_dry_run_a"
_USER_B = "u_api_dry_run_b"
_RUN_A = "run_api_dry_run_a"
_JWT_ALGORITHM = "HS256"
_TENANTS = (_TENANT_A, _TENANT_B)


def _run_async[T](body: Callable[[Any], Awaitable[T]]) -> T:
    """One shared loop and one shared admin connection — see conftest.

    Every test used to clear ``get_engine``'s cache because a per-test
    ``asyncio.run`` left the previous pool bound to a closed loop. With one loop
    for the session that is no longer true, and not clearing it is worth about a
    second per test in connection setup.
    """

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
    for tenant, user in ((_TENANT_A, _USER_A), (_TENANT_B, _USER_B)):
        await conn.execute(
            "INSERT INTO tenants (tenant_id, name, status) VALUES ($1, $2, 'active')",
            tenant,
            f"dry-run test {tenant}",
        )
        await conn.execute(
            "INSERT INTO users (user_id, tenant_id, email, display_name, role, status) "
            "VALUES ($1, $2, $3, $4, 'owner', 'active')",
            user,
            tenant,
            f"{user}@example.invalid",
            user,
        )
    await conn.execute(
        "INSERT INTO runs (run_id, tenant_id, triggered_by, status, ruleset_hash, "
        "input_hashes, config) "
        "VALUES ($1, $2, $3, 'complete', 'deadbeef', '{}'::jsonb, '{}'::jsonb)",
        _RUN_A,
        _TENANT_A,
        _USER_A,
    )


async def _cleanup(conn: Any) -> None:
    await purge(conn, _TENANTS)


async def _insert_event(
    conn: Any, *, event_id: str, tenant: str, run_id: str, amount_paise: int
) -> None:
    await conn.execute(
        "INSERT INTO transaction_events (event_id, run_id, tenant_id, source, source_row_id, "
        "amount_paise, direction, txn_date, raw) "
        "VALUES ($1, $2, $3, 'bank', $1, $4, 'credit', $5, '{}'::jsonb)",
        event_id,
        run_id,
        tenant,
        amount_paise,
        date(2026, 8, 20),
    )


async def _insert_exception(
    conn: Any,
    *,
    exception_id: str,
    tenant: str,
    run_id: str,
    event_ids: list[str],
    residual_paise: int,
) -> None:
    await conn.execute(
        "INSERT INTO exceptions (exception_id, run_id, tenant_id, event_ids, category, "
        "amount_paise, residual_paise, confidence, tier, priority_score, recommended_action, "
        "status, signature, created_at) "
        "VALUES ($1, $2, $3, $4, 'amount_variance', $5, $5, 0.9, 'monitor', 0.5, 'review', "
        "'open', 'sig_test', $6)",
        exception_id,
        run_id,
        tenant,
        event_ids,
        residual_paise,
        _AT,
    )


def _token(cfg: Any, *, tenant_id: str, user_id: str) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": "owner",
        "email": f"{user_id}@example.invalid",
        "display_name": user_id,
        "typ": "access",
        "iat": now,
        "exp": now.replace(year=now.year + 1),
    }
    return jwt.encode(claims, cfg.jwt_secret, algorithm=_JWT_ALGORITHM)


async def _row_count(conn: Any, table: str, tenant: str) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {table} WHERE tenant_id = $1", tenant)  # noqa: S608


def _require_jwt_secret() -> Any:
    cfg = load_config()
    if not cfg.jwt_secret:
        pytest.skip("no JWT_SECRET configured")
    return cfg


def test_dry_run_resolve_persists_nothing_and_a_real_call_does() -> None:
    """Check #1a: the simple write endpoint. Row counts, not just a claim."""

    async def body(conn: Any) -> None:
        from api.main import app

        cfg = _require_jwt_secret()
        token_a = _token(cfg, tenant_id=_TENANT_A, user_id=_USER_A)

        exception_id = "exc_dry_run_resolve"
        await _insert_event(
            conn, event_id="evt_dr_1", tenant=_TENANT_A, run_id=_RUN_A, amount_paise=50000
        )
        await _insert_exception(
            conn,
            exception_id=exception_id,
            tenant=_TENANT_A,
            run_id=_RUN_A,
            event_ids=["evt_dr_1"],
            residual_paise=50000,
        )

        exceptions_before = await _row_count(conn, "exceptions", _TENANT_A)
        audit_before = await _row_count(conn, "audit_events", _TENANT_A)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {token_a}"}

            # dry_run=true: the response shows the full computed effect...
            resp = await client.post(
                f"/api/v1/exceptions/{exception_id}/resolve",
                params={"dry_run": "true"},
                json={"reason": "dry run probe"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "resolved"

            # ...but nothing was persisted: identical row counts, unchanged status.
            assert await _row_count(conn, "exceptions", _TENANT_A) == exceptions_before
            assert await _row_count(conn, "audit_events", _TENANT_A) == audit_before
            status = await conn.fetchval(
                "SELECT status FROM exceptions WHERE exception_id = $1", exception_id
            )
            assert status == "open"

            # dry_run=false: the same call, for real.
            resp = await client.post(
                f"/api/v1/exceptions/{exception_id}/resolve",
                params={"dry_run": "false"},
                json={"reason": "for real"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == "resolved"

        # Exceptions row count is unchanged (resolve mutates in place), but the
        # status persisted and exactly one audit row landed.
        assert await _row_count(conn, "exceptions", _TENANT_A) == exceptions_before
        assert await _row_count(conn, "audit_events", _TENANT_A) == audit_before + 1
        status = await conn.fetchval(
            "SELECT status, resolution_reason FROM exceptions WHERE exception_id = $1", exception_id
        )
        assert status == "resolved"

    _run_async(body)


def test_dry_run_link_persists_no_derived_residual_exception() -> None:
    """Check #1b: link has derived side effects — an amount delta AND a
    possible brand-new residual exception row. dry_run must swallow both."""

    async def body(conn: Any) -> None:
        from api.main import app

        cfg = _require_jwt_secret()
        token_a = _token(cfg, tenant_id=_TENANT_A, user_id=_USER_A)

        exception_id = "exc_dry_run_link"
        # residual_paise=100000, linked event only covers 30000 -> 70000
        # left over, well past the default tolerance_abs_paise (100) -> a
        # residual exception must be created on the real call.
        await _insert_event(
            conn, event_id="evt_dl_1", tenant=_TENANT_A, run_id=_RUN_A, amount_paise=100000
        )
        await _insert_event(
            conn, event_id="evt_dl_2", tenant=_TENANT_A, run_id=_RUN_A, amount_paise=30000
        )
        await _insert_exception(
            conn,
            exception_id=exception_id,
            tenant=_TENANT_A,
            run_id=_RUN_A,
            event_ids=["evt_dl_1"],
            residual_paise=100000,
        )

        exceptions_before = await _row_count(conn, "exceptions", _TENANT_A)
        audit_before = await _row_count(conn, "audit_events", _TENANT_A)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {token_a}"}

            resp = await client.post(
                f"/api/v1/exceptions/{exception_id}/link",
                params={"dry_run": "true"},
                json={"event_id": "evt_dl_2", "reason": "found the missing leg"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            body_json = resp.json()
            assert body_json["amount_delta_paise"] == 30000
            assert body_json["residual_exception"] is not None  # the computed effect

            # Neither the mutated original nor the brand-new residual row exists.
            assert await _row_count(conn, "exceptions", _TENANT_A) == exceptions_before
            assert await _row_count(conn, "audit_events", _TENANT_A) == audit_before
            status = await conn.fetchval(
                "SELECT status FROM exceptions WHERE exception_id = $1", exception_id
            )
            assert status == "open"

            resp = await client.post(
                f"/api/v1/exceptions/{exception_id}/link",
                params={"dry_run": "false"},
                json={"event_id": "evt_dl_2", "reason": "found the missing leg"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            residual_id = resp.json()["residual_exception"]["exception_id"]

        # +1 row: the new residual exception. The original still exists (its
        # own row, now resolved), and exactly one audit event landed.
        assert await _row_count(conn, "exceptions", _TENANT_A) == exceptions_before + 1
        assert await _row_count(conn, "audit_events", _TENANT_A) == audit_before + 1
        original_status = await conn.fetchval(
            "SELECT status FROM exceptions WHERE exception_id = $1", exception_id
        )
        assert original_status == "resolved"
        residual_row = await conn.fetchrow(
            "SELECT status, residual_paise FROM exceptions WHERE exception_id = $1", residual_id
        )
        assert residual_row["status"] == "open"
        assert residual_row["residual_paise"] == 70000

    _run_async(body)


def test_rls_isolation_survives_a_reused_pooled_connection() -> None:
    """Check #2: SET LOCAL, not SET. Sequential requests from two different
    tenants against the same FastAPI app (and very plausibly the same
    physical pooled connection, since the app's engine reuses connections
    across requests) must not leak tenant A's data into tenant B's session.
    """

    async def body(conn: Any) -> None:
        from api.main import app

        cfg = _require_jwt_secret()
        token_a = _token(cfg, tenant_id=_TENANT_A, user_id=_USER_A)
        token_b = _token(cfg, tenant_id=_TENANT_B, user_id=_USER_B)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Tenant A can see its own run.
            resp = await client.get(
                f"/api/v1/runs/{_RUN_A}", headers={"Authorization": f"Bearer {token_a}"}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["tenant_id"] == _TENANT_A

            # Immediately after, on the same client (same connection pool),
            # tenant B asks for the exact same run_id and must get nothing —
            # if `SET LOCAL` ever leaked into `SET`, this would return 200.
            resp = await client.get(
                f"/api/v1/runs/{_RUN_A}", headers={"Authorization": f"Bearer {token_b}"}
            )
            assert resp.status_code == 404, resp.text

            # And a third call, back to tenant A, still works — proving B's
            # request didn't corrupt the session for whoever asks next either.
            resp = await client.get(
                f"/api/v1/runs/{_RUN_A}", headers={"Authorization": f"Bearer {token_a}"}
            )
            assert resp.status_code == 200, resp.text

    _run_async(body)
