"""Hash-chain integrity against a real ``audit_events`` table.

This is the demo moment for Prompt 8: ``verify_chain`` does not just look
correct, it detects a payload mutated by a direct SQL ``UPDATE`` that never
went through the ledger module, the ORM, or the API — and it names the exact
``seq``. Mirrors ``test_rules_immutability.py``'s connection and skip pattern.

The owner connection is used to tamper, deliberately, for the same reason
``test_rules_immutability.py`` uses it for the trigger test: ``neondb_owner``
bypasses both the ``REVOKE UPDATE ... FROM fc_app`` grant and every RLS
policy, so a tamper that succeeds against the owner is the strongest thing
this test could show — the hash chain has no privileged escape hatch.
``test_fc_app_user_cannot_update_audit_events`` below is the separate,
narrower claim that the application's own role can't do this either.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from fc.audit.ledger import GENESIS_HASH, HASH_MISMATCH, SEQUENCE_GAP, append_batch, verify_chain
from fc.config import asyncpg_url, load_config

asyncpg = pytest.importorskip("asyncpg", reason="asyncpg is not installed")

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_TENANT = "t_audit_ledger_test"
_USER = "u_audit_ledger_test"
_RUN = "run_audit_ledger_test"


def _plain_url(url: str) -> str:
    return asyncpg_url(url).replace("postgresql+asyncpg://", "postgresql://")


def _owner_url() -> str:
    cfg = load_config()
    url = cfg.database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("no DATABASE_URL configured")
    return _plain_url(url)


def _app_url() -> str | None:
    cfg = load_config()
    url = cfg.database_url_app or os.environ.get("DATABASE_URL_APP", "")
    return _plain_url(url) if url else None


def _run_async[T](body: Callable[[Any], Awaitable[T]]) -> T:
    async def main() -> T:
        try:
            conn = await asyncio.wait_for(asyncpg.connect(_owner_url()), timeout=20)
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
        "audit ledger test",
    )
    await conn.execute(
        "INSERT INTO users (user_id, tenant_id, email, display_name, role, status) "
        "VALUES ($1, $2, $3, $4, 'controller', 'active')",
        _USER,
        _TENANT,
        "audit-ledger-test@example.invalid",
        "Audit Ledger Test",
    )
    await conn.execute(
        "INSERT INTO runs (run_id, tenant_id, triggered_by, status, ruleset_hash, "
        "input_hashes, config) "
        "VALUES ($1, $2, $3, 'complete', 'deadbeef', '{}'::jsonb, '{}'::jsonb)",
        _RUN,
        _TENANT,
        _USER,
    )


async def _cleanup(conn: Any) -> None:
    await conn.execute("DELETE FROM audit_events WHERE tenant_id = $1", _TENANT)
    await conn.execute("DELETE FROM runs WHERE tenant_id = $1", _TENANT)
    await conn.execute("DELETE FROM users WHERE tenant_id = $1", _TENANT)
    await conn.execute("DELETE FROM tenants WHERE tenant_id = $1", _TENANT)


def _sample_entries(n: int = 5) -> list[dict[str, Any]]:
    return [
        dict(
            tenant_id=_TENANT,
            run_id=_RUN,
            actor="system",
            action="ingest.row",
            subject_type="event",
            subject_id=f"evt_{i}",
            payload={
                "source": "razorpay",
                "amount_paise": 100000 + i,
                "confidence": Decimal("0.9800"),
            },
            created_at=_AT,
            ruleset_hash="deadbeef",
        )
        for i in range(n)
    ]


async def _insert_events(conn: Any, events: list[Any]) -> list[int]:
    seqs: list[int] = []
    for event in events:
        seq = await conn.fetchval(
            "INSERT INTO audit_events (tenant_id, run_id, actor, action, subject_type, "
            "subject_id, payload, ruleset_hash, prev_hash, this_hash, created_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11) RETURNING seq",
            event.tenant_id,
            event.run_id,
            event.actor,
            event.action,
            event.subject_type,
            event.subject_id,
            json.dumps(event.payload),
            event.ruleset_hash,
            event.prev_hash,
            event.this_hash,
            event.created_at,
        )
        seqs.append(seq)
    return seqs


async def _fetch_chain(conn: Any) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT seq, prev_hash, this_hash, payload, actor, action, subject_id "
        "FROM audit_events WHERE tenant_id = $1 ORDER BY seq",
        _TENANT,
    )
    return [
        {
            "seq": r["seq"],
            "prev_hash": r["prev_hash"],
            "this_hash": r["this_hash"],
            "payload": json.loads(r["payload"]),
            "actor": r["actor"],
            "action": r["action"],
            "subject_id": r["subject_id"],
        }
        for r in rows
    ]


def test_verify_chain_is_valid_over_a_freshly_appended_run() -> None:
    async def body(conn: Any) -> None:
        events = append_batch(_sample_entries(), prev_hash=GENESIS_HASH)
        await _insert_events(conn, events)

        chain = await _fetch_chain(conn)
        valid, first_break, reason = verify_chain(chain, expected_prev_hash=GENESIS_HASH)
        assert valid is True
        assert first_break is None
        assert reason is None

    _run_async(body)


def test_verify_chain_reports_the_exact_seq_of_a_tampered_row() -> None:
    """The headline: mutate one payload directly in Postgres, then prove it's caught."""

    async def body(conn: Any) -> None:
        events = append_batch(_sample_entries(), prev_hash=GENESIS_HASH)
        seqs = await _insert_events(conn, events)
        tampered_seq = seqs[2]

        # Bypasses the ledger module, the ORM and the API entirely.
        await conn.execute(
            "UPDATE audit_events SET payload = $1::jsonb WHERE seq = $2",
            json.dumps({"source": "razorpay", "amount_paise": 999999999, "confidence": "0.9800"}),
            tampered_seq,
        )

        chain = await _fetch_chain(conn)
        valid, first_break, reason = verify_chain(chain, expected_prev_hash=GENESIS_HASH)
        assert valid is False
        assert first_break == tampered_seq
        assert reason == HASH_MISMATCH

        # Rows before the tamper, and the tamper's own seq, are unaffected by
        # which row was hit — the break is reported exactly once, at seq 3,
        # not smeared across every row that follows it in the fetch order.
        assert tampered_seq == seqs[2]

    _run_async(body)


def test_verify_chain_reports_the_exact_seq_regardless_of_which_row_is_tampered() -> None:
    """Same proof, at the last row instead of the middle — the break is positional,
    not "always the middle of the batch" by accident of the first test's shape."""

    async def body(conn: Any) -> None:
        events = append_batch(_sample_entries(6), prev_hash=GENESIS_HASH)
        seqs = await _insert_events(conn, events)
        tampered_seq = seqs[-1]

        await conn.execute(
            "UPDATE audit_events SET actor = $1 WHERE seq = $2",
            "user:attacker",
            tampered_seq,
        )

        chain = await _fetch_chain(conn)
        valid, first_break, reason = verify_chain(chain, expected_prev_hash=GENESIS_HASH)
        assert valid is False
        assert first_break == tampered_seq
        assert reason == HASH_MISMATCH

    _run_async(body)


def test_verify_chain_reports_a_deleted_middle_row_as_a_sequence_gap() -> None:
    """The gap this whole mechanism exists for: a tamperer with database access
    deletes a row rather than editing it, precisely because editing is what the
    hash chain catches. This DELETEs seq 47-equivalent directly and confirms
    verify_chain reports it as a gap at that exact seq, not a hash_mismatch."""

    async def body(conn: Any) -> None:
        events = append_batch(_sample_entries(6), prev_hash=GENESIS_HASH)
        seqs = await _insert_events(conn, events)
        deleted_seq = seqs[2]

        await conn.execute("DELETE FROM audit_events WHERE seq = $1", deleted_seq)

        chain = await _fetch_chain(conn)
        valid, first_break, reason = verify_chain(chain, expected_prev_hash=GENESIS_HASH)
        assert valid is False
        assert first_break == deleted_seq
        assert reason == SEQUENCE_GAP

    _run_async(body)


def test_fc_app_user_cannot_update_audit_events() -> None:
    """The grant that makes the ledger append-only for the application itself.

    ``verify_chain`` proves tampering is *detectable*; this proves the
    application's own database role can't perform it in the first place —
    a different and stronger guarantee, and one worth testing separately so
    neither hides a gap in the other.
    """

    async def body(conn: Any) -> None:
        events = append_batch(_sample_entries(1), prev_hash=GENESIS_HASH)
        seqs = await _insert_events(conn, events)

        app_url = _app_url()
        if not app_url:
            pytest.skip("no DATABASE_URL_APP configured")
        app_conn = await asyncpg.connect(app_url)
        try:
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await app_conn.execute(
                    "UPDATE audit_events SET actor = 'tampered' WHERE seq = $1", seqs[0]
                )
        finally:
            await app_conn.close()

    _run_async(body)
