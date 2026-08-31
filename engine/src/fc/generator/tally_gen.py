"""Tally Prime day book CSV generation — PRD §4.1.6, §4.1.8.

Sales vouchers at gross per order, a Receipt voucher per settlement, and the
deduction stack (Bank Charges / GST Input / TDS Receivable / Reserve
Receivable) booked as Journal vouchers against the same settlement — PRD
§4.1.7's ledger split. Amounts are Indian-grouped with the ``(-)`` negative
prefix Tally actually exports (CLAUDE.md gotcha), never a minus sign. The
order reference lives in ``narration``, never ``reference_number`` — three-way
matching reads it from there (see ``fc.ingest.tally`` module docstring).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from fc.generator.ground_truth import GTEntry
from fc.generator.scenarios import (
    Settlement,
    compute_totals,
    fiscal_year_label,
    to_tally_amount_str,
)

__all__ = ["build"]

FIELDS = (
    "voucher_date",
    "voucher_type",
    "voucher_number",
    "ledger_name",
    "party_ledger_name",
    "debit",
    "credit",
    "narration",
    "reference_number",
    "cost_centre",
    "gstin",
    "voucher_guid",
)


def _csv_field(value: str) -> str:
    if any(c in value for c in (",", '"', "\n")):
        return '"' + value.replace('"', '""') + '"'
    return value


def build(
    settlements: list[Settlement], issue_id: Callable[[str], str]
) -> tuple[str, list[GTEntry]]:
    seq = {"Sales": 0, "Receipt": 0, "Journal": 0, "Credit Note": 0}
    lines = [",".join(FIELDS)]
    gt: list[GTEntry] = []

    def emit(
        *,
        d: date,
        voucher_type: str,
        ledger_name: str,
        party: str,
        debit_paise: int,
        credit_paise: int,
        narration: str,
        gt_group: str,
        gt_label: str | None,
        bucket: str,
        scenario: int | None,
    ) -> None:
        seq[voucher_type] = seq.get(voucher_type, 0) + 1
        fy = fiscal_year_label(d)
        codes = {"Sales": "SAL", "Receipt": "RCP", "Journal": "JNL", "Credit Note": "CN"}
        code = codes[voucher_type]
        voucher_number = f"{code}/{fy}/{seq[voucher_type]:05d}"
        guid = issue_id("")
        row = [
            d.isoformat(),
            voucher_type,
            voucher_number,
            ledger_name,
            party,
            to_tally_amount_str(debit_paise) if debit_paise else "",
            to_tally_amount_str(credit_paise) if credit_paise else "",
            narration,
            "",
            "Own Store" if party != "" else "",
            "",
            guid,
        ]
        lines.append(",".join(_csv_field(f) for f in row))
        gt.append(
            GTEntry(
                source="ledger",
                key=guid,
                gt_match_group=gt_group,
                gt_label=gt_label,
                bucket=bucket,
                scenario=scenario,
            )
        )

    for settlement in settlements:
        # Scenario 21: the bank never credited this settlement, so there is no
        # receipt for the books to record. Razorpay alone claims it, which is
        # what leaves the gateway row unmatched and files it missing_in_bank.
        if settlement.skip_bank_row:
            continue
        counterparty = (
            "RAZORPAY" if settlement.channel == "own_store" else (settlement.platform or "").upper()
        )

        for order in settlement.orders:
            if not order.is_refund_only:
                # Same settlement-wide-vs-order-level fallback as razorpay_gen: a
                # narration/rate scenario marks the whole settlement an exception,
                # not the individual order, so the Sales voucher must inherit it
                # too rather than defaulting to "matched".
                sales_bucket = order.gt_bucket if order.gt_label else settlement.gt_bucket
                sales_label = order.gt_label or (
                    settlement.gt_label if sales_bucket == "exception" else None
                )
                emit(
                    d=order.order_date,
                    voucher_type="Sales",
                    ledger_name="Sales",
                    party="",
                    debit_paise=0,
                    credit_paise=order.amount_paise,
                    narration=(
                        f"Sales order {order.order_id}"
                        if order.ledger_reference_visible
                        else f"Sales invoice dated {order.order_date.isoformat()}"
                    ),
                    gt_group=order.gt_group,
                    gt_label=sales_label,
                    bucket=sales_bucket,
                    scenario=settlement.scenario,
                )

            if order.refund_paise:
                is_scenario_13 = settlement.scenario == 13
                emit(
                    d=settlement.settle_date,
                    voucher_type="Credit Note",
                    ledger_name="Sales Return",
                    party="",
                    debit_paise=order.refund_paise,
                    credit_paise=0,
                    narration=f"Refund order {order.order_id}",
                    gt_group=order.gt_group,
                    gt_label="partial_refund" if is_scenario_13 else None,
                    bucket="exception" if is_scenario_13 else "matched",
                    scenario=settlement.scenario,
                )

            # Scenarios 6 and 20 are both chargebacks the ledger never
            # recorded; 20 additionally carries no dispute id to contest with.
            if order.dispute_paise and settlement.scenario not in (6, 20):
                emit(
                    d=settlement.settle_date,
                    voucher_type="Journal",
                    ledger_name="Disputes",
                    party="",
                    debit_paise=order.dispute_paise,
                    credit_paise=0,
                    narration=f"Chargeback order {order.order_id}",
                    gt_group=order.gt_group,
                    gt_label=None,
                    bucket="matched",
                    scenario=settlement.scenario,
                )
            # scenario 6: the chargeback is deliberately never booked here.

        if settlement.on_hold:
            continue  # cash side isn't booked until the hold releases

        totals = compute_totals(settlement)
        if totals.net_credit_paise <= 0:
            continue

        bucket = settlement.gt_bucket
        label = settlement.gt_label if bucket == "exception" else None
        n_orders = len(settlement.orders)
        receipt_narration = f"Settlement credit {settlement.settlement_id} {n_orders} orders"

        emit(
            d=settlement.settle_date,
            voucher_type="Receipt",
            ledger_name="HDFC Bank 4471",
            party=counterparty,
            debit_paise=totals.net_credit_paise,
            credit_paise=0,
            narration=receipt_narration,
            gt_group=settlement.settlement_id,
            gt_label=label,
            bucket=bucket,
            scenario=settlement.scenario,
        )

        if settlement.duplicate_voucher:
            emit(
                d=settlement.settle_date,
                voucher_type="Receipt",
                ledger_name="HDFC Bank 4471",
                party=counterparty,
                debit_paise=totals.net_credit_paise,
                credit_paise=0,
                narration=receipt_narration,
                gt_group=settlement.settlement_id,
                gt_label="duplicate_ledger_entry",
                bucket="exception",
                scenario=5,
            )

        if totals.mdr_base_paise:
            if settlement.scenario == 11:
                # Demonstrates the (-) prefix / Indian grouping parse path on a
                # real entry: a negative credit nets to the same debit amount.
                emit(
                    d=settlement.settle_date,
                    voucher_type="Journal",
                    ledger_name="Bank Charges",
                    party=counterparty,
                    debit_paise=0,
                    credit_paise=-totals.mdr_base_paise,
                    narration=f"MDR on settlement {settlement.settlement_id}",
                    gt_group=settlement.settlement_id,
                    gt_label=label,
                    bucket=bucket,
                    scenario=settlement.scenario,
                )
            else:
                emit(
                    d=settlement.settle_date,
                    voucher_type="Journal",
                    ledger_name="Bank Charges",
                    party=counterparty,
                    debit_paise=totals.mdr_base_paise,
                    credit_paise=0,
                    narration=f"MDR on settlement {settlement.settlement_id}",
                    gt_group=settlement.settlement_id,
                    gt_label=label,
                    bucket=bucket,
                    scenario=settlement.scenario,
                )

        if totals.gst_paise:
            emit(
                d=settlement.settle_date,
                voucher_type="Journal",
                ledger_name="GST Input",
                party=counterparty,
                debit_paise=totals.gst_paise,
                credit_paise=0,
                narration=f"GST on MDR settlement {settlement.settlement_id}",
                gt_group=settlement.settlement_id,
                gt_label=label,
                bucket=bucket,
                scenario=settlement.scenario,
            )

        if totals.tds_paise:
            emit(
                d=settlement.settle_date,
                voucher_type="Journal",
                ledger_name="TDS Receivable",
                party=counterparty,
                debit_paise=totals.tds_paise,
                credit_paise=0,
                narration=f"TDS 194-O settlement {settlement.settlement_id}",
                gt_group=settlement.settlement_id,
                gt_label=label,
                bucket=bucket,
                scenario=settlement.scenario,
            )

        if totals.reserve_paise:
            emit(
                d=settlement.settle_date,
                voucher_type="Journal",
                ledger_name="Reserve Receivable",
                party=counterparty,
                debit_paise=totals.reserve_paise,
                credit_paise=0,
                narration=f"Rolling reserve hold settlement {settlement.settlement_id}",
                gt_group=settlement.settlement_id,
                gt_label=None,
                bucket="rule_resolved" if settlement.scenario == 14 else bucket,
                scenario=settlement.scenario,
            )

        if settlement.reserve_release_paise:
            emit(
                d=settlement.settle_date,
                voucher_type="Journal",
                ledger_name="Reserve Receivable",
                party=counterparty,
                debit_paise=0,
                credit_paise=settlement.reserve_release_paise,
                narration=(
                    f"Rolling reserve release settlement {settlement.settlement_id} "
                    f"for {settlement.reserve_release_of}"
                ),
                gt_group=settlement.settlement_id,
                gt_label=None,
                bucket="matched",
                scenario=settlement.scenario,
            )

    return "\n".join(lines) + "\n", gt
