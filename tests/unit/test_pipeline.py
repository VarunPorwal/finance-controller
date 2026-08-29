"""The Rulebook gap-builders in :mod:`fc.pipeline` — three separate questions.

Batch payout (marketplace), per-transaction MDR (own-store), and batch TDS
194-O (own-store) are three different gaps on purpose (see
``_all_rule_gaps``'s docstring). These tests build one own-store settlement
and one marketplace settlement side by side and check each builder answers
only the question it owns — in particular, that TDS is never verified twice
for the same settlement (once via the marketplace commission rule, once via
the batch TDS rule), which is exactly the double-count the rule split had to
avoid.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fc.config import load_config
from fc.models.transaction import Direction, Source, TransactionEvent
from fc.pipeline import (
    _own_store_tds_gaps,
    _per_transaction_mdr_gaps,
    _settlement_rule_gaps,
)
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules

_AT = datetime(2026, 8, 1, tzinfo=UTC)
_CFG = load_config(env_file=None, environ={})
_RULES = load_rules(DEFAULT_RULES_PATH, tenant_id="t_lumea", created_at=_AT).rules
_MDR_RULES = tuple(r for r in _RULES if r.rule_id.startswith("razorpay_mdr_"))
_TDS_RULES = tuple(r for r in _RULES if r.rule_id == "razorpay_tds_batch")

# Own-store: one card order, gross 1,00,000. MDR 2% = 2,000; GST on that MDR
# 18% = 360; fee_paise = 2,360. TDS 194-O on the 1,00,000 gross = 1,000.
_OWN_ORDER_GROSS = 100_000
_OWN_MDR = 2_000
_OWN_GST_ON_MDR = 360
_OWN_FEE = _OWN_MDR + _OWN_GST_ON_MDR
_OWN_TDS = 1_000
_OWN_NET_CREDIT = _OWN_ORDER_GROSS - _OWN_FEE - _OWN_TDS

# Marketplace (Blinkit): one order, gross 2,00,000. Commission 18% = 36,000;
# GST on commission 18% = 6,480; fee_paise = 42,480. TDS on the 2,00,000
# gross = 2,000 — already inside blinkit_commission's own stack.
_MKT_ORDER_GROSS = 200_000
_MKT_COMMISSION = 36_000
_MKT_GST_ON_COMMISSION = 6_480
_MKT_FEE = _MKT_COMMISSION + _MKT_GST_ON_COMMISSION
_MKT_TDS = 2_000
_MKT_NET_CREDIT = _MKT_ORDER_GROSS - _MKT_FEE - _MKT_TDS


def _event(
    event_id: str,
    *,
    source: Source,
    amount: int,
    direction: Direction = "credit",
    txn_type: str | None = None,
    method: str | None = None,
    settlement_id: str | None = None,
    order_id: str | None = None,
    voucher_type: str | None = None,
    counterparty_norm: str | None = None,
    narration: str | None = None,
    fee: int | None = None,
    tax: int | None = None,
    description: str | None = None,
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t",
        source=source,
        source_row_id=event_id,
        amount_paise=amount,
        direction=direction,
        txn_date=date(2026, 6, 10),
        txn_type=txn_type or ("payment" if source == "razorpay" else None),
        method=method,
        settlement_id=settlement_id,
        order_id=order_id,
        voucher_type=voucher_type,
        counterparty_norm=counterparty_norm,
        raw_narration=narration,
        fee_paise=fee,
        tax_paise=tax,
        raw={"description": description} if description else {},
        ingested_at=_AT,
    )


def _own_store_events() -> list[TransactionEvent]:
    payment = _event(
        "own_pay",
        source="razorpay",
        amount=_OWN_NET_CREDIT + _OWN_TDS,  # net of MDR fee only, before TDS
        method="card",
        settlement_id="setl_own",
        order_id="order_own1",
        fee=_OWN_FEE,
        tax=_OWN_GST_ON_MDR,
    )
    tds = _event(
        "own_tds",
        source="razorpay",
        amount=_OWN_TDS,
        direction="debit",
        txn_type="adjustment",
        settlement_id="setl_own",
        description="TDS 194-O settlement setl_own",
    )
    receipt = _event(
        "own_receipt",
        source="ledger",
        amount=_OWN_NET_CREDIT,
        voucher_type="Receipt",
        counterparty_norm="RAZORPAY",
        narration="Settlement credit setl_own 1 orders",
    )
    return [payment, tds, receipt]


def _marketplace_events() -> list[TransactionEvent]:
    payment = _event(
        "mkt_pay",
        source="razorpay",
        amount=_MKT_NET_CREDIT + _MKT_TDS,
        method="upi",  # marketplace collection always narrates as UPI
        settlement_id="setl_blinkit",
        order_id="order_mkt1",
        fee=_MKT_FEE,
        tax=_MKT_GST_ON_COMMISSION,
    )
    tds = _event(
        "mkt_tds",
        source="razorpay",
        amount=_MKT_TDS,
        direction="debit",
        txn_type="adjustment",
        settlement_id="setl_blinkit",
        description="TDS 194-O settlement setl_blinkit",
    )
    receipt = _event(
        "mkt_receipt",
        source="ledger",
        amount=_MKT_NET_CREDIT,
        voucher_type="Receipt",
        counterparty_norm="BLINKIT",
        narration="Settlement credit setl_blinkit 1 orders",
    )
    return [payment, tds, receipt]


def test_settlement_gaps_mark_marketplace_but_not_own_store_as_claimed() -> None:
    events = [*_own_store_events(), *_marketplace_events()]

    gaps, marketplace_settlement_ids = _settlement_rule_gaps(events, _RULES, cfg=_CFG, aliases=None)

    assert marketplace_settlement_ids == {"setl_blinkit"}
    own_gap = next(g for g in gaps if g.counterparty_norm == "RAZORPAY")
    mkt_gap = next(g for g in gaps if g.counterparty_norm == "BLINKIT")
    assert own_gap.outcome.considered == 0  # no batch-level rule covers own-store
    assert mkt_gap.outcome.considered > 0
    assert mkt_gap.outcome.outcome == "fully_explained"


def test_per_transaction_mdr_verifies_own_store_and_skips_marketplace() -> None:
    events = [*_own_store_events(), *_marketplace_events()]
    _, marketplace_settlement_ids = _settlement_rule_gaps(events, _RULES, cfg=_CFG, aliases=None)

    gaps = _per_transaction_mdr_gaps(
        events, _MDR_RULES, cfg=_CFG, aliases=None, skip_settlements=marketplace_settlement_ids
    )

    assert len(gaps) == 1  # only the own-store payment row
    (gap,) = gaps
    assert gap.event_ids == ("own_pay",)
    assert gap.outcome.outcome == "fully_explained"
    assert gap.outcome.residual_paise == 0


def test_per_transaction_mdr_catches_a_real_overcharge() -> None:
    """The check actually verifies something — it is not vacuously green."""
    overcharged_fee = _OWN_FEE + 1_000  # ₹10 more than the contracted 2% + GST
    overcharged = _event(
        "own_pay_bad",
        source="razorpay",
        amount=_OWN_ORDER_GROSS - overcharged_fee,
        method="card",
        settlement_id="setl_own2",
        order_id="order_own2",
        fee=overcharged_fee,
        tax=_OWN_GST_ON_MDR,
    )

    gaps = _per_transaction_mdr_gaps(
        [overcharged], _MDR_RULES, cfg=_CFG, aliases=None, skip_settlements=frozenset()
    )

    assert len(gaps) == 1
    (gap,) = gaps
    assert gap.outcome.outcome != "fully_explained"
    assert gap.outcome.residual_paise != 0


def test_own_store_tds_is_verified_once_and_marketplace_tds_is_not_checked_twice() -> None:
    """The double-count guard the rule split exists to prevent.

    Blinkit's settlement TDS is already verified inside blinkit_commission's
    own stack (see fc.eval / tests/eval/test_rules_corpus.py). If
    ``_own_store_tds_gaps`` also produced a gap for the marketplace
    settlement, that TDS would be checked twice.
    """
    events = [*_own_store_events(), *_marketplace_events()]
    _, marketplace_settlement_ids = _settlement_rule_gaps(events, _RULES, cfg=_CFG, aliases=None)
    assert marketplace_settlement_ids == {"setl_blinkit"}

    gaps = _own_store_tds_gaps(
        events, _TDS_RULES, cfg=_CFG, aliases=None, skip_settlements=marketplace_settlement_ids
    )

    assert len(gaps) == 1  # only the own-store settlement's TDS row
    (gap,) = gaps
    assert gap.event_ids == ("own_tds",)
    assert gap.outcome.outcome == "fully_explained"
    assert gap.outcome.residual_paise == 0
    assert not any(g.event_ids == ("mkt_tds",) for g in gaps)


def test_own_store_tds_catches_a_real_discrepancy() -> None:
    events = _own_store_events()
    events[1] = _event(
        "own_tds",
        source="razorpay",
        amount=_OWN_TDS + 500,  # deducted more than 1% of gross
        direction="debit",
        txn_type="adjustment",
        settlement_id="setl_own",
        description="TDS 194-O settlement setl_own",
    )

    gaps = _own_store_tds_gaps(
        events, _TDS_RULES, cfg=_CFG, aliases=None, skip_settlements=frozenset()
    )

    assert len(gaps) == 1
    (gap,) = gaps
    assert gap.outcome.outcome != "fully_explained"
    assert gap.outcome.residual_paise != 0
