"""Stage 1 joins on trusted references only, and never across an order's two sides.

Three invariants, each of which cost precision when it was missing:

* a truncated bank reference never enters the stage at all;
* an order id links a payment to its own voucher, not to its refund - the two
  settle in different batches and ground truth calls them different money;
* reference agreement is closed transitively, because one settlement is linked
  by several different references and no single key sees all of it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fc.config import load_config
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.matching.ledger_refs import index_ledger_refs
from fc.matching.stages import reference_is_truncated
from fc.matching.stages.exact_ref import find_matches, order_side, trusted_references
from fc.models.transaction import Direction, Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)
_ORDER = "order_01KT07NV33WV987DMTMF64Y936"
_SETL = "setl_01KT07NVH5KTVYN9PVWMBFQW16"
_UTR = "HDFC261560000000"


def _event(
    event_id: str,
    *,
    source: Source,
    amount: int = 1000,
    direction: Direction = "credit",
    utr: str | None = None,
    settlement_id: str | None = None,
    order_id: str | None = None,
    txn_type: str | None = None,
    voucher_type: str | None = None,
    narration: str | None = None,
    rail: str | None = None,
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t",
        source=source,
        source_row_id=event_id,
        amount_paise=amount,
        direction=direction,
        txn_date=date(2026, 6, 1),
        utr=utr,
        settlement_id=settlement_id,
        order_id=order_id,
        txn_type=txn_type,
        voucher_type=voucher_type,
        rail=rail,
        raw_narration=narration,
        raw={},
        ingested_at=_AT,
    )


#: Stage 1 balances a group that has a bank leg against the side that
#: claims to be the money, and that tolerance comes from config.
_CFG = load_config(env_file=None, environ={})


def _run(events: list[TransactionEvent]) -> list[tuple[str, ...]]:
    output = find_matches(events, ledger_refs=index_ledger_refs(events), cfg=_CFG)
    return sorted(m.event_ids for m in output.matches)


def test_a_gateway_row_and_a_bank_credit_join_on_utr() -> None:
    events = [
        _event("g", source="razorpay", utr=_UTR, settlement_id=_SETL),
        _event("b", source="bank", utr=_UTR, rail="neft", narration=f"NEFT CR:{_UTR}/RZP"),
    ]
    assert _run(events) == [("b", "g")]


def test_a_single_source_collision_is_not_a_match() -> None:
    """Two gateway rows sharing a settlement id are one batch, not two sides."""
    events = [
        _event("g1", source="razorpay", settlement_id=_SETL),
        _event("g2", source="razorpay", settlement_id=_SETL),
    ]
    assert _run(events) == []


def test_reference_agreement_closes_transitively_into_one_settlement_group() -> None:
    events = [
        _event("bank", source="bank", utr=_UTR, rail="neft", narration=f"NEFT CR:{_UTR}/RZP"),
        _event(
            "pay",
            source="razorpay",
            utr=_UTR,
            settlement_id=_SETL,
            order_id=_ORDER,
            txn_type="payment",
        ),
        _event("sales", source="ledger", voucher_type="Sales", narration=f"Sales order {_ORDER}"),
        _event(
            "rcpt", source="ledger", voucher_type="Receipt", narration=f"Settlement credit {_SETL}"
        ),
    ]
    assert _run(events) == [("bank", "pay", "rcpt", "sales")]


def test_a_truncated_bank_reference_never_enters_the_stage() -> None:
    narration = (
        "NEFT CR:HDFC2615/RAZORPAY RAZORPAY SOFTWARE PRIVATE LIMITED "
        "SETTLEMENT NARRATION FOR PERIODIC BATCH PADDING PADDING"
    )
    assert len(narration) >= 98
    bank = _event("b", source="bank", utr="HDFC2615", rail="neft", narration=narration)
    assert reference_is_truncated(bank) is True
    assert trusted_references(bank, index_ledger_refs([])) == ()

    gateway = _event("g", source="razorpay", utr="HDFC2615", settlement_id=_SETL)
    assert _run([bank, gateway]) == []


def test_a_full_length_reference_in_a_long_narration_is_still_trusted() -> None:
    narration = f"NEFT CR:{_UTR}/RAZORPAY SOFTWARE PRIVATE LIMITED " + "X" * 60
    assert len(narration) >= 98
    bank = _event("b", source="bank", utr=_UTR, rail="neft", narration=narration)
    assert reference_is_truncated(bank) is False


def test_a_nach_batch_reference_is_never_judged_truncated() -> None:
    narration = "NACH-BATCH01000-NPCI " + "X" * 90
    bank = _event("b", source="bank", rail="nach", narration=narration)
    assert reference_is_truncated(bank) is False


def test_an_order_id_does_not_join_a_payment_to_its_refund() -> None:
    """Scenario 4: the refund settles three days later, in another batch."""
    events = [
        _event("pay", source="razorpay", order_id=_ORDER, txn_type="payment"),
        _event("rfnd", source="razorpay", order_id=_ORDER, txn_type="refund", direction="debit"),
        _event("sales", source="ledger", voucher_type="Sales", narration=f"Sales order {_ORDER}"),
        _event(
            "cn", source="ledger", voucher_type="Credit Note", narration=f"Refund order {_ORDER}"
        ),
    ]
    groups = _run(events)
    assert groups == [("cn", "rfnd"), ("pay", "sales")]


def test_order_side_reads_gateway_type_and_ledger_voucher_type() -> None:
    assert order_side(_event("a", source="razorpay", txn_type="payment")) == "payment"
    assert order_side(_event("a", source="razorpay", txn_type="refund")) == "refund"
    assert order_side(_event("a", source="razorpay", txn_type="dispute")) == "refund"
    assert order_side(_event("a", source="ledger", voucher_type="Credit Note")) == "refund"
    assert order_side(_event("a", source="ledger", voucher_type="Sales")) == "payment"


def test_a_narration_naming_two_settlements_does_not_merge_them() -> None:
    other = "setl_01KT07NVJQA6ZY8PZXVWK97FJB"
    events = [
        _event("gA", source="razorpay", settlement_id=_SETL),
        _event("gB", source="razorpay", settlement_id=other),
        _event(
            "jnl",
            source="ledger",
            voucher_type="Journal",
            narration=f"Rolling reserve release settlement {other} for {_SETL}",
        ),
    ]
    assert _run(events) == []


def test_the_truncation_rule_agrees_with_the_ingest_parser() -> None:
    """The rail length table here duplicates ingest's; this is the drift guard."""
    parser = HdfcNarrationParser()
    narrations = [
        f"NEFT CR:{_UTR}/RAZORPAY",
        "NEFT CR:HDFC2615/RAZORPAY SOFTWARE PRIVATE LIMITED SETTLEMENT NARRATION BATCH " + "X" * 30,
        f"NEFT CR:{_UTR}/RAZORPAY SOFTWARE PRIVATE LIMITED " + "X" * 60,
        "UPI-MERCHANT-merchant@okhdfc-HDFC0001234-123456789012",
    ]
    for narration in narrations:
        parsed = parser.parse(narration)
        event = _event(
            "b",
            source="bank",
            rail=parsed.rail,
            utr=parsed.reference if parsed.rail in ("neft", "rtgs") else None,
            narration=narration,
        )
        event = event.model_copy(
            update={"rrn": parsed.reference if parsed.rail in ("imps", "upi") else None}
        )
        assert reference_is_truncated(event) == parsed.truncated, narration
