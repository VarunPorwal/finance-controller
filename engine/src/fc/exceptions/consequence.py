"""Cash impact and deadline — PRD §6.8.6.

The deadline computed here is the one stored on ``exceptions.deadline`` and
fed to :func:`fc.exceptions.priority.deadline_urgency` — it is not decoration,
it is the number that moves an item to the top of the queue as the dispute
window closes. Categories with nothing at stake (a duplicate the books can
simply reverse, a timing gap that resolves itself) carry no deadline, which
is the correct answer rather than a missing one.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta

from fc.config import Config
from fc.exceptions.classify import Classified
from fc.models.money import fmt_inr
from fc.models.transaction import TransactionEvent

__all__ = ["consequence_and_deadline"]


def consequence_and_deadline(
    classified: Classified,
    *,
    events_by_id: Mapping[str, TransactionEvent],
    cfg: Config,
    as_of: date,
) -> tuple[str | None, date | None]:
    """§6.8.6's consequence sentence, plus the deadline it is measured against.

    ``as_of`` is the run's own date, injected rather than read off the clock
    (CLAUDE.md hard rule 9): "12 days remaining" must mean the same thing on
    replay as it did the day the run happened.
    """
    anchor = events_by_id.get(classified.event_ids[0]) if classified.event_ids else None
    amount = fmt_inr(classified.amount_paise)

    if classified.category == "chargeback_unrecorded":
        booked = anchor.effective_date if anchor is not None else as_of
        deadline = booked + timedelta(days=cfg.dispute_window_days)
        days_remaining = max((deadline - as_of).days, 0)
        return (
            f"{amount} becomes unrecoverable after {deadline.isoformat()} "
            f"({days_remaining} days remaining)",
            deadline,
        )

    if classified.category == "missing_in_bank":
        settled = anchor.settled_at.date() if anchor is not None and anchor.settled_at else None
        base = settled or (anchor.effective_date if anchor is not None else None)
        if base is None:
            return f"{amount} not yet received.", None
        deadline = base + timedelta(days=cfg.missing_in_bank_sla_days)
        return (
            f"{amount} not yet received. Escalate to Razorpay support if not credited by "
            f"{deadline.isoformat()}",
            deadline,
        )

    if classified.category == "timing_lag":
        if classified.expected_resolution_date is not None:
            recheck_at = classified.expected_resolution_date + timedelta(days=1)
            return f"No action needed. Auto-recheck {recheck_at.isoformat()}", None
        return "No action needed; expected to resolve on its own.", None

    if classified.category == "duplicate_ledger_entry":
        return f"Books overstate revenue by {amount} until the duplicate is reversed.", None

    if classified.category == "missing_in_ledger":
        return f"Books understate cash by {amount} until this settlement is recorded.", None

    if classified.category == "missing_in_gateway":
        return (
            f"{amount} sits in the bank with no gateway record; confirm before booking it "
            "as revenue.",
            None,
        )

    if classified.category == "amount_variance":
        return f"{amount} of gross is unaccounted for; margin is overstated until explained.", None

    if classified.category == "ambiguous_multi_candidate":
        return f"{amount} cannot close until one candidate is confirmed.", None

    return None, None
