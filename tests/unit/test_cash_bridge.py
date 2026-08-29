"""The reconciliation bridge — PRD §6.8.7 / §13.4.

The one invariant that matters more than any single figure: the segments sum
exactly to the difference between gross and actual.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from fc.cash.bridge import compute_cash_bridge
from fc.models.exception_ import Exception_
from fc.models.transaction import Direction, Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)


def _event(
    event_id: str,
    *,
    source: Source,
    amount: int,
    direction: Direction = "credit",
    txn_type: str | None = None,
    fee: int | None = None,
    tax: int | None = None,
    description: str | None = None,
) -> TransactionEvent:
    raw: dict[str, object] = {"description": description} if description else {}
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t",
        source=source,
        source_row_id=event_id,
        amount_paise=amount,
        direction=direction,
        txn_date=date(2026, 8, 1),
        txn_type=txn_type or ("payment" if source == "razorpay" else None),
        fee_paise=fee,
        tax_paise=tax,
        raw=raw,
        ingested_at=_AT,
    )


def _exception(
    exception_id: str, *, category: str = "amount_variance", tier: str = "escalate"
) -> Exception_:
    return Exception_(
        exception_id=exception_id,
        run_id="run",
        tenant_id="t",
        event_ids=["e"],
        category=category,  # type: ignore[arg-type]
        amount_paise=100,
        residual_paise=100,
        confidence=Decimal("0.5"),
        tier=tier,  # type: ignore[arg-type]
        priority_score=Decimal("0.5"),
        recommended_action="do something",
        signature="sig",
        created_at=_AT,
    )


def test_a_clean_settlement_reconciles_to_zero_unexplained() -> None:
    # 100000 gross, 2% fee (2000, of which 18% GST = 360, so pure MDR 1640).
    payment = _event("pay", source="razorpay", amount=98_000, fee=2_000, tax=360)
    bank = _event("bank", source="bank", amount=98_000)

    bridge = compute_cash_bridge([payment, bank], [])

    assert bridge.gross_collected_paise == 100_000
    assert bridge.expected_net_paise == 98_000
    assert bridge.actual_bank_paise == 98_000
    assert bridge.unexplained_paise == 0


@pytest.mark.parametrize(
    "extra",
    [
        [],
        [_event("rfnd", source="razorpay", amount=5_000, direction="debit", txn_type="refund")],
        [_event("dp", source="razorpay", amount=3_000, direction="debit", txn_type="dispute")],
        [
            _event(
                "tds",
                source="razorpay",
                amount=1_000,
                direction="debit",
                txn_type="adjustment",
                description="TDS 194-O settlement setl_1",
            )
        ],
        [
            _event(
                "res",
                source="razorpay",
                amount=4_000,
                direction="debit",
                txn_type="adjustment",
                description="rolling reserve hold",
            )
        ],
    ],
)
def test_segments_always_sum_to_gross_minus_actual(extra: list[TransactionEvent]) -> None:
    payment = _event("pay", source="razorpay", amount=98_000, fee=2_000, tax=360)
    bank = _event("bank", source="bank", amount=90_000)
    events = [payment, bank, *extra]

    bridge = compute_cash_bridge(events, [])

    total = sum(segment.amount_paise for segment in bridge.segments)
    assert total == bridge.gross_collected_paise - bridge.actual_bank_paise


def test_a_reserve_release_reduces_the_net_reserve_deduction() -> None:
    payment = _event("pay", source="razorpay", amount=90_000, fee=0, tax=0)
    bank = _event("bank", source="bank", amount=95_000)  # includes a prior release
    hold = _event(
        "hold",
        source="razorpay",
        amount=5_000,
        direction="debit",
        txn_type="adjustment",
        description="rolling reserve hold",
    )
    release = _event(
        "release",
        source="razorpay",
        amount=5_000,
        direction="credit",
        txn_type="adjustment",
        description="rolling reserve release for setl_0",
    )

    bridge = compute_cash_bridge([payment, bank, hold, release], [])

    reserve_segment = next(s for s in bridge.deductions if s.label == "Rolling reserve")
    assert reserve_segment.amount_paise == 0


def test_chargeback_segment_links_its_exceptions() -> None:
    payment = _event("pay", source="razorpay", amount=95_000, fee=0, tax=0)
    dispute = _event("dp", source="razorpay", amount=5_000, direction="debit", txn_type="dispute")
    bank = _event("bank", source="bank", amount=90_000)
    exc = _exception("exc_1", category="chargeback_unrecorded")

    bridge = compute_cash_bridge([payment, dispute, bank], [exc])

    chargeback_segment = next(s for s in bridge.deductions if s.label == "Chargebacks")
    assert chargeback_segment.exception_ids == ("exc_1",)


def test_unexplained_segment_links_unexplained_exceptions() -> None:
    payment = _event("pay", source="razorpay", amount=100_000, fee=0, tax=0)
    bank = _event("bank", source="bank", amount=90_000)
    exc = _exception("exc_2", category="missing_in_bank")
    unrelated = _exception("exc_3", category="partial_refund")

    bridge = compute_cash_bridge([payment, bank], [exc, unrelated])

    unexplained = bridge.segments[-1]
    assert unexplained.label == "Unexplained"
    assert unexplained.exception_ids == ("exc_2",)
