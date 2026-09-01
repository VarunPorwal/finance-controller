"""Lanes — which counterpart a row is supposed to reconcile against.

A bank account carries more than one kind of money. Gateway settlements land
next to marketplace payouts, POS terminal settlements, salary NACH, ad spend
and a GST challan, and every one of those has a *different* counterpart:

======================  ==========================================
lane                    reconciles
======================  ==========================================
``gateway``             bank <-> gateway recon <-> ledger
``marketplace``         bank <-> ledger
``pos``                 bank <-> ledger
``operating``           bank <-> ledger
``other``               bank <-> ledger, or nothing (unidentified)
======================  ==========================================

This replaces filtering rows in or out of a matching pool. A filter answers
"is this gateway money?" and throws away everything that isn't, which means
the six unbooked bank charges sitting in a statement — real findings, and the
kind a controller actually acts on — are discarded before anything can look at
them. A lane answers the better question, "what should this have agreed with?",
and every row keeps a counterpart to be judged against.

Nothing here is a name list. Every lane is derived from the files themselves:
the gateway lane from the settlement ids and UTRs the gateway recon actually
contains, the marketplace lane from counterparties whose payouts the books
book a commission against, the POS lane from the terminal vocabulary the
statement itself uses, the operating lane from the direction the money moved
and the account it was booked to. Point the engine at a different merchant and
the lanes come out of that merchant's data.

Pure: takes events, returns a mapping. No database, no LLM (this is a decision
module under CLAUDE.md hard rule 2).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from fc.ingest.narration.base import is_internal_tag, narration_tag
from fc.matching.ledger_refs import LedgerRefIndex, index_ledger_refs
from fc.models.transaction import TransactionEvent

__all__ = ["LANES", "Lane", "LaneMap", "assign_lanes"]

Lane = Literal["gateway", "marketplace", "pos", "operating", "other"]

#: Presentation order: the lane the business is actually about first, the
#: bucket that means "we could not say" last.
LANES: Final[tuple[Lane, ...]] = ("gateway", "marketplace", "pos", "operating", "other")

#: Chart-of-accounts words, not company names. A platform that nets its fee out
#: of the payout forces the merchant to book that fee somewhere, and this is
#: what the account is called when they do. A counterparty with such a leg
#: against it settles net — which is exactly what makes it a marketplace rather
#: than a customer who pays an invoice in full.
_MARKETPLACE_ACCOUNT_WORDS: Final[tuple[str, ...]] = ("COMMISSION", "TCS")

#: Statement and daybook vocabulary for a card-acquirer terminal settlement.
#: ``TID`` is the terminal id; ``POS`` is the statement's own tag for the rail.
_POS_MARKERS: Final[tuple[str, ...]] = ("POS", "TID")

#: Ledger accounts that hold money the business *owes or spends* rather than
#: collects. Matched as whole words against the account name so "Bank Charges"
#: and "Rates and Taxes" are caught while "Sales" and "Razorpay Clearing" are
#: not. Again a chart-of-accounts vocabulary, shared across every Indian SME
#: daybook, not this merchant's account list.
_OPERATING_ACCOUNT_WORDS: Final[frozenset[str]] = frozenset(
    {
        "ADVERTISING",
        "CHARGES",
        "DUTIES",
        "ELECTRICITY",
        "EXPENSE",
        "EXPENSES",
        "FREIGHT",
        "INSURANCE",
        "INTEREST",
        "PACKING",
        "PAYABLE",
        "PURCHASES",
        "RATES",
        "RENT",
        "SALARIES",
        "SALARY",
        "TAXES",
        "WAGES",
    }
)

_WORD = re.compile(r"[A-Z]+")


@dataclass(frozen=True)
class LaneMap:
    """Every event's lane, plus the counterparty-level table it came from.

    ``party_lane`` is kept because it is the explanation: a row is in the
    marketplace lane *because this counterparty settles net of commission*,
    and a UI that can only show the answer without the reason is not much use
    to someone deciding whether to trust it.
    """

    lane_of: Mapping[str, Lane]
    party_lane: Mapping[str, Lane]

    def lane(self, event_id: str) -> Lane:
        return self.lane_of.get(event_id, "other")

    def event_ids(self, lane: Lane) -> tuple[str, ...]:
        return tuple(sorted(e for e, value in self.lane_of.items() if value == lane))

    def counts(self) -> Mapping[Lane, int]:
        counts: dict[Lane, int] = dict.fromkeys(LANES, 0)
        for value in self.lane_of.values():
            counts[value] = counts.get(value, 0) + 1
        return counts


def _account_words(name: str | None) -> set[str]:
    return set(_WORD.findall((name or "").upper()))


def _gateway_references(
    events: Sequence[TransactionEvent],
) -> tuple[frozenset[str], frozenset[str]]:
    """Every settlement id and UTR the gateway recon file itself contains.

    The gateway lane is defined by this set and nothing else: a bank credit is
    gateway money when it quotes a reference the processor's own report claims,
    and a merchant with a different processor gets a different set for free.
    """
    settlements: set[str] = set()
    utrs: set[str] = set()
    for event in events:
        if event.source != "razorpay":
            continue
        if event.settlement_id:
            settlements.add(event.settlement_id)
        if event.utr:
            utrs.add(event.utr)
    return frozenset(settlements), frozenset(utrs)


def _cites_gateway(
    event: TransactionEvent,
    refs: LedgerRefIndex,
    settlements: frozenset[str],
    utrs: frozenset[str],
) -> bool:
    if event.settlement_id and event.settlement_id in settlements:
        return True
    if event.utr and event.utr in utrs:
        return True
    if event.rrn and event.rrn in utrs:
        return True
    if event.source != "ledger":
        return False
    cited = refs.for_event(event.event_id)
    return bool(set(cited.settlement_ids) & settlements)


def _party_lanes(
    events: Sequence[TransactionEvent],
    refs: LedgerRefIndex,
    settlements: frozenset[str],
    utrs: frozenset[str],
) -> dict[str, Lane]:
    """Counterparty -> lane, decided once and applied to every row that names it.

    Resolved in order of how much the evidence proves. A counterparty the
    gateway file itself names is the processor. One the books book a
    commission against settles net, so it is a marketplace. One the statement
    tags as a terminal settlement is an acquirer. Anything else is left
    unassigned here and decided per row, because the same customer can send a
    receipt one week and a refund the next.
    """
    lanes: dict[str, Lane] = {}

    for event in events:
        party = event.counterparty_norm
        if party and _cites_gateway(event, refs, settlements, utrs):
            lanes[party] = "gateway"

    for event in events:
        party = event.counterparty_norm
        if not party or lanes.get(party) == "gateway":
            continue
        if event.source == "ledger" and _account_words(event.ledger_account) & set(
            _MARKETPLACE_ACCOUNT_WORDS
        ):
            lanes[party] = "marketplace"

    for event in events:
        party = event.counterparty_norm
        if not party or party in lanes:
            continue
        text = f"{narration_tag(event.raw_narration or '')} {event.raw_narration or ''}".upper()
        if any(re.search(rf"\b{marker}\b", text) for marker in _POS_MARKERS):
            lanes[party] = "pos"

    return lanes


def _ledger_lane(event: TransactionEvent, bank_ledgers: frozenset[str]) -> Lane:
    """A daybook row with no lane-bearing counterparty, judged by its account.

    The account a voucher books to *is* the statement of what kind of money it
    was. An expense, tax or payroll account is operating; the bank account
    itself and everything else is left as other, where a bank counterpart can
    still be found for it.
    """
    if _account_words(event.ledger_account) & _OPERATING_ACCOUNT_WORDS:
        return "operating"
    if event.ledger_account in bank_ledgers and event.voucher_type == "Payment":
        return "operating"
    return "other"


def _bank_lane(event: TransactionEvent) -> Lane:
    """A statement row with no lane-bearing counterparty.

    A debit is money leaving the business, and money leaving a merchant's
    current account is an operating outflow unless a lane has already claimed
    it — no gateway, marketplace or acquirer pays the merchant by taking money
    out. A credit the bank tags as internal (interest, a charge reversal) is
    the same lane from the other direction. Everything else is a credit nobody
    has identified, which is the honest answer, and the reason ``other`` is a
    lane rather than a discard.
    """
    if is_internal_tag(event.raw_narration or ""):
        return "operating"
    if event.direction == "debit":
        return "operating"
    return "other"


def assign_lanes(
    events: Sequence[TransactionEvent],
    *,
    bank_ledger_names: Iterable[str] = (),
    ledger_refs: LedgerRefIndex | None = None,
) -> LaneMap:
    """Put every event in exactly one lane."""
    events = tuple(events)
    refs = ledger_refs if ledger_refs is not None else index_ledger_refs(events)
    settlements, utrs = _gateway_references(events)
    party_lane = _party_lanes(events, refs, settlements, utrs)
    bank_ledgers = frozenset(bank_ledger_names)

    lane_of: dict[str, Lane] = {}
    for event in events:
        if event.source == "razorpay" or _cites_gateway(event, refs, settlements, utrs):
            lane_of[event.event_id] = "gateway"
            continue
        party = event.counterparty_norm
        if party and party in party_lane:
            lane_of[event.event_id] = party_lane[party]
            continue
        lane_of[event.event_id] = (
            _ledger_lane(event, bank_ledgers) if event.source == "ledger" else _bank_lane(event)
        )

    return LaneMap(lane_of=lane_of, party_lane=party_lane)
