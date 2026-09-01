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

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fc.models.exception_ import Exception_
from fc.models.match import MatchResult
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
    """One row of the bridge: a label, an amount, and what proves it.

    ``amount_paise`` and ``attributed_paise`` are two different questions and
    the segment carries both because conflating them produced a wrong figure on
    screen. ``amount_paise`` is the segment's place in the bridge arithmetic —
    for "Unexplained" that is ``expected_net - actual_bank``, the balancing
    residual the whole bridge must sum to. ``attributed_paise`` is what the
    exceptions named in ``exception_ids`` actually total.

    They are not the same number and cannot be made the same. The residual is
    net over the whole corpus after MDR, GST, TDS, refunds, chargebacks and
    reserve have been taken out; the exceptions are gross per-discrepancy
    amounts that overlap those same deductions. On the reference corpus the
    residual is ₹2,373.89 and the attributed exceptions total ₹26,940.42.

    Clicking the residual used to reveal the attributed set, so a drill-down on
    ₹2,373.89 displayed ₹26,940.42 of exceptions. Carrying both means whichever
    number a reader clicks, the rows they get sum to it.
    """

    label: str
    amount_paise: int
    event_ids: tuple[str, ...]
    exception_ids: tuple[str, ...] = ()
    #: Sum of ``amount_paise`` over ``exception_ids``. Always reconciles with
    #: them, because :func:`_attribute` computes the pair together.
    attributed_paise: int = 0


@dataclass(frozen=True)
class CashBridge:
    gross_collected_paise: int
    #: The razorpay payment-credit rows that sum to `gross_collected_paise`.
    #: Carried the same way `BridgeSegment.event_ids` is, so a click on
    #: "Gross settled" can show the rows behind it.
    gross_event_ids: tuple[str, ...]
    deductions: tuple[BridgeSegment, ...]
    expected_net_paise: int
    actual_bank_paise: int
    #: The bank rows that sum to `actual_bank_paise` — only ones the matcher
    #: attributed to the gateway (part of a match whose `sources_covered`
    #: includes both "bank" and "razorpay"). A real merchant's statement has
    #: salary, rent, vendor payments and GST challans on the same account;
    #: netting the *whole* statement against gateway gross produced a
    #: meaningless gap the moment a corpus had any of those.
    actual_bank_event_ids: tuple[str, ...]
    unexplained_paise: int
    #: Every deduction plus the terminal "Unexplained" line, in bridge order.
    segments: tuple[BridgeSegment, ...]
    cash_at_risk_paise: int
    reserve_pending_release_paise: int
    gst_input_credit_claimable_paise: int


def _attribute(
    exceptions: Sequence[Exception_], predicate: Callable[[Exception_], bool]
) -> tuple[tuple[str, ...], int]:
    """The exceptions a segment is attributed to, and what they total.

    One function returns both halves so the ids and the total cannot drift
    apart — the ids were built by a comprehension and the total was never built
    at all, which is how a segment came to display a number no set of rows
    added up to.
    """
    selected = sorted((e for e in exceptions if predicate(e)), key=lambda e: e.exception_id)
    return tuple(e.exception_id for e in selected), sum(e.amount_paise for e in selected)


def compute_cash_bridge(
    events: Sequence[TransactionEvent],
    exceptions: Sequence[Exception_],
    matches: Sequence[MatchResult],
) -> CashBridge:
    """Build the bridge for one run.

    The gross/deduction side of the bridge (razorpay rows) is still read
    straight off the whole ingested corpus — "sales were booked at gross,
    what did the gateway deduct" does not depend on what the matching
    cascade proved (CLAUDE.md: "the Rulebook's gap is not the cascade's
    gap" applies here too, for the same reason).

    ``actual_bank_paise`` is different: a bank statement carries salary,
    rent, vendor payments, ad spend and GST challans alongside gateway
    settlements, and none of those are the bank's side of *this* bridge. Only
    bank rows the matcher actually attributed to the gateway — part of a
    match whose ``sources_covered`` includes both ``bank`` and ``razorpay``
    — count here; everything else on the statement is out of scope for this
    question, not evidence of a gap.
    """
    gateway_matched_bank_ids: set[str] = set()
    for m in matches:
        if "bank" in m.sources_covered and "razorpay" in m.sources_covered:
            gateway_matched_bank_ids.update(m.event_ids)
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
    # Signed, not a magnitude: a dispute debit is a chargeback (subtracts from
    # net) and a dispute credit is its reversal (the money comes back, so it
    # must add back). Both are txn_type == "dispute" — direction is what tells
    # them apart. Filtering the whole loop to direction == "debit" (as this
    # used to) silently dropped every reversal from the bridge: not double
    # counted, just invisible, which is how a batch that nets out correctly
    # in the bank still showed a phantom gap of exactly one reversal.
    chargeback_paise, chargeback_ids = 0, []
    for event in events:
        if event.source != "razorpay":
            continue
        if event.txn_type == "refund" and event.direction == "debit":
            refund_paise += abs(event.amount_paise)
            refund_ids.append(event.event_id)
        elif event.txn_type == "dispute":
            sign = 1 if event.direction == "debit" else -1
            chargeback_paise += sign * abs(event.amount_paise)
            chargeback_ids.append(event.event_id)

    actual_bank_paise = 0
    actual_bank_ids: list[str] = []
    for event in events:
        if event.source != "bank" or event.event_id not in gateway_matched_bank_ids:
            continue
        sign = 1 if event.direction == "credit" else -1
        actual_bank_paise += sign * event.amount_paise
        actual_bank_ids.append(event.event_id)

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

    chargeback_exception_ids, chargeback_attributed = _attribute(
        exceptions, lambda e: e.category == "chargeback_unrecorded"
    )
    unexplained_exception_ids, unexplained_attributed = _attribute(
        exceptions, lambda e: e.category in _UNEXPLAINED_CATEGORIES
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
            attributed_paise=chargeback_attributed,
        ),
        BridgeSegment(
            "Rolling reserve",
            reserve_net_paise,
            (*reserve_hold_ids, *reserve_release_ids),
        ),
    )
    unexplained_segment = BridgeSegment(
        "Unexplained",
        unexplained_paise,
        (),
        exception_ids=unexplained_exception_ids,
        attributed_paise=unexplained_attributed,
    )
    segments = (*deductions, unexplained_segment)

    by_id = {e.exception_id: e for e in exceptions}
    for segment in segments:
        restated = sum(by_id[i].amount_paise for i in segment.exception_ids if i in by_id)
        if restated != segment.attributed_paise:
            raise ValueError(
                f"bridge segment {segment.label!r} attributes {segment.attributed_paise} paise "
                f"to {len(segment.exception_ids)} exception(s) that total {restated} paise"
            )

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
        gross_event_ids=tuple(payment_event_ids),
        deductions=deductions,
        expected_net_paise=expected_net_paise,
        actual_bank_paise=actual_bank_paise,
        actual_bank_event_ids=tuple(actual_bank_ids),
        unexplained_paise=unexplained_paise,
        segments=segments,
        cash_at_risk_paise=cash_at_risk_paise,
        reserve_pending_release_paise=reserve_net_paise,
        gst_input_credit_claimable_paise=gst_paise,
    )
