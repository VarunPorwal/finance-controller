"""Pure tests for the hash chain: no database, no clock, no network.

The database-backed proof that ``verify_chain`` catches a tamper made
directly in Postgres lives in ``tests/integration/test_audit_ledger.py`` —
these tests are the fast, always-on layer underneath it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fc.audit.ledger import (
    GENESIS_HASH,
    HASH_MISMATCH,
    AuditEventInput,
    append,
    append_batch,
    canonical_json,
    compute_hash,
    normalize_payload,
    sequence_gaps,
    verify_chain,
)

_AT = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)


def _entry(i: int, **overrides: object) -> dict:
    base = dict(
        tenant_id="t_test",
        actor="system",
        action="ingest.row",
        subject_type="event",
        subject_id=f"evt_{i}",
        payload={"amount_paise": 1000 + i},
        created_at=_AT,
    )
    base.update(overrides)
    return base


def test_canonical_json_is_stable_under_key_order() -> None:
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b == '{"a":2,"b":1}'


def test_canonical_json_does_not_itself_validate_float_rejection_belongs_to_normalize() -> None:
    """canonical_json is the low-level formatter; normalize_payload is the guard
    that keeps float out before anything reaches it (see the test below)."""
    assert canonical_json({"amount": 12.5}) == '{"amount":12.5}'


def test_normalize_payload_converts_decimal_and_datetime() -> None:
    normalized = normalize_payload(
        {"confidence": Decimal("0.9800"), "at": _AT, "nested": {"rate": Decimal("18.0")}}
    )
    assert normalized == {
        "confidence": "0.9800",
        "at": _AT.isoformat(),
        "nested": {"rate": "18.0"},
    }


def test_normalize_payload_rejects_float_even_nested() -> None:
    with pytest.raises(TypeError):
        normalize_payload({"nested": {"amount": 1.5}})


def test_normalize_payload_preserves_bool_and_int() -> None:
    assert normalize_payload({"ok": True, "n": 3}) == {"ok": True, "n": 3}


def test_compute_hash_is_deterministic() -> None:
    kwargs = dict(
        prev_hash=GENESIS_HASH, payload={"x": 1}, actor="system", action="a", subject_id="s"
    )
    assert compute_hash(**kwargs) == compute_hash(**kwargs)


def test_compute_hash_changes_with_any_hashed_field() -> None:
    base = compute_hash(
        prev_hash=GENESIS_HASH, payload={"x": 1}, actor="system", action="a", subject_id="s"
    )
    variants = [
        dict(prev_hash=GENESIS_HASH, payload={"x": 2}, actor="system", action="a", subject_id="s"),
        dict(prev_hash=GENESIS_HASH, payload={"x": 1}, actor="human", action="a", subject_id="s"),
        dict(prev_hash=GENESIS_HASH, payload={"x": 1}, actor="system", action="b", subject_id="s"),
        dict(prev_hash=GENESIS_HASH, payload={"x": 1}, actor="system", action="a", subject_id="t"),
        dict(prev_hash="1" * 64, payload={"x": 1}, actor="system", action="a", subject_id="s"),
    ]
    for kwargs in variants:
        assert base != compute_hash(**kwargs)


def test_append_chains_from_the_given_prev_hash() -> None:
    event = append(prev_hash=GENESIS_HASH, **_entry(0))
    assert event.prev_hash == GENESIS_HASH
    assert event.this_hash == compute_hash(
        prev_hash=GENESIS_HASH,
        payload=event.payload,
        actor=event.actor,
        action=event.action,
        subject_id=event.subject_id,
    )


def test_append_batch_chains_sequentially_in_memory() -> None:
    events = append_batch([_entry(i) for i in range(4)], prev_hash=GENESIS_HASH)
    assert events[0].prev_hash == GENESIS_HASH
    for earlier, later in zip(events, events[1:], strict=False):
        assert later.prev_hash == earlier.this_hash
    # Every this_hash is still independently reproducible from its own row.
    valid, first_break, reason = verify_chain(
        [e.model_dump() | {"seq": i} for i, e in enumerate(events)], expected_prev_hash=GENESIS_HASH
    )
    assert valid is True
    assert first_break is None
    assert reason is None


def test_append_batch_accepts_audit_event_input_models() -> None:
    inputs = [AuditEventInput(**_entry(i)) for i in range(3)]
    events = append_batch(inputs, prev_hash=GENESIS_HASH)
    assert len(events) == 3
    assert events[1].prev_hash == events[0].this_hash


def _as_rows(events: list, start_seq: int = 1) -> list[dict]:
    return [e.model_dump() | {"seq": start_seq + i} for i, e in enumerate(events)]


def test_verify_chain_valid_over_a_clean_batch() -> None:
    events = append_batch([_entry(i) for i in range(6)], prev_hash=GENESIS_HASH)
    valid, first_break, reason = verify_chain(_as_rows(events), expected_prev_hash=GENESIS_HASH)
    assert valid is True
    assert first_break is None
    assert reason is None


def test_verify_chain_detects_a_tampered_payload_at_its_exact_seq() -> None:
    events = append_batch([_entry(i) for i in range(6)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    rows[3]["payload"] = {"amount_paise": 999999}  # this_hash for seq=4 no longer matches
    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == rows[3]["seq"] == 4
    assert reason == HASH_MISMATCH


def test_verify_chain_detects_a_tampered_actor_at_its_exact_seq() -> None:
    events = append_batch([_entry(i) for i in range(6)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    rows[5]["actor"] = "user:attacker"
    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == rows[5]["seq"] == 6
    assert reason == HASH_MISMATCH


def test_verify_chain_detects_a_broken_prev_hash_link() -> None:
    """A row's stored this_hash was rewritten in place, so it stays internally
    self-consistent, but the next row's prev_hash no longer points at it."""
    events = append_batch([_entry(i) for i in range(4)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    rows[2]["prev_hash"] = "f" * 64
    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == rows[2]["seq"] == 3
    assert reason == HASH_MISMATCH


def test_verify_chain_only_flags_the_first_break_not_every_row_after_it() -> None:
    events = append_batch([_entry(i) for i in range(5)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    rows[1]["payload"] = {"amount_paise": -1}
    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == rows[1]["seq"] == 2
    assert reason == HASH_MISMATCH


def test_verify_chain_empty_is_trivially_valid() -> None:
    assert verify_chain([], expected_prev_hash=GENESIS_HASH) == (True, None, None)


def test_verify_chain_without_expected_prev_hash_trusts_the_first_rows_own_prev_hash() -> None:
    """A sub-range query (e.g. from_seq=50) has no way to know seq 49's this_hash
    unless the caller supplies it, so the first row's own prev_hash is accepted."""
    events = append_batch([_entry(i) for i in range(3)], prev_hash="c" * 64)
    rows = _as_rows(events, start_seq=51)
    valid, first_break, reason = verify_chain(rows)
    assert valid is True
    assert first_break is None
    assert reason is None


def test_verify_chain_detects_a_deleted_middle_row_through_the_broken_link() -> None:
    """A deletion is caught by the hash chain, not by counting seq values.

    The surviving successor's ``prev_hash`` still points at the row that was
    removed, so the link fails to close and the break is reported at the first
    row that actually exists.
    """
    events = append_batch([_entry(i) for i in range(5)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    del rows[2]  # simulate DELETE FROM audit_events WHERE seq = 3

    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == 4  # the surviving row whose prev_hash no longer matches
    assert reason == HASH_MISMATCH


def test_verify_chain_detects_a_multi_row_deletion() -> None:
    events = append_batch([_entry(i) for i in range(6)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    del rows[2:4]  # seq 3 and 4 both gone

    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == 5
    assert reason == HASH_MISMATCH


def test_verify_chain_accepts_burned_sequence_numbers() -> None:
    """The case that made the endpoint useless: a gap with the link intact.

    PostgreSQL burns BIGSERIAL values on any rolled-back transaction, so a
    healthy chain routinely has holes in its seq column. Production has two, of
    47 and 74 numbers. Nothing was deleted, every prev_hash still closes, and
    the chain is valid.
    """
    events = append_batch([_entry(i) for i in range(4)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    for row, seq in zip(rows, [1, 49, 50, 124], strict=True):
        row["seq"] = seq  # the chain is untouched; only the numbering jumps

    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is True
    assert first_break is None
    assert reason is None

    assert sequence_gaps(rows) == ((1, 49), (50, 124))


def test_verify_chain_detects_deletion_of_the_very_first_row() -> None:
    """No predecessor's link can break, so this needs the genesis anchor."""
    events = append_batch([_entry(i) for i in range(4)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    del rows[0]

    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == 2
    assert reason == HASH_MISMATCH

    # Without the anchor the truncated chain looks internally consistent —
    # which is exactly why the router passes GENESIS_HASH for a full fetch.
    assert verify_chain(rows) == (True, None, None)


def test_sequence_gaps_is_empty_for_a_contiguous_range() -> None:
    events = append_batch([_entry(i) for i in range(4)], prev_hash=GENESIS_HASH)
    assert sequence_gaps(_as_rows(events)) == ()
