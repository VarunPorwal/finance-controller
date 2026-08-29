"""Stage 3 needs a real date shift and a reference fragment that means something.

The uniqueness rule is what keeps this stage honest. An RBI UTR is
``bank + year + day-of-year + sequence``, so a shared eight-character prefix is
evidence of nothing - in the generated corpus one such prefix covers fourteen
settlements. A fragment with several completions is an abstention, not a match.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fc.config import Config, load_config
from fc.matching.blocking import build_blocks
from fc.matching.stages.date_shift import BASE_CONFIDENCE, find_matches
from fc.models.transaction import Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)


def _cfg(**overrides: object) -> Config:
    return load_config(env_file=None, environ={}).model_copy(update=overrides)


def _event(
    event_id: str,
    *,
    source: Source,
    amount: int,
    day: int,
    utr: str | None = None,
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
        utr=utr,
        raw={},
        ingested_at=_AT,
    )


def _run(events: list[TransactionEvent], cfg: Config | None = None) -> list[tuple[str, ...]]:
    settings = cfg or _cfg()
    output = find_matches(events, index=build_blocks(events, cfg=settings), cfg=settings)
    return sorted(m.event_ids for m in output.matches)


def test_a_two_day_shift_with_a_uniquely_completing_fragment_matches() -> None:
    events = [
        _event("g", source="razorpay", amount=100_000, day=5, utr="HDFC261560000000"),
        _event("b", source="bank", amount=100_000, day=7, utr="HDFC26156"),
    ]
    assert _run(events) == [("b", "g")]


def test_confidence_falls_two_points_a_day() -> None:
    events = [
        _event("g", source="razorpay", amount=100_000, day=5, utr="HDFC261560000000"),
        _event("b", source="bank", amount=100_000, day=8, utr="HDFC26156"),
    ]
    output = find_matches(events, index=build_blocks(events, cfg=_cfg()), cfg=_cfg())
    match = output.matches[0]
    assert match.date_shift_days == 3
    assert match.base_confidence == BASE_CONFIDENCE - Decimal("0.02") * 3


def test_a_same_day_pair_is_not_this_stage_s_business() -> None:
    events = [
        _event("g", source="razorpay", amount=100_000, day=5, utr="HDFC261560000000"),
        _event("b", source="bank", amount=100_000, day=5, utr="HDFC26156"),
    ]
    assert _run(events) == []


def test_a_shift_beyond_three_days_is_not_a_shift() -> None:
    events = [
        _event("g", source="razorpay", amount=100_000, day=5, utr="HDFC261560000000"),
        _event("b", source="bank", amount=100_000, day=12, utr="HDFC26156"),
    ]
    assert _run(events) == []


def test_an_ambiguous_fragment_abstains_rather_than_guessing() -> None:
    """Two settlements share the prefix, so it identifies neither."""
    events = [
        _event("g1", source="razorpay", amount=100_000, day=5, utr="HDFC261560000000"),
        _event("g2", source="razorpay", amount=100_000, day=5, utr="HDFC261560000001"),
        _event("b", source="bank", amount=100_000, day=7, utr="HDFC26156"),
    ]
    output = find_matches(events, index=build_blocks(events, cfg=_cfg()), cfg=_cfg())
    assert output.matches == ()
    assert output.abstained != ()
    assert output.diagnostics["ambiguous_reference_fragments"] > 0


def test_a_fragment_shorter_than_the_minimum_is_not_evidence() -> None:
    events = [
        _event("g", source="razorpay", amount=100_000, day=5, utr="HDFC261560000000"),
        _event("b", source="bank", amount=100_000, day=7, utr="HDFC"),
    ]
    assert _run(events) == []


def test_amounts_outside_tolerance_do_not_match_however_good_the_reference() -> None:
    events = [
        _event("g", source="razorpay", amount=100_000, day=5, utr="HDFC261560000000"),
        _event("b", source="bank", amount=140_000, day=7, utr="HDFC26156"),
    ]
    assert _run(events) == []


def test_same_source_events_are_never_paired() -> None:
    events = [
        _event("g1", source="razorpay", amount=100_000, day=5, utr="HDFC261560000000"),
        _event("g2", source="razorpay", amount=100_000, day=7, utr="HDFC26156"),
    ]
    assert _run(events) == []


def test_output_is_stable_across_runs() -> None:
    events = [
        _event("g", source="razorpay", amount=100_000, day=5, utr="HDFC261560000000"),
        _event("b", source="bank", amount=100_000, day=7, utr="HDFC26156"),
    ]
    assert _run(events) == _run(events)
