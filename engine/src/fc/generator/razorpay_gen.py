"""Razorpay settlement recon report generation — PRD §4.1.1, §4.1.2, §4.1.8.

Emits rows shaped exactly like :class:`fc.ingest.razorpay.RazorpayReconRow`
(``extra="forbid"``, so nothing beyond that field set may appear). Fee and
GST-on-fee are computed per transaction and rounded to paise before summing,
never on the batch total — that per-transaction rounding is what produces the
scenario 7 drift; nothing else needs to fake it (CLAUDE.md ingestion note).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from fc.generator.ground_truth import GTEntry
from fc.generator.scenarios import Settlement, compute_totals, effective_rate, fee_and_tax

__all__ = ["build"]


def _unix(dt_or_date: date | datetime) -> int:
    if isinstance(dt_or_date, datetime):
        return int(dt_or_date.timestamp())
    noon = datetime(dt_or_date.year, dt_or_date.month, dt_or_date.day, 12, tzinfo=UTC)
    return int(noon.timestamp())


def build(
    settlements: list[Settlement],
    issue_id: Callable[[str], str],
    utr_by_settlement: dict[str, str],
) -> tuple[list[dict[str, Any]], list[GTEntry]]:
    rows: list[dict[str, Any]] = []
    gt: list[GTEntry] = []

    for settlement in settlements:
        settlement_utr = utr_by_settlement[settlement.settlement_id]
        settled = not settlement.on_hold

        for order in settlement.orders:
            if not order.payment_id:
                order.payment_id = issue_id("pay_")

            if not order.is_refund_only:
                rate = effective_rate(settlement, order)
                fee, tax = fee_and_tax(order.amount_paise, rate)
                entity_id = issue_id("pay_")
                row = {
                    "entity_id": entity_id,
                    "type": "payment",
                    "debit": 0,
                    "credit": order.amount_paise - fee,
                    "amount": order.amount_paise,
                    "currency": "INR",
                    "fee": fee,
                    "tax": tax,
                    "on_hold": settlement.on_hold,
                    "settled": settled,
                    "created_at": _unix(order.order_date),
                    "settled_at": _unix(settlement.settle_date) if settled else None,
                    "settlement_id": settlement.settlement_id,
                    "posted_at": None if settlement.on_hold else _unix(settlement.value_date),
                    "credit_type": "default",
                    "description": None,
                    "notes": None,
                    "payment_id": order.payment_id,
                    "settlement_utr": settlement_utr,
                    "order_id": order.order_id,
                    "order_receipt": order.order_id,
                    "method": order.method if settlement.channel == "own_store" else "upi",
                    "card_network": "Visa" if order.method == "card" else None,
                    "card_issuer": "HDFC" if order.method == "card" else None,
                    "card_type": "credit" if order.method == "card" else None,
                    "dispute_id": None,
                }
                rows.append(row)
                bucket = order.gt_bucket if order.gt_label else _bucket_for(settlement)
                # An order rarely carries its own label (scenario 16's pair does); a
                # settlement-wide exception (truncated/unparseable/transposed narration,
                # a rate mismatch, an on-hold batch) sets only settlement.gt_label, so
                # every member row must inherit it or the category confusion matrix
                # can't score it.
                label = order.gt_label or (settlement.gt_label if bucket == "exception" else None)
                gt.append(
                    GTEntry(
                        source="razorpay",
                        key=entity_id,
                        gt_match_group=order.gt_group,
                        gt_label=label,
                        bucket=bucket,
                        scenario=settlement.scenario,
                    )
                )

            if order.refund_paise:
                rfnd_id = issue_id("rfnd_")
                rows.append(
                    {
                        "entity_id": rfnd_id,
                        "type": "refund",
                        "debit": order.refund_paise,
                        "credit": 0,
                        "amount": order.refund_paise,
                        "currency": "INR",
                        "fee": 0,
                        "tax": 0,
                        "on_hold": False,
                        "settled": True,
                        "created_at": _unix(settlement.settle_date),
                        "settled_at": _unix(settlement.settle_date),
                        "settlement_id": settlement.settlement_id,
                        "posted_at": _unix(settlement.value_date),
                        "credit_type": "refund",
                        "description": None,
                        "notes": None,
                        "payment_id": order.payment_id,
                        "settlement_utr": settlement_utr,
                        "order_id": order.order_id,
                        "order_receipt": order.order_id,
                        "method": order.method if settlement.channel == "own_store" else "upi",
                        "card_network": None,
                        "card_issuer": None,
                        "card_type": None,
                        "dispute_id": None,
                    }
                )
                gt.append(
                    GTEntry(
                        source="razorpay",
                        key=rfnd_id,
                        gt_match_group=order.gt_group,
                        gt_label="partial_refund" if settlement.scenario == 13 else None,
                        bucket="exception" if settlement.scenario == 13 else "matched",
                        scenario=settlement.scenario,
                    )
                )

            if order.dispute_paise:
                dp_id = issue_id("dp_")
                rows.append(
                    {
                        "entity_id": dp_id,
                        "type": "dispute",
                        "debit": order.dispute_paise,
                        "credit": 0,
                        "amount": order.dispute_paise,
                        "currency": "INR",
                        "fee": 0,
                        "tax": 0,
                        "on_hold": False,
                        "settled": True,
                        "created_at": _unix(settlement.settle_date),
                        "settled_at": _unix(settlement.settle_date),
                        "settlement_id": settlement.settlement_id,
                        "posted_at": _unix(settlement.value_date),
                        "credit_type": "dispute",
                        "description": "chargeback",
                        "notes": None,
                        "payment_id": order.payment_id,
                        "settlement_utr": settlement_utr,
                        "order_id": order.order_id,
                        "order_receipt": order.order_id,
                        "method": order.method if settlement.channel == "own_store" else "upi",
                        "card_network": None,
                        "card_issuer": None,
                        "card_type": None,
                        # Scenario 20: the debit landed before the dispute
                        # record was raised, so there is no reference to
                        # contest it with. classify.py already falls back to
                        # the event id when narrating this.
                        "dispute_id": dp_id if order.dispute_reference_visible else None,
                    }
                )
                gt.append(
                    GTEntry(
                        source="razorpay",
                        key=dp_id,
                        gt_match_group=order.gt_group,
                        gt_label="chargeback_unrecorded" if settlement.scenario == 6 else None,
                        bucket="exception" if settlement.scenario == 6 else "matched",
                        scenario=settlement.scenario,
                    )
                )

        # Batch-level adjustments: TDS, rolling reserve hold, reserve release.
        totals = compute_totals(settlement)
        if totals.tds_paise:
            adj_id = issue_id("setlod_")
            rows.append(
                _adjustment_row(adj_id, settlement, totals.tds_paise, "TDS 194-O", settlement_utr)
            )
            gt.append(_clean_gt("razorpay", adj_id, settlement))

        if totals.reserve_paise:
            adj_id = issue_id("setlod_")
            rows.append(
                _adjustment_row(
                    adj_id, settlement, totals.reserve_paise, "rolling reserve hold", settlement_utr
                )
            )
            gt.append(
                GTEntry(
                    source="razorpay",
                    key=adj_id,
                    gt_match_group=settlement.settlement_id,
                    gt_label=None,
                    bucket="rule_resolved" if settlement.scenario == 14 else "matched",
                    scenario=settlement.scenario,
                )
            )

        if settlement.reserve_release_paise:
            rel_id = issue_id("setlod_")
            rows.append(
                {
                    "entity_id": rel_id,
                    "type": "adjustment",
                    "debit": 0,
                    "credit": settlement.reserve_release_paise,
                    "amount": settlement.reserve_release_paise,
                    "currency": "INR",
                    "fee": 0,
                    "tax": 0,
                    "on_hold": False,
                    "settled": True,
                    "created_at": _unix(settlement.settle_date),
                    "settled_at": _unix(settlement.settle_date),
                    "settlement_id": settlement.settlement_id,
                    "posted_at": _unix(settlement.value_date),
                    "credit_type": "default",
                    "description": f"rolling reserve release for {settlement.reserve_release_of}",
                    "notes": None,
                    "payment_id": None,
                    "settlement_utr": settlement_utr,
                    "order_id": None,
                    "order_receipt": None,
                    "method": None,
                    "card_network": None,
                    "card_issuer": None,
                    "card_type": None,
                    "dispute_id": None,
                }
            )
            gt.append(_clean_gt("razorpay", rel_id, settlement))

    return rows, gt


def _adjustment_row(
    entity_id: str, settlement: Settlement, amount_paise: int, description: str, settlement_utr: str
) -> dict[str, Any]:
    return {
        "entity_id": entity_id,
        "type": "adjustment",
        "debit": amount_paise,
        "credit": 0,
        "amount": amount_paise,
        "currency": "INR",
        "fee": 0,
        "tax": 0,
        "on_hold": False,
        "settled": True,
        "created_at": _unix(settlement.settle_date),
        "settled_at": _unix(settlement.settle_date),
        "settlement_id": settlement.settlement_id,
        "posted_at": _unix(settlement.value_date),
        "credit_type": "default",
        "description": description,
        "notes": None,
        "payment_id": None,
        "settlement_utr": settlement_utr,
        "order_id": None,
        "order_receipt": None,
        "method": None,
        "card_network": None,
        "card_issuer": None,
        "card_type": None,
        "dispute_id": None,
    }


def _clean_gt(source: str, key: str, settlement: Settlement) -> GTEntry:
    return GTEntry(
        source=source,
        key=key,
        gt_match_group=settlement.settlement_id,
        gt_label=None,
        bucket="matched",
        scenario=settlement.scenario,
    )


def _bucket_for(settlement: Settlement) -> str:
    return settlement.gt_bucket
