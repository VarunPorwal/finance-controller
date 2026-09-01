"""Grouping the queue by what to *do* — not by what went wrong.

A category tells you the shape of a discrepancy. It does not tell you whether
somebody has to act this morning, whether the right move is to wait, whether
the fix belongs in the daybook rather than the bank, or whether the honest
answer is that nothing can be resolved from the files in hand. Those are four
different working days, and a queue sorted by category interleaves them.

::

    ACT TODAY       a window is closing; miss it and the money is gone
    WAITING         the system expects this to settle itself, and will recheck
    BOOKS FIX       bank and gateway agree; the daybook is what needs editing
    CANNOT RESOLVE  no file present can settle it; a human must decide or ask

A fifth bucket sits beside those four rather than inside them. An unidentified
inflow is money that *arrived* — nobody can say what it settles, but it is in
the account and nothing is at stake. Filing a ₹2,86,440 inward remittance under
"cannot resolve" makes that section's total read as exposure when the opposite
is true, so it gets its own heading and stays out of the four.

Deterministic and evidence-only, like every other module under
``fc/exceptions`` — no LLM (CLAUDE.md hard rule 2).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final, Literal

__all__ = ["ACTION_GROUPS", "ActionGroup", "action_group", "group_label"]

ActionGroup = Literal[
    "act_today", "waiting", "books_fix", "cannot_resolve", "unidentified_inflow"
]

ACTION_GROUPS: Final[tuple[ActionGroup, ...]] = (
    "act_today",
    "waiting",
    "books_fix",
    "cannot_resolve",
    "unidentified_inflow",
)

_LABELS: Final[dict[ActionGroup, str]] = {
    "act_today": "Act today",
    "waiting": "Waiting",
    "books_fix": "Books fix",
    "cannot_resolve": "Cannot resolve",
    "unidentified_inflow": "Unidentified inflows",
}

#: The cash and the processor's own report agree; what disagrees is the
#: daybook. Every one of these is fixed by a voucher, never by a phone call to
#: the bank — which is why they belong together however differently they are
#: categorised.
_BOOKS_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "missing_in_ledger",
        "duplicate_ledger_entry",
        "unbooked_bank_entry",
        "revenue_booked_not_settled",
        "amount_variance",
    }
)

#: Nothing in the three files can settle these. Abstention is the correct
#: outcome (CLAUDE.md hard rule 4) and this is where a correct abstention goes
#: — a queue section, not a failure.
_UNRESOLVABLE_CATEGORIES: Final[frozenset[str]] = frozenset(
    {
        "ambiguous_multi_candidate",
        "reference_truncated",
        "nach_batch_unexploded",
        "unknown",
    }
)


def group_label(group: ActionGroup) -> str:
    return _LABELS[group]


def action_group(
    category: str,
    *,
    tier: str,
    deadline: date | None = None,
    recheck_at: datetime | None = None,
    as_of: date | None = None,
) -> ActionGroup:
    """Which of the four working days this exception belongs to.

    Takes fields rather than an ``Exception_`` so
    :class:`~fc.models.exception_.Exception_` can expose the answer as a
    computed field without this module and that one importing each other.

    Order matters and is the point. A deadline that has arrived outranks
    everything else: an unrecorded chargeback inside its contest window is a
    books problem *and* a countdown, and filing it under "books fix" because of
    its shape would put a losable claim behind a data-entry task.
    """
    if deadline is not None and (as_of is None or deadline <= as_of):
        return "act_today"
    if tier == "monitor" or recheck_at is not None:
        return "waiting"
    if deadline is not None:
        return "act_today"
    # Before the unresolvable check, which it would otherwise fall into: an
    # inflow nobody can attribute is unresolvable *and* is not exposure, and
    # only the second fact tells a reader what to feel about the total.
    if category == "unidentified_inflow":
        return "unidentified_inflow"
    if category in _UNRESOLVABLE_CATEGORIES:
        return "cannot_resolve"
    if category in _BOOKS_CATEGORIES:
        return "books_fix"
    if tier == "escalate":
        return "act_today"
    return "waiting"
