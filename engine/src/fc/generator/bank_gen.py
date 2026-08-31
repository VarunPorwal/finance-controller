"""HDFC NetBanking CSV generation — PRD §4.1.3, §4.1.4, §4.1.8.

One lumped NEFT credit per settlement (T+1/T+2 for direct, weekly for
marketplace), narration built to the HDFC pattern
(``fc.ingest.narration.hdfc``), with a running ``closing_balance`` that
actually reconciles (PRD §6.1: ``bal[n] == bal[n-1] + deposit[n] -
withdrawal[n]``).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from fc.generator.ground_truth import GTEntry
from fc.generator.scenarios import (
    OPENING_BALANCE_PAISE,
    Settlement,
    compute_totals,
    paise_to_rupee_str,
)

__all__ = ["StandaloneBankRow", "build"]

HEADER = "txn_date,value_date,narration,chq_ref_no,withdrawal_amt,deposit_amt,closing_balance"


@dataclass
class StandaloneBankRow:
    """A bank credit with no corresponding Razorpay/Tally row — scenarios 8, 9."""

    narration: str
    amount_paise: int
    txn_date: date
    scenario: int
    gt_label: str
    gt_group: str


def _fmt_date(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _swap_adjacent_digits(utr: str) -> str:
    chars = list(utr)
    for i in range(len(chars) - 1, 0, -1):
        if chars[i].isdigit() and chars[i - 1].isdigit() and chars[i] != chars[i - 1]:
            chars[i], chars[i - 1] = chars[i - 1], chars[i]
            return "".join(chars)
    return utr  # pragma: no cover — every generated UTR has two distinct adjacent digits


def _neft_narration(utr: str, party: str, ref: str, direction: str) -> str:
    marker = "CR" if direction == "credit" else "DR"
    return f"NEFT {marker}:{utr}/{party}/{ref}"


def _settlement_narration(settlement: Settlement, true_utr: str, direction: str) -> str:
    party = "RAZORPAY" if settlement.channel == "own_store" else (settlement.platform or "").upper()
    ref = settlement.settlement_id
    mode = settlement.narration_mode
    verb = "CREDIT" if direction == "credit" else "DEBIT"
    if mode == "unparseable":
        return f"SETTLEMENT {verb} RAZORPAY SOFTWARE PRIVATE LIMITED PAYMENT GATEWAY SERVICES {ref}"
    if mode == "short_utr":
        short = true_utr[:8]
        marker = "CR" if direction == "credit" else "DR"
        padding = (
            "RAZORPAY SOFTWARE PRIVATE LIMITED SETTLEMENT NARRATION FOR PERIODIC "
            "BATCH CREDIT COVERING MULTIPLE MERCHANT ORDER PAYMENTS PROCESSED VIA "
            "GATEWAY REFERENCE"
        )
        full = f"NEFT {marker}:{short}/{party} {padding}/{ref}"
        return full[:99]  # export truncated the line before the full reference
    if mode == "transposed":
        return _neft_narration(_swap_adjacent_digits(true_utr), party, ref, direction)
    return _neft_narration(true_utr, party, ref, direction)


def _bank_key(txn_date: date, amount_paise: int, narration: str, closing_balance_paise: int) -> str:
    parts = "|".join(
        str(v) for v in (txn_date.isoformat(), amount_paise, narration, closing_balance_paise)
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def build(
    settlements: list[Settlement],
    standalone: list[StandaloneBankRow],
    utr_by_settlement: dict[str, str],
) -> tuple[str, list[GTEntry]]:
    rows: list[dict[str, Any]] = []  # pre-balance rows, in emission order

    for settlement in settlements:
        if settlement.on_hold:
            continue
        # Scenario 21: Razorpay reported the settlement and the bank never
        # credited it. The field existed on Settlement and nothing read it, so
        # the only way a settlement could go missing was on_hold — which is a
        # different fact with a different narration and a different outcome.
        if settlement.skip_bank_row:
            continue
        totals = compute_totals(settlement)
        net = totals.net_credit_paise
        if net == 0:
            continue
        # A settlement can legitimately net negative — a dedicated refund
        # batch (scenario 4) with no offsetting payments in it, say — and
        # that still moves money: a withdrawal, not nothing. Dropping it
        # would silently erase a real Razorpay debit from the bank side.
        direction = "credit" if net > 0 else "debit"
        narration = _settlement_narration(
            settlement, utr_by_settlement[settlement.settlement_id], direction
        )
        rows.append(
            {
                "txn_date": settlement.settle_date,
                "value_date": settlement.value_date,
                "narration": narration,
                "amount_paise": abs(net),
                "direction": direction,
                "gt_group": settlement.settlement_id,
                "gt_label": settlement.gt_label if settlement.gt_bucket == "exception" else None,
                "bucket": settlement.gt_bucket,
                "scenario": settlement.scenario,
            }
        )

    for standalone_row in standalone:
        rows.append(
            {
                "txn_date": standalone_row.txn_date,
                "value_date": standalone_row.txn_date,
                "narration": standalone_row.narration,
                "amount_paise": standalone_row.amount_paise,
                "direction": "credit",
                "gt_group": standalone_row.gt_group,
                "gt_label": standalone_row.gt_label,
                "bucket": "exception",
                "scenario": standalone_row.scenario,
            }
        )

    rows.sort(key=lambda r: r["txn_date"])

    balance = OPENING_BALANCE_PAISE
    lines = [HEADER]
    gt: list[GTEntry] = []
    for row in rows:
        is_credit = row["direction"] == "credit"
        balance += row["amount_paise"] if is_credit else -row["amount_paise"]
        key = _bank_key(row["txn_date"], row["amount_paise"], row["narration"], balance)
        lines.append(
            ",".join(
                [
                    _fmt_date(row["txn_date"]),
                    _fmt_date(row["value_date"]),
                    row["narration"],
                    "0",
                    "" if is_credit else paise_to_rupee_str(row["amount_paise"]),
                    paise_to_rupee_str(row["amount_paise"]) if is_credit else "",
                    paise_to_rupee_str(balance),
                ]
            )
        )
        gt.append(
            GTEntry(
                source="bank",
                key=key,
                gt_match_group=row["gt_group"],
                gt_label=row["gt_label"],
                bucket=row["bucket"],
                scenario=row["scenario"],
            )
        )

    return "\n".join(lines) + "\n", gt
