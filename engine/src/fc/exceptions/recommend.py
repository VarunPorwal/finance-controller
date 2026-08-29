"""Recommendation templates — PRD §6.8.5.

Template-driven per category, parameterised with real values already sitting
on the events and the classification. The template is the source of truth: an
LLM may later rewrite one of these for readability, but it never supplies a
parameter, and every branch below produces a specific action, never a label
("Escalated" is not a recommendation).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from fc.exceptions.classify import Classified
from fc.models.money import fmt_inr
from fc.models.transaction import TransactionEvent

__all__ = ["recommended_action"]


def recommended_action(
    classified: Classified,
    *,
    events_by_id: Mapping[str, TransactionEvent],
    deadline: date | None,
) -> str:
    members = [
        events_by_id[event_id] for event_id in classified.event_ids if event_id in events_by_id
    ]
    amount = fmt_inr(classified.amount_paise)
    category = classified.category

    if category == "duplicate_ledger_entry":
        return _duplicate_ledger_entry(members, amount)
    if category == "chargeback_unrecorded":
        return _chargeback_unrecorded(members, amount, deadline)
    if category == "missing_in_bank":
        return _missing_in_bank(members, amount, deadline)
    if category == "missing_in_gateway":
        return _missing_in_gateway(members, amount)
    if category == "missing_in_ledger":
        return _missing_in_ledger(members, amount)
    if category == "partial_refund":
        return _partial_refund(members, amount)
    if category == "nach_batch_unexploded":
        return _nach_batch_unexploded(members, amount)
    if category == "timing_lag":
        return _timing_lag(amount, classified.expected_resolution_date)
    if category == "ambiguous_multi_candidate":
        return _ambiguous_multi_candidate(classified, members, amount)
    if category == "reference_truncated":
        return _reference_truncated(members, amount)
    if category == "amount_variance":
        return _amount_variance(classified, amount)
    return _unknown(members, amount)


def _duplicate_ledger_entry(members: Sequence[TransactionEvent], amount: str) -> str:
    ledger_legs = sorted((m for m in members if m.source == "ledger"), key=lambda m: m.event_id)
    if len(ledger_legs) != 2:
        return (
            f"Confirm which of {len(ledger_legs) or len(members)} ledger legs actually books "
            f"this {amount} movement; the books currently claim it more than once."
        )
    keep, reverse = ledger_legs
    order_id = reverse.order_id or keep.order_id or "the settlement"
    return (
        f"Reverse voucher {reverse.voucher_number or reverse.event_id} dated "
        f"{reverse.effective_date.isoformat()}. It duplicates "
        f"{keep.voucher_number or keep.event_id} for {amount} against {order_id}."
    )


def _chargeback_unrecorded(
    members: Sequence[TransactionEvent], amount: str, deadline: date | None
) -> str:
    event = members[0] if members else None
    order_id = (event.order_id if event else None) or "the order"
    dispute_id = None
    if event is not None and isinstance(event.raw, dict):
        dispute_id = event.raw.get("dispute_id")
    dispute_id = dispute_id or (event.event_id if event else "the dispute")
    deadline_text = deadline.isoformat() if deadline else "the contest window's close"
    return (
        f"Record chargeback of {amount} for {order_id} (dispute {dispute_id}). "
        f"Dr Disputes, Cr Bank Clearing. Contest by {deadline_text} or the amount becomes "
        "unrecoverable."
    )


def _missing_in_bank(
    members: Sequence[TransactionEvent], amount: str, deadline: date | None
) -> str:
    event = members[0] if members else None
    settled_at = event.settled_at.date().isoformat() if event and event.settled_at else "settlement"
    utr = (event.utr if event else None) or "no UTR on file"
    sla_text = deadline.isoformat() if deadline else "the usual SLA"
    return (
        f"{amount} settled by Razorpay on {settled_at} (UTR {utr}) has not been credited. "
        f"Escalate to Razorpay support if not received by {sla_text}."
    )


def _missing_in_gateway(members: Sequence[TransactionEvent], amount: str) -> str:
    event = members[0] if members else None
    when = event.effective_date.isoformat() if event else "the statement date"
    counterparty = (event.counterparty_norm if event else None) or "an unidentified counterparty"
    return (
        f"Confirm the {amount} bank credit dated {when} against a Razorpay settlement, or log "
        f"it as a direct payment from {counterparty} outside the gateway."
    )


def _missing_in_ledger(members: Sequence[TransactionEvent], amount: str) -> str:
    event = max(members, key=lambda m: abs(m.amount_paise), default=None)
    when = event.effective_date.isoformat() if event else "the settlement date"
    return (
        f"Book a Receipt for {amount} settled {when}; gateway and bank agree but the ledger "
        "does not."
    )


def _partial_refund(members: Sequence[TransactionEvent], amount: str) -> str:
    event = members[0] if members else None
    order_id = (event.order_id if event else None) or "the order"
    return (
        f"Confirm the {amount} refund against {order_id} and book the remaining balance as "
        "retained revenue."
    )


def _nach_batch_unexploded(members: Sequence[TransactionEvent], amount: str) -> str:
    event = members[0] if members else None
    when = event.effective_date.isoformat() if event else "the statement date"
    return (
        f"Log the {amount} NACH batch credited {when} as a lump-sum mandate collection; "
        "individual mandates cannot be resolved from the bank statement."
    )


def _timing_lag(amount: str, expected_resolution_date: date | None) -> str:
    when = expected_resolution_date.isoformat() if expected_resolution_date else "shortly"
    return f"No action needed; {amount} is expected to settle by {when}. Rechecked automatically."


def _ambiguous_multi_candidate(
    classified: Classified, members: Sequence[TransactionEvent], amount: str
) -> str:
    order_ids = [m.order_id for m in members if m.order_id]
    if classified.residual_paise == 0 and len(order_ids) >= 2:
        # The settlement's cash already closed (§6.8: an order-attribution
        # question, not a gap) — see fc.exceptions.classify's
        # _ambiguous_order_attribution. Different wording on purpose: nothing
        # here is waiting to close, and saying so would send someone looking
        # for a settlement that already settled.
        when = members[0].effective_date.isoformat()
        return (
            f"Settlement cash is already reconciled; {' and '.join(order_ids)} each settled "
            f"{amount} on {when} and neither ledger Sales voucher names an order, so which is "
            "which cannot be told apart from the records alone. Confirm from the Razorpay "
            "dashboard which payment belongs to which order, or note the order id on the "
            "Sales voucher narration going forward so this does not recur."
        )
    event = members[0] if members else None
    when = event.effective_date.isoformat() if event else "the same day"
    return f"Confirm which candidate {amount} dated {when} belongs to before either side is closed."


def _reference_truncated(members: Sequence[TransactionEvent], amount: str) -> str:
    event = members[0] if members else None
    when = event.effective_date.isoformat() if event else "the statement date"
    return (
        f"Manually confirm {amount} dated {when}; the bank narration truncated the reference "
        "before matching could use it."
    )


def _amount_variance(classified: Classified, amount: str) -> str:
    if classified.rules_applied:
        return classified.reason
    return (
        f"Confirm the {amount} residual against {fmt_inr(classified.gross_paise)} gross; no "
        "rule fully explains it."
    )


def _unknown(members: Sequence[TransactionEvent], amount: str) -> str:
    event = members[0] if members else None
    when = event.effective_date.isoformat() if event else "an unknown date"
    return f"Manually review {amount} dated {when}; it does not fit a known category."
