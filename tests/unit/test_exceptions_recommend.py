"""Recommendation templates — PRD §6.8.5. Specific actions, never labels."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fc.exceptions.classify import Classified
from fc.exceptions.recommend import recommended_action
from fc.models.transaction import Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)


def _event(event_id: str, *, source: Source, amount: int, **kwargs: object) -> TransactionEvent:
    defaults: dict[str, object] = {
        "run_id": "run",
        "tenant_id": "t",
        "source": source,
        "source_row_id": event_id,
        "amount_paise": amount,
        "direction": "credit",
        "txn_date": date(2026, 6, 5),
        "raw": {},
        "ingested_at": _AT,
    }
    defaults.update(kwargs)
    return TransactionEvent(event_id=event_id, **defaults)  # type: ignore[arg-type]


def _classified(category: str, event_ids: tuple[str, ...], **kwargs: object) -> Classified:
    fields: dict[str, object] = {
        "amount_paise": 10_000,
        "residual_paise": 10_000,
        "reason": "test",
        "confidence": Decimal("0.9"),
        "gross_paise": 10_000,
        "gap_paise": 10_000,
    }
    fields.update(kwargs)
    return Classified(event_ids=event_ids, category=category, **fields)  # type: ignore[arg-type]


def test_duplicate_ledger_entry_names_both_vouchers() -> None:
    keep = _event(
        "keep",
        source="ledger",
        amount=10_000,
        voucher_type="Receipt",
        voucher_number="RCPT-1",
        order_id="order_1",
    )
    reverse = _event(
        "reverse",
        source="ledger",
        amount=10_000,
        voucher_type="Receipt",
        voucher_number="RCPT-2",
        order_id="order_1",
    )
    classified = _classified("duplicate_ledger_entry", ("keep", "reverse"))

    text = recommended_action(
        classified, events_by_id={"keep": keep, "reverse": reverse}, deadline=None
    )

    assert "Reverse voucher" in text
    assert "RCPT-2" in text
    assert "RCPT-1" in text
    assert "order_1" in text


def test_chargeback_unrecorded_names_the_dispute_and_the_deadline() -> None:
    event = _event(
        "dp",
        source="razorpay",
        amount=50_000,
        txn_type="dispute",
        order_id="order_X",
        raw={"dispute_id": "dp_X"},
    )
    classified = _classified("chargeback_unrecorded", ("dp",))

    text = recommended_action(classified, events_by_id={"dp": event}, deadline=date(2026, 9, 15))

    assert "dp_X" in text
    assert "order_X" in text
    assert "2026-09-15" in text
    assert "Disputes" in text


def test_missing_in_bank_names_the_utr_and_the_sla() -> None:
    event = _event(
        "pay",
        source="razorpay",
        amount=10_000,
        txn_type="payment",
        utr="HDFC1234",
        settled_at=_AT,
    )
    classified = _classified("missing_in_bank", ("pay",))

    text = recommended_action(classified, events_by_id={"pay": event}, deadline=date(2026, 8, 31))

    assert "HDFC1234" in text
    assert "2026-08-31" in text


def test_every_category_produces_a_non_empty_specific_sentence() -> None:
    """No category may fall through to an empty or label-only string."""
    event = _event("e", source="razorpay", amount=10_000)
    for category in (
        "missing_in_bank",
        "missing_in_gateway",
        "missing_in_ledger",
        "duplicate_ledger_entry",
        "chargeback_unrecorded",
        "partial_refund",
        "nach_batch_unexploded",
        "timing_lag",
        "ambiguous_multi_candidate",
        "reference_truncated",
        "amount_variance",
        "unknown",
    ):
        classified = _classified(category, ("e",))
        text = recommended_action(classified, events_by_id={"e": event}, deadline=None)
        assert text
        assert text.strip() != category
