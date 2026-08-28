from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from fc.ingest.razorpay import parse_razorpay_recon
from fc.models.ids import deterministic_factory

INGESTED_AT = datetime(2026, 8, 28, 6, 0, tzinfo=UTC)


def _issue_id() -> Callable[[str], str]:
    return deterministic_factory(seed=42, epoch_ms=1_756_339_200_000)


def _payment_row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "entity_id": "pay_DEXrnipqTmWVGE",
        "type": "payment",
        "debit": 0,
        "credit": 97100,
        "amount": 100000,
        "currency": "INR",
        "fee": 2900,
        "tax": 522,
        "on_hold": False,
        "settled": True,
        "created_at": 1_692_000_000,
        "settled_at": 1_692_100_000,
        "settlement_id": "setl_DGlQ1Rj8os78Ec",
        "posted_at": 1_692_100_100,
        "credit_type": "default",
        "description": None,
        "notes": {"order_ref": "LUM-4471"},
        "payment_id": "pay_DEXrnipqTmWVGE",
        "settlement_utr": "1568176960vxp0rj",
        "order_id": "order_DEXrnRiR3SNDHA",
        "order_receipt": None,
        "method": "upi",
        "card_network": None,
        "card_issuer": None,
        "card_type": None,
        "dispute_id": None,
    }
    return base | overrides


def test_payment_amount_is_already_paise_not_reconverted() -> None:
    result = parse_razorpay_recon(
        [_payment_row()],
        run_id="run_1",
        tenant_id="t_lumea",
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert len(result.rejections) == 0
    event = result.events[0]
    assert event.amount_paise == 97100
    assert event.direction == "credit"
    assert event.source == "razorpay"
    assert event.source_row_id == "pay_DEXrnipqTmWVGE"


def test_refund_row_is_a_debit() -> None:
    refund = _payment_row(
        entity_id="rfnd_DEXrnabcd1234",
        type="refund",
        credit_type="refund",
        debit=50000,
        credit=0,
        payment_id="pay_DEXrnipqTmWVGE",
    )
    result = parse_razorpay_recon(
        [refund], run_id="run_1", tenant_id="t_lumea", issue_id=_issue_id(), ingested_at=INGESTED_AT
    )
    assert len(result.rejections) == 0
    event = result.events[0]
    assert event.direction == "debit"
    assert event.amount_paise == 50000
    assert event.txn_type == "refund"


def test_id_prefixes_are_all_accepted() -> None:
    prefixes = ("pay_", "order_", "rfnd_", "setl_", "setlod_", "dp_")
    rows = [
        _payment_row(entity_id=f"{prefix}abc123", payment_id=f"{prefix}abc123")
        for prefix in prefixes
    ]
    result = parse_razorpay_recon(
        rows, run_id="run_1", tenant_id="t_lumea", issue_id=_issue_id(), ingested_at=INGESTED_AT
    )
    assert len(result.rejections) == 0
    assert len(result.events) == len(prefixes)


def test_unrecognised_entity_id_prefix_is_rejected_and_logged() -> None:
    bad = _payment_row(entity_id="xyz_notarazorpayid")
    result = parse_razorpay_recon(
        [bad], run_id="run_1", tenant_id="t_lumea", issue_id=_issue_id(), ingested_at=INGESTED_AT
    )
    assert len(result.events) == 0
    assert len(result.rejections) == 1
    assert "prefix" in result.rejections[0].reason


def test_schema_violation_is_a_typed_rejection() -> None:
    bad = _payment_row(method="bitcoin")  # not a valid RazorpayMethod
    result = parse_razorpay_recon(
        [bad], run_id="run_1", tenant_id="t_lumea", issue_id=_issue_id(), ingested_at=INGESTED_AT
    )
    assert len(result.events) == 0
    assert len(result.rejections) == 1
    assert result.rejections[0].fields[0].field == "method"


def test_unix_timestamps_convert_to_utc() -> None:
    result = parse_razorpay_recon(
        [_payment_row()],
        run_id="run_1",
        tenant_id="t_lumea",
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    event = result.events[0]
    assert event.txn_date == datetime.fromtimestamp(1_692_000_000, tz=UTC).date()
    assert event.settled_at == datetime.fromtimestamp(1_692_100_000, tz=UTC)


def test_repeated_parse_is_deterministic() -> None:
    issue_id = deterministic_factory(seed=42, epoch_ms=1_756_339_200_000)
    first = parse_razorpay_recon(
        [_payment_row()],
        run_id="run_1",
        tenant_id="t_lumea",
        issue_id=issue_id,
        ingested_at=INGESTED_AT,
    )
    issue_id_again = deterministic_factory(seed=42, epoch_ms=1_756_339_200_000)
    second = parse_razorpay_recon(
        [_payment_row()],
        run_id="run_1",
        tenant_id="t_lumea",
        issue_id=issue_id_again,
        ingested_at=INGESTED_AT,
    )
    assert first.events[0].event_id == second.events[0].event_id
    assert first.events[0].source_row_id == second.events[0].source_row_id
