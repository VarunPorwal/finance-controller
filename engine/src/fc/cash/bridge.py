"""The reconciliation bridge — PRD §6.8.7 / §13.4.

::

    GROSS COLLECTED
      - MDR - GST on MDR - TDS 194-O - Refunds settled - Chargebacks
      - Rolling reserve
      = EXPECTED NET
           vs BANK CREDITED
           ─────────────────
           UNEXPLAINED

"The artifact a finance person draws by hand on paper" (§13.4), so every
figure here is read straight off the Razorpay recon report and the bank
statement — no rule engine, no LLM (CLAUDE.md hard rule 2, and this package
is one of ``test_architecture.py``'s four scanned decision modules), and every
amount is int paise, never float (hard rule 1, and this package is one of the
three money-arithmetic trees the AST scan covers).

Each segment carries the ``event_ids`` that make it up and, where the segment
overlaps something a human still needs to act on, the ``exception_ids`` that
explain it — so the bridge in the UI can be clicked straight into the queue.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fc.models.exception_ import Exception_
from fc.models.transaction import TransactionEvent

__all__ = ["BridgeSegment", "CashBridge", "compute_cash_bridge"]

#: Substrings ``fc.generator.razorpay_gen`` writes into a settlement-line-item
#: adjustment row's ``description`` (PRD §4.1.7). Matched here rather than
#: mapped onto its own ``TransactionEvent`` field because ``description`` was
#: never promoted off ``raw`` (CLAUDE.md: "if either side changes ... change
#: the other side in the same commit" — this is that other side, for now).
_TDS_MARKER = "TDS"
_RESERVE_RELEASE_MARKER = "reserve release"
_RESERVE_HOLD_MARKER = "reserve hold"

#: Categories a bridge reader would recognise as "the gap": nothing else in
#: the deduction stack already accounts for them.
_UNEXPLAINED_CATEGORIES = frozenset(
    {"missing_in_bank", "missing_in_gateway", "amount_variance", "unknown"}
)


@dataclass(frozen=True)
class BridgeSegment:
    """One row of the bridge: a label, an amount, and what proves it."""

    label: str
    amount_paise: int
    event_ids: tuple[str, ...]
    exception_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CashBridge:
    gross_collected_paise: int
    deductions: tuple[BridgeSegment, ...]
    expected_net_paise: int
    actual_bank_paise: int
    unexplained_paise: int
    #: Every deduction plus the terminal "Unexplained" line, in bridge order.
    segments: tuple[BridgeSegment, ...]
    cash_at_risk_paise: int
    reserve_pending_release_paise: int
    gst_input_credit_claimable_paise: int


def compute_cash_bridge(
    events: Sequence[TransactionEvent], exceptions: Sequence[Exception_]
) -> CashBridge:
    """Build the bridge for one run.

    ``events`` is the whole ingested corpus, not just what matched — the
    bridge is a books-level question ("sales were booked at gross, the bank
    paid net, what happened to the difference"), independent of what the
    matching cascade did or didn't prove (CLAUDE.md: "the Rulebook's gap is
    not the cascade's gap" applies here too, for the same reason).
    """
    gross_paise = 0
    mdr_paise = 0
    gst_paise = 0
    payment_event_ids: list[str] = []
    for event in events:
        is_payment_credit = (
            event.source == "razorpay"
            and event.txn_type == "payment"
            and event.direction == "credit"
        )
        if is_payment_credit:
            gross_paise += event.amount_paise + (event.fee_paise or 0)
            mdr_paise += (event.fee_paise or 0) - (event.tax_paise or 0)
            gst_paise += event.tax_paise or 0
            payment_event_ids.append(event.event_id)

    tds_paise, tds_ids = 0, []
    reserve_hold_paise, reserve_hold_ids = 0, []
    reserve_release_paise, reserve_release_ids = 0, []
    for event in events:
        if event.source != "razorpay" or event.txn_type != "adjustment":
            continue
        description = str(event.raw.get("description") or "")
        if _TDS_MARKER in description:
            tds_paise += abs(event.amount_paise)
            tds_ids.append(event.event_id)
        elif _RESERVE_RELEASE_MARKER in description:
            reserve_release_paise += abs(event.amount_paise)
            reserve_release_ids.append(event.event_id)
        elif _RESERVE_HOLD_MARKER in description:
            reserve_hold_paise += abs(event.amount_paise)
            reserve_hold_ids.append(event.event_id)

    refund_paise, refund_ids = 0, []
    chargeback_paise, chargeback_ids = 0, []
    for event in events:
        if event.source != "razorpay" or event.direction != "debit":
            continue
        if event.txn_type == "refund":
            refund_paise += abs(event.amount_paise)
            refund_ids.append(event.event_id)
        elif event.txn_type == "dispute":
            chargeback_paise += abs(event.amount_paise)
            chargeback_ids.append(event.event_id)

    actual_bank_paise = 0
    for event in events:
        if event.source != "bank":
            continue
        sign = 1 if event.direction == "credit" else -1
        actual_bank_paise += sign * event.amount_paise

    reserve_net_paise = reserve_hold_paise - reserve_release_paise
    expected_net_paise = (
        gross_paise
        - mdr_paise
        - gst_paise
        - tds_paise
        - refund_paise
        - chargeback_paise
        - reserve_net_paise
    )
    unexplained_paise = expected_net_paise - actual_bank_paise

    chargeback_exception_ids = tuple(
        sorted(e.exception_id for e in exceptions if e.category == "chargeback_unrecorded")
    )
    unexplained_exception_ids = tuple(
        sorted(e.exception_id for e in exceptions if e.category in _UNEXPLAINED_CATEGORIES)
    )

    deductions = (
        BridgeSegment("MDR", mdr_paise, tuple(payment_event_ids)),
        BridgeSegment("GST on MDR", gst_paise, tuple(payment_event_ids)),
        BridgeSegment("TDS 194-O", tds_paise, tuple(tds_ids)),
        BridgeSegment("Refunds settled", refund_paise, tuple(refund_ids)),
        BridgeSegment(
            "Chargebacks",
            chargeback_paise,
            tuple(chargeback_ids),
            exception_ids=chargeback_exception_ids,
        ),
        BridgeSegment(
            "Rolling reserve",
            reserve_net_paise,
            (*reserve_hold_ids, *reserve_release_ids),
        ),
    )
    unexplained_segment = BridgeSegment(
        "Unexplained", unexplained_paise, (), exception_ids=unexplained_exception_ids
    )
    segments = (*deductions, unexplained_segment)

    total_paise = sum(segment.amount_paise for segment in segments)
    if total_paise != gross_paise - actual_bank_paise:
        raise ValueError(
            f"cash bridge segments sum to {total_paise} paise, expected gross - actual = "
            f"{gross_paise - actual_bank_paise} paise"
        )

    cash_at_risk_paise = sum(
        e.amount_paise for e in exceptions if e.tier == "escalate" and e.deadline is not None
    )

    return CashBridge(
        gross_collected_paise=gross_paise,
        deductions=deductions,
        expected_net_paise=expected_net_paise,
        actual_bank_paise=actual_bank_paise,
        unexplained_paise=unexplained_paise,
        segments=segments,
        cash_at_risk_paise=cash_at_risk_paise,
        reserve_pending_release_paise=reserve_net_paise,
        gst_input_credit_claimable_paise=gst_paise,
    )
