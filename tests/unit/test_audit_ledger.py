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
    SEQUENCE_GAP,
    AuditEventInput,
    append,
    append_batch,
    canonical_json,
    compute_hash,
    normalize_payload,
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


def test_verify_chain_detects_a_missing_middle_row_as_a_sequence_gap() -> None:
    """A deleted row leaves its neighbours each internally correct — no hash check
    alone would ever catch its absence — so this needs its own detection path."""
    events = append_batch([_entry(i) for i in range(5)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    missing_seq = rows[2]["seq"]
    del rows[2]  # simulate DELETE FROM audit_events WHERE seq = missing_seq

    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == missing_seq == 3
    assert reason == SEQUENCE_GAP


def test_verify_chain_reports_the_first_missing_seq_of_a_multi_row_gap() -> None:
    events = append_batch([_entry(i) for i in range(6)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    del rows[2:4]  # seq 3 and 4 both gone; the gap is reported at the first one

    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == 3
    assert reason == SEQUENCE_GAP


def test_verify_chain_prefers_sequence_gap_over_hash_mismatch_when_both_are_present() -> None:
    """A gap is a more precise diagnosis than the prev_hash mismatch it would
    otherwise present as, so it takes priority when a row after a gap is also
    independently tampered."""
    events = append_batch([_entry(i) for i in range(5)], prev_hash=GENESIS_HASH)
    rows = _as_rows(events)
    del rows[2]
    rows[2]["actor"] = "user:attacker"  # the row now at index 2 (originally seq 4)

    valid, first_break, reason = verify_chain(rows, expected_prev_hash=GENESIS_HASH)
    assert valid is False
    assert first_break == 3
    assert reason == SEQUENCE_GAP


def test_verify_chain_gap_detection_does_not_depend_on_expected_prev_hash() -> None:
    events = append_batch([_entry(i) for i in range(4)], prev_hash="c" * 64)
    rows = _as_rows(events, start_seq=51)
    del rows[1]  # drop seq 52

    valid, first_break, reason = verify_chain(rows)
    assert valid is False
    assert first_break == 52
    assert reason == SEQUENCE_GAP
