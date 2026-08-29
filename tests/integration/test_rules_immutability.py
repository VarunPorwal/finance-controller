"""An active rule's deductions cannot be edited. The database says so, not the code.

PRD §4.3.6. This is the guarantee the whole replay story rests on: an exception
closed in June by ``blinkit_commission`` v3 must still be explainable by v3 in
December, and it would not be if somebody could edit v3's rates in place. A
version hash over the deductions makes tampering *visible*; the trigger makes it
*impossible*, which is a different and stronger claim.

Runs against the configured database and **skips** when there isn't one, so it
does not turn ``dev.ps1 check`` into something that needs a network. That is a
real hole and it is named in the module docstring rather than hidden: on a
machine with no ``DATABASE_URL`` this file proves nothing.

The owner connection is used deliberately. ``neondb_owner`` carries
``rolbypassrls``, so it is the wrong role for testing RLS (CLAUDE.md) — but a
``BEFORE UPDATE`` trigger is not a policy and does not care who is connected.
Testing it as the owner is therefore the stronger test, not the weaker one: it
shows that even the role that can bypass every policy cannot rewrite history.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from fc.config import asyncpg_url, load_config
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules

asyncpg = pytest.importorskip("asyncpg", reason="asyncpg is not installed")

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_TENANT = "t_rules_immutability_test"
_USER = "u_rules_immutability_test"
_RULE = "test_immutable_rule"


def _database_url() -> str:
    cfg = load_config()
    url = cfg.database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("no DATABASE_URL configured")
    # asyncpg's own connect() takes a plain postgresql:// URL, not the
    # SQLAlchemy dialect form the config carries for the API.
    return asyncpg_url(url).replace("postgresql+asyncpg://", "postgresql://")


def _run[T](body: Callable[[Any], Awaitable[T]]) -> T:
    """Connect, run ``body``, always clean up. Skips if the database is unreachable."""

    async def main() -> T:
        try:
            conn = await asyncio.wait_for(asyncpg.connect(_database_url()), timeout=20)
        except (TimeoutError, OSError, asyncpg.PostgresError) as exc:
            pytest.skip(f"database unreachable: {exc}")
        try:
            await _seed(conn)
            return await body(conn)
        finally:
            await _cleanup(conn)
            await conn.close()

    return asyncio.run(main())


async def _seed(conn: Any) -> None:
    await _cleanup(conn)
    await conn.execute(
        "INSERT INTO tenants (tenant_id, name, status) VALUES ($1, $2, 'active')",
        _TENANT,
        "rules immutability test",
    )
    await conn.execute(
        "INSERT INTO users (user_id, tenant_id, email, display_name, role, status) "
        "VALUES ($1, $2, $3, $4, 'controller', 'active')",
        _USER,
        _TENANT,
        "immutability-test@example.invalid",
        "Immutability Test",
    )


async def _cleanup(conn: Any) -> None:
    await conn.execute("DELETE FROM rules WHERE tenant_id = $1", _TENANT)
    await conn.execute("DELETE FROM users WHERE tenant_id = $1", _TENANT)
    await conn.execute("DELETE FROM tenants WHERE tenant_id = $1", _TENANT)


async def _insert_rule(conn: Any, *, version: int, status: str) -> None:
    """Insert one version of the shipped Blinkit rule under the test tenant."""
    (blinkit,) = load_rules(DEFAULT_RULES_PATH, tenant_id=_TENANT, created_at=_AT).by_id(
        "blinkit_commission"
    )
    await conn.execute(
        """
        INSERT INTO rules (rule_id, version, tenant_id, version_hash, name, scope,
                           deductions, tolerance, priority, effective_confidence,
                           effective_from, status, origin, created_by)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9, $10, $11, $12,
                'manual', $13)
        """,
        _RULE,
        version,
        _TENANT,
        blinkit.version_hash,
        blinkit.name,
        blinkit.scope.model_dump_json(exclude_none=True),
        json.dumps([d.model_dump(mode="json") for d in blinkit.deductions]),
        blinkit.tolerance.model_dump_json(),
        blinkit.priority,
        Decimal("0.95"),
        date(2026, 4, 1),
        status,
        _USER,
    )


_EDITED_DEDUCTIONS = json.dumps(
    [
        {"type": "commission", "basis": "gross", "rate": "20.0", "fixed_paise": None},
        {"type": "gst_on_fee", "basis": "commission", "rate": "18.0", "fixed_paise": None},
        {"type": "tds_194o", "basis": "gross", "rate": "1.0", "fixed_paise": None},
    ]
)


def test_editing_an_active_rules_deductions_raises_the_trigger() -> None:
    """The headline. 18% -> 20% on a live rule is refused by Postgres."""

    async def body(conn: Any) -> None:
        await _insert_rule(conn, version=3, status="active")
        with pytest.raises(asyncpg.RaiseError, match="Active rules are immutable"):
            await conn.execute(
                "UPDATE rules SET deductions = $1::jsonb WHERE rule_id = $2 AND version = 3",
                _EDITED_DEDUCTIONS,
                _RULE,
            )
        # And nothing moved.
        stored = await conn.fetchval(
            "SELECT deductions FROM rules WHERE rule_id = $1 AND version = 3", _RULE
        )
        assert '"rate": "18.0"' in stored or '"rate":"18.0"' in stored

    _run(body)


def test_editing_an_active_rules_scope_or_tolerance_is_refused_too() -> None:
    """Widening a scope silently re-aims a rule at rows it was never approved for."""

    async def body(conn: Any) -> None:
        await _insert_rule(conn, version=3, status="active")
        with pytest.raises(asyncpg.RaiseError, match="Active rules are immutable"):
            await conn.execute(
                "UPDATE rules SET scope = $1::jsonb WHERE rule_id = $2 AND version = 3",
                json.dumps(
                    {"counterparty_matches": ["BLINKIT", "ZEPTO"], "date_from": "2026-04-01"}
                ),
                _RULE,
            )
        with pytest.raises(asyncpg.RaiseError, match="Active rules are immutable"):
            await conn.execute(
                "UPDATE rules SET tolerance = $1::jsonb WHERE rule_id = $2 AND version = 3",
                json.dumps({"absolute_paise": 500000, "percent": "0.05"}),
                _RULE,
            )

    _run(body)


def test_a_draft_can_still_be_edited() -> None:
    """The trigger guards history, not authorship. An unapproved rule is not history."""

    async def body(conn: Any) -> None:
        await _insert_rule(conn, version=1, status="draft")
        await conn.execute(
            "UPDATE rules SET deductions = $1::jsonb WHERE rule_id = $2 AND version = 1",
            _EDITED_DEDUCTIONS,
            _RULE,
        )
        stored = await conn.fetchval(
            "SELECT deductions FROM rules WHERE rule_id = $1 AND version = 1", _RULE
        )
        assert "20.0" in stored

    _run(body)


def test_an_active_rule_can_still_be_retired() -> None:
    """Immutable is not frozen: status and effective_to are how a rule ends."""

    async def body(conn: Any) -> None:
        await _insert_rule(conn, version=3, status="active")
        await conn.execute(
            "UPDATE rules SET status = 'retired', effective_to = $1 "
            "WHERE rule_id = $2 AND version = 3",
            date(2026, 6, 30),
            _RULE,
        )
        status = await conn.fetchval(
            "SELECT status FROM rules WHERE rule_id = $1 AND version = 3", _RULE
        )
        assert status == "retired"

    _run(body)


def test_a_rate_change_is_a_new_version_alongside_the_old_one() -> None:
    """The supported path, and the reason the trigger costs nothing in practice."""

    async def body(conn: Any) -> None:
        await _insert_rule(conn, version=3, status="active")
        await _insert_rule(conn, version=4, status="active")
        await conn.execute(
            "UPDATE rules SET effective_to = $1 WHERE rule_id = $2 AND version = 3",
            date(2026, 6, 30),
            _RULE,
        )
        versions = await conn.fetch(
            "SELECT version, effective_to FROM rules WHERE rule_id = $1 ORDER BY version", _RULE
        )
        assert [r["version"] for r in versions] == [3, 4]
        assert versions[0]["effective_to"] == date(2026, 6, 30)
        assert versions[1]["effective_to"] is None

    _run(body)
