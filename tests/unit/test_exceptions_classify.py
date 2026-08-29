"""Classification — PRD §6.8's tree, plus the chargeback sweep.

The sweep is the important case: CLAUDE.md's carry-forward note is that
nothing in ``fc.matching`` ever refuses on dispute presence, so a chargeback
must be found and escalated whether or not the matching cascade folded its
settlement into an auto-closing group.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fc.config import load_config
from fc.exceptions.classify import classify_exceptions
from fc.matching.blocking import BlockingStats
from fc.matching.cascade import CascadeResult, run_cascade
from fc.matching.ledger_refs import index_ledger_refs
from fc.matching.stages import StageRefusal
from fc.models.ids import deterministic_factory
from fc.models.match import MatchEvidence, MatchResult
from fc.models.transaction import Direction, Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)
_CFG = load_config(env_file=None, environ={})


def _event(
    event_id: str,
    *,
    source: Source,
    amount: int,
    day: int = 5,
    direction: Direction = "credit",
    txn_type: str | None = None,
    rail: str | None = None,
    order_id: str | None = None,
    voucher_type: str | None = None,
    ledger_account: str | None = None,
    narration: str | None = None,
    raw: dict[str, object] | None = None,
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t",
        source=source,
        source_row_id=event_id,
        amount_paise=amount,
        direction=direction,
        txn_date=date(2026, 6, day),
        rail=rail,
        order_id=order_id,
        txn_type=txn_type or ("payment" if source == "razorpay" else None),
        voucher_type=voucher_type,
        ledger_account=ledger_account,
        raw_narration=narration,
        raw=raw or {},
        ingested_at=_AT,
    )


def _cascade(events: list[TransactionEvent]) -> CascadeResult:
    return run_cascade(
        events,
        cfg=_CFG,
        run_id="run",
        tenant_id="t",
        issue_id=deterministic_factory(seed=1, epoch_ms=1_780_000_000_000),
        created_at=_AT,
    )


def _empty_stats() -> BlockingStats:
    return BlockingStats(
        events=0,
        naive_comparisons=0,
        naive_cross_source=0,
        candidate_pairs=0,
        reduction_ratio=Decimal(0),
        blocks=0,
        oversize_blocks=0,
        sub_bucketed_keys=0,
        oversize_after_shard=0,
        largest_block=0,
    )


def _minimal_cascade(
    events: list[TransactionEvent],
    *,
    unmatched: tuple[str, ...] = (),
    refusals: tuple[StageRefusal, ...] = (),
    matches: tuple[MatchResult, ...] = (),
) -> CascadeResult:
    return CascadeResult(
        matches=matches,
        unmatched_event_ids=unmatched,
        blocking=_empty_stats(),
        ledger_refs=index_ledger_refs(events),
        stage_counts={},
        abstentions={},
        diagnostics={},
        refusals=refusals,
    )


def _auto_closed_match(event_ids: tuple[str, ...]) -> MatchResult:
    return MatchResult(
        match_id="mch_test",
        run_id="run",
        tenant_id="t",
        group_key="k",
        event_ids=list(event_ids),
        sources_covered=["razorpay", "bank", "ledger"],
        stage="exact_ref",
        confidence=Decimal(1),
        residual_paise=0,
        evidence=[
            MatchEvidence(
                stage="exact_ref", fields_agreed=["settlement_id"], candidates_considered=1
            )
        ],
        auto_closed=True,
        created_at=_AT,
    )


#: A real 26-char Crockford-base32 ULID body, so ledger narration extraction
#: (``fc.matching.ledger_refs``, anchored on exactly 26 characters) accepts it.
_ORDER = "order_01ARZ3NDEKTSV4RRFFQ69G5FAV"


def test_an_unbooked_dispute_is_a_chargeback_regardless_of_match_state() -> None:
    dispute = _event(
        "dp",
        source="razorpay",
        amount=50_000,
        txn_type="dispute",
        order_id=_ORDER,
        raw={"dispute_id": "dp_X"},
    )
    cascade = _minimal_cascade([dispute], unmatched=("dp",))

    found = classify_exceptions([dispute], cascade)

    assert len(found) == 1
    assert found[0].category == "chargeback_unrecorded"
    assert found[0].event_ids == ("dp",)


def test_a_dispute_booked_in_the_ledger_is_not_flagged() -> None:
    dispute = _event("dp", source="razorpay", amount=50_000, txn_type="dispute", order_id=_ORDER)
    booking = _event(
        "led",
        source="ledger",
        amount=50_000,
        direction="debit",
        voucher_type="Journal",
        ledger_account="Disputes",
        narration=f"Chargeback order {_ORDER}",
    )
    cascade = _minimal_cascade([dispute, booking], unmatched=("dp", "led"))

    found = classify_exceptions([dispute, booking], cascade)

    assert all(item.category != "chargeback_unrecorded" for item in found)


_ORDER_A = "order_01ARZ3NDEKTSV4RRFFQ69G5FAV"
_ORDER_B = "order_01BX5ZZKBKACTAV9WEVGEMMVRZ"


def test_two_orders_sharing_gross_with_no_ledger_reference_are_ambiguous() -> None:
    """The order-attribution finding: settlement cash proven, order labels not.

    Both orders sit inside an auto-closed match (proving the cash), and their
    ledger Sales legs carry no order reference at all — the real shape of
    generator scenario 16.
    """
    a = _event("a", source="razorpay", amount=95_000, order_id=_ORDER_A)
    b = _event("b", source="razorpay", amount=95_000, order_id=_ORDER_B)
    bank = _event("bank", source="bank", amount=190_000, rail="neft", narration="NEFT CR:X")
    sales_a = _event(
        "sa",
        source="ledger",
        amount=95_000,
        voucher_type="Sales",
        narration="Sales invoice dated 2026-06-05",
    )
    sales_b = _event(
        "sb",
        source="ledger",
        amount=95_000,
        voucher_type="Sales",
        narration="Sales invoice dated 2026-06-05",
    )
    events = [a, b, bank, sales_a, sales_b]
    match = _auto_closed_match(("a", "b", "bank", "sa", "sb"))
    cascade = _minimal_cascade(events, matches=(match,))

    found = classify_exceptions(events, cascade)

    assert len(found) == 1
    item = found[0]
    assert item.category == "ambiguous_multi_candidate"
    assert set(item.event_ids) == {"a", "b"}
    assert item.residual_paise == 0
    assert item.priority_amount == 0
    assert _ORDER_A in item.reason and _ORDER_B in item.reason


def test_an_order_named_in_the_ledger_is_not_flagged_ambiguous() -> None:
    a = _event("a", source="razorpay", amount=95_000, order_id=_ORDER_A)
    b = _event("b", source="razorpay", amount=95_000, order_id=_ORDER_B)
    bank = _event("bank", source="bank", amount=190_000, rail="neft", narration="NEFT CR:X")
    sales_a = _event(
        "sa",
        source="ledger",
        amount=95_000,
        voucher_type="Sales",
        narration=f"Sales order {_ORDER_A}",
    )
    sales_b = _event(
        "sb",
        source="ledger",
        amount=95_000,
        voucher_type="Sales",
        narration="Sales invoice dated 2026-06-05",
    )
    events = [a, b, bank, sales_a, sales_b]
    match = _auto_closed_match(("a", "b", "bank", "sa", "sb"))
    cascade = _minimal_cascade(events, matches=(match,))

    found = classify_exceptions(events, cascade)

    assert found == ()


def test_an_unmatched_gateway_row_is_missing_in_bank() -> None:
    event = _event("pay", source="razorpay", amount=10_000)
    cascade = _minimal_cascade([event], unmatched=("pay",))

    found = classify_exceptions([event], cascade)

    assert found[0].category == "missing_in_bank"


def test_an_unmatched_bank_credit_is_missing_in_gateway() -> None:
    event = _event("bank", source="bank", amount=10_000, rail="neft", narration="NEFT CR:X")
    cascade = _minimal_cascade([event], unmatched=("bank",))

    found = classify_exceptions([event], cascade)

    assert found[0].category == "missing_in_gateway"


def test_an_unmatched_nach_row_is_a_nach_batch() -> None:
    event = _event("bank", source="bank", amount=10_000, rail="nach", narration="NACH-BATCH01-NPCI")
    cascade = _minimal_cascade([event], unmatched=("bank",))

    found = classify_exceptions([event], cascade)

    assert found[0].category == "nach_batch_unexploded"


def test_an_unmatched_refund_is_a_partial_refund() -> None:
    event = _event("rfnd", source="razorpay", amount=5_000, direction="debit", txn_type="refund")
    cascade = _minimal_cascade([event], unmatched=("rfnd",))

    found = classify_exceptions([event], cascade)

    assert found[0].category == "partial_refund"


def test_same_amount_far_apart_dates_is_a_timing_lag() -> None:
    gateway = _event("pay", source="razorpay", amount=10_000, day=1)
    bank = _event("bank", source="bank", amount=10_000, day=10, rail="neft", narration="NEFT CR:X")
    cascade = _minimal_cascade([gateway, bank], unmatched=("pay", "bank"))

    found = classify_exceptions([gateway, bank], cascade)

    assert {item.category for item in found} == {"timing_lag"}


def test_a_refusal_becomes_an_exception_with_its_own_category() -> None:
    left = _event("a", source="razorpay", amount=1_000)
    right = _event("b", source="razorpay", amount=2_000)
    refusal = StageRefusal(
        category="ambiguous_multi_candidate",
        event_ids=("a", "b"),
        amount_paise=1_000,
        reason="two candidates, same evidence",
    )
    cascade = _minimal_cascade([left, right], unmatched=("a", "b"), refusals=(refusal,))

    found = classify_exceptions([left, right], cascade)

    assert len(found) == 1
    assert found[0].category == "ambiguous_multi_candidate"
    assert found[0].event_ids == ("a", "b")


def test_every_event_lands_in_at_most_one_finding() -> None:
    """A refusal already accounts for its events; the unmatched sweep must not
    double them into a second, vaguer exception."""
    left = _event("a", source="razorpay", amount=1_000)
    right = _event("b", source="razorpay", amount=2_000)
    refusal = StageRefusal(
        category="ambiguous_multi_candidate",
        event_ids=("a", "b"),
        amount_paise=1_000,
        reason="two candidates",
    )
    cascade = _minimal_cascade([left, right], unmatched=("a", "b"), refusals=(refusal,))

    found = classify_exceptions([left, right], cascade)
    seen: set[str] = set()
    for item in found:
        assert not (seen & set(item.event_ids))
        seen.update(item.event_ids)
