"""Blocking emits the §6.2 key set, guards oversized blocks, and measures itself.

The two properties worth protecting: the +/-1 amount bucket spill (without it a
fee deduction moves a settlement's net out of its counterpart's block and the
pair is never compared) and the reference-prefix guard (without it a corpus of
identical amounts degenerates to O(n^2)).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fc.config import Config, load_config
from fc.matching.blocking import (
    AMOUNT_BUCKET_PAISE,
    DAY_WINDOW,
    PrefixIndex,
    block_key,
    build_blocks,
    candidate_pairs,
)
from fc.models.transaction import Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)


def _event(
    event_id: str,
    *,
    amount: int,
    day: int = 1,
    source: Source = "razorpay",
    utr: str | None = None,
    value_date: date | None = None,
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t",
        source=source,
        source_row_id=event_id,
        amount_paise=amount,
        direction="credit",
        txn_date=date(2026, 6, day),
        value_date=value_date,
        utr=utr,
        raw={},
        ingested_at=_AT,
    )


def _cfg(**overrides: object) -> Config:
    return load_config(env_file=None, environ={}).model_copy(update=overrides)


def test_block_key_emits_three_buckets_by_seven_days() -> None:
    keys = block_key(_event("e", amount=250_000, day=10))
    assert len(keys) == 21
    assert len(set(keys)) == 21


def test_block_key_spills_one_bucket_either_side() -> None:
    event = _event("e", amount=250_000, day=10)
    bucket = event.amount_paise // AMOUNT_BUCKET_PAISE
    buckets = {b for b, _ in block_key(event)}
    assert buckets == {bucket - 1, bucket, bucket + 1}


def test_block_key_covers_t_plus_minus_three_days() -> None:
    event = _event("e", amount=250_000, day=10)
    day = event.effective_date.toordinal()
    days = {d for _, d in block_key(event)}
    assert days == set(range(day - DAY_WINDOW, day + DAY_WINDOW + 1))


def test_block_key_uses_value_date_when_present() -> None:
    with_value = _event("e", amount=250_000, day=10, value_date=date(2026, 6, 20))
    assert {d for _, d in block_key(with_value)} == set(
        range(date(2026, 6, 20).toordinal() - 3, date(2026, 6, 20).toordinal() + 4)
    )


def test_a_fee_deduction_across_a_bucket_boundary_still_blocks_together() -> None:
    gross = _event("gross", amount=200_000, source="razorpay")
    net = _event("net", amount=199_000, source="bank")  # one bucket lower
    assert set(block_key(gross)) & set(block_key(net))


def test_candidate_pairs_are_cross_source_deduplicated_and_sorted() -> None:
    events = [
        _event("a", amount=100_000, source="razorpay"),
        _event("b", amount=100_000, source="bank"),
        _event("c", amount=100_000, source="razorpay"),
    ]
    by_id = {e.event_id: e for e in events}
    pairs = list(candidate_pairs(build_blocks(events, cfg=_cfg()), by_id))
    assert pairs == sorted(set(pairs))
    assert ("a", "c") not in pairs  # same source
    assert {("a", "b"), ("b", "c")} <= set(pairs)


def test_oversized_blocks_are_sub_bucketed_by_reference_prefix() -> None:
    """References sharing a long prefix still get separated - see ``_shard``."""
    events = [_event(f"e{i:03d}", amount=100_000, utr=f"HDFC26156000{i:04d}") for i in range(12)]
    index = build_blocks(events, cfg=_cfg(max_bucket_size=5))
    assert index.stats.oversize_blocks > 0
    assert index.stats.sub_bucketed_keys > 0
    assert index.stats.largest_block <= 5
    assert index.stats.oversize_after_shard == 0


def test_identical_references_cannot_be_split_and_that_is_reported() -> None:
    """No prefix separates equal strings; the guard says so instead of pretending."""
    events = [_event(f"e{i:03d}", amount=100_000, utr="HDFC261560000000") for i in range(12)]
    index = build_blocks(events, cfg=_cfg(max_bucket_size=5))
    assert index.stats.largest_block == 12
    assert index.stats.oversize_after_shard > 0


def test_events_with_no_reference_at_all_still_block() -> None:
    events = [_event(f"e{i:03d}", amount=100_000) for i in range(12)]
    index = build_blocks(events, cfg=_cfg(max_bucket_size=5))
    assert index.stats.oversize_after_shard > 0


def test_blocking_reduces_the_comparison_count_and_reports_it() -> None:
    events = [
        _event(f"r{i}", amount=100_000 * i, source="razorpay", day=1 + i % 20) for i in range(60)
    ] + [_event(f"b{i}", amount=100_000 * i, source="bank", day=1 + i % 20) for i in range(60)]
    stats = build_blocks(events, cfg=_cfg()).stats
    assert stats.candidate_pairs < stats.naive_cross_source
    assert stats.reduction_ratio > 1


def test_prefix_index_refuses_a_fragment_with_several_completions() -> None:
    index = PrefixIndex(["HDFC261560000000", "HDFC261569000002", "IDFC261560000000"])
    assert index.unique_completion("HDFC2615") is None
    assert index.unique_completion("IDFC") == "IDFC261560000000"
    assert index.unique_completion("") is None
    assert index.unique_completion("NOPE") is None


def test_building_blocks_twice_gives_identical_output() -> None:
    events = [
        _event(f"e{i}", amount=100_000 + i, source="bank" if i % 2 else "razorpay")
        for i in range(20)
    ]
    first = build_blocks(events, cfg=_cfg())
    second = build_blocks(events, cfg=_cfg())
    assert first.blocks == second.blocks
    assert first.stats == second.stats
