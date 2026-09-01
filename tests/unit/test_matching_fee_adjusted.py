"""Stage 2 reconciles a settlement's deduction stack, and refuses when it should.

The arithmetic is the point: the evidence pack shows the sum, not a score. Two
behaviours guard precision - a credit quoting a reference that contradicts the
settlement is refused however well the numbers line up, and two settlements
reconciling to one credit produce no match at all.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fc.config import Config, load_config
from fc.matching.stages.fee_adjusted import (
    BASE_CONFIDENCE,
    BASE_CONFIDENCE_RATIONALE,
    find_matches,
    settlement_arithmetic,
)
from fc.models.transaction import Direction, Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)
_SETL = "setl_01KT07NVH5KTVYN9PVWMBFQW16"
_UTR = "HDFC261560000000"


def _cfg(**overrides: object) -> Config:
    return load_config(env_file=None, environ={}).model_copy(update=overrides)


def _gateway(
    event_id: str,
    *,
    amount: int,
    txn_type: str,
    direction: Direction = "credit",
    fee: int | None = None,
    tax: int | None = None,
    settlement_id: str = _SETL,
    utr: str | None = _UTR,
    description: str | None = None,
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t",
        source="razorpay",
        source_row_id=event_id,
        amount_paise=amount,
        direction=direction,
        txn_date=date(2026, 6, 5),
        utr=utr,
        settlement_id=settlement_id,
        txn_type=txn_type,
        fee_paise=fee,
        tax_paise=tax,
        raw={"description": description},
        ingested_at=_AT,
    )


def _bank(
    event_id: str, *, amount: int, utr: str | None = None, source: Source = "bank"
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t",
        source=source,
        source_row_id=event_id,
        amount_paise=amount,
        direction="credit",
        txn_date=date(2026, 6, 5),
        utr=utr,
        rail="neft" if utr else None,
        raw_narration=f"NEFT CR:{utr}/RZP" if utr else "SETTLEMENT CREDIT RAZORPAY",
        raw={},
        ingested_at=_AT,
    )


# gross 1,00,000 paise; MDR 2% = 2000 incl. 18% GST of 305 -> fee 2305, credit 97695.
def _one_payment_batch() -> list[TransactionEvent]:
    return [
        _gateway("p1", amount=97_695, txn_type="payment", fee=2_305, tax=305),
        _gateway("p2", amount=48_847, txn_type="payment", fee=1_153, tax=153),
    ]


def test_gross_is_the_credit_plus_the_fee_the_row_already_lost() -> None:
    sums = settlement_arithmetic(_SETL, _one_payment_batch())
    assert sums.gross_paise == 97_695 + 2_305 + 48_847 + 1_153
    assert sums.fee_paise == 3_458
    assert sums.n_txns == 2


def test_tax_is_inside_the_fee_and_is_not_subtracted_again() -> None:
    """``credit = amount - fee`` and ``fee`` already contains the GST."""
    sums = settlement_arithmetic(_SETL, _one_payment_batch())
    assert sums.gst_within_fee_paise == 458
    assert sums.expected_net_paise == 97_695 + 48_847
    # Subtracting tax separately would understate the net by the GST amount.
    assert sums.expected_net_paise != sums.gross_paise - sums.fee_paise - sums.gst_within_fee_paise


def test_tds_and_reserve_are_subtracted_and_a_release_is_added_back() -> None:
    rows = [
        *_one_payment_batch(),
        _gateway(
            "tds", amount=1_500, txn_type="adjustment", direction="debit", description="TDS 194-O"
        ),
        _gateway(
            "res",
            amount=7_400,
            txn_type="adjustment",
            direction="debit",
            description="rolling reserve hold",
        ),
        _gateway("rel", amount=2_000, txn_type="adjustment", description="rolling reserve release"),
    ]
    sums = settlement_arithmetic(_SETL, rows)
    assert dict(sums.deductions) == {"TDS 194-O": 1_500, "rolling reserve hold": 7_400}
    assert dict(sums.additions) == {"rolling reserve release": 2_000}
    assert sums.expected_net_paise == 97_695 + 48_847 - 1_500 - 7_400 + 2_000


def test_a_reconciling_credit_matches_and_anchors_only_itself() -> None:
    rows = _one_payment_batch()
    credit = _bank("b", amount=146_542)
    output = find_matches([*rows, credit], unmatched=frozenset({"b"}), cfg=_cfg())
    assert len(output.matches) == 1
    match = output.matches[0]
    assert match.anchors == ("b",)
    assert set(match.event_ids) == {"b", "p1", "p2"}
    assert match.base_confidence == BASE_CONFIDENCE
    assert match.delta_paise == 0


def test_the_evidence_states_the_sum_and_names_the_base_as_a_judgement() -> None:
    rows = _one_payment_batch()
    output = find_matches(
        [*rows, _bank("b", amount=146_542)], unmatched=frozenset({"b"}), cfg=_cfg()
    )
    arithmetic = output.matches[0].arithmetic
    assert arithmetic is not None
    assert "gross" in arithmetic and "MDR incl." in arithmetic
    assert "vs bank credit" in arithmetic
    assert BASE_CONFIDENCE_RATIONALE in arithmetic


def test_a_credit_outside_tolerance_does_not_match() -> None:
    rows = _one_payment_batch()
    output = find_matches(
        [*rows, _bank("b", amount=146_542 + 5_000)], unmatched=frozenset({"b"}), cfg=_cfg()
    )
    assert output.matches == ()


def test_a_usable_reference_that_disagrees_beats_the_arithmetic() -> None:
    """Scenario 9: a direct NEFT that happens to reconcile is not this batch."""
    rows = _one_payment_batch()
    stranger = _bank("b", amount=146_542, utr="ICIC261560000999")
    output = find_matches([*rows, stranger], unmatched=frozenset({"b"}), cfg=_cfg())
    assert output.matches == ()
    assert output.diagnostics["settlements_refused_on_contradicting_reference"] == 1


def test_a_credit_with_no_usable_reference_is_still_rescued() -> None:
    """Scenario 2: the UTR never reached the bank narration."""
    rows = _one_payment_batch()
    output = find_matches(
        [*rows, _bank("b", amount=146_542)], unmatched=frozenset({"b"}), cfg=_cfg()
    )
    assert len(output.matches) == 1


def test_two_settlements_reconciling_to_one_credit_produce_no_match() -> None:
    other = "setl_01KT07NVJQA6ZY8PZXVWK97FJB"
    rows = [
        *_one_payment_batch(),
        _gateway(
            "q1",
            amount=97_695,
            txn_type="payment",
            fee=2_305,
            tax=305,
            settlement_id=other,
            utr=None,
        ),
        _gateway(
            "q2",
            amount=48_847,
            txn_type="payment",
            fee=1_153,
            tax=153,
            settlement_id=other,
            utr=None,
        ),
    ]
    output = find_matches(
        [*rows, _bank("b", amount=146_542)], unmatched=frozenset({"b"}), cfg=_cfg()
    )
    assert output.matches == ()
    # The refusal names everything it declined to decide, not just the credit:
    # both candidate settlements are part of the question, and a refusal listing
    # only the bank row would leave their rows looking untouched by it.
    assert set(output.abstained) == {"b", "p1", "p2", "q1", "q2"}


def test_an_already_matched_credit_is_not_reconsidered() -> None:
    rows = _one_payment_batch()
    output = find_matches([*rows, _bank("b", amount=146_542)], unmatched=frozenset(), cfg=_cfg())
    assert output.matches == ()


def test_the_reported_tolerance_binding_term_is_recorded() -> None:
    rows = _one_payment_batch()
    output = find_matches(
        [*rows, _bank("b", amount=146_542)], unmatched=frozenset({"b"}), cfg=_cfg()
    )
    assert any(k.startswith("tolerance_binding_") for k in output.diagnostics)


def test_base_confidence_matches_the_prd_table() -> None:
    assert BASE_CONFIDENCE == Decimal("0.97")
