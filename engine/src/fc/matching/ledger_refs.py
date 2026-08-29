"""Gateway references recovered from ledger narration — PRD §6.4.

Tally exports carry no gateway identifier in a field. ``fc/ingest/tally.py``
says so deliberately: ``reference_number`` is an invoice reference, "not a
gateway order id, so it is kept only in ``raw`` ... three-way matching (PRD
§6.4) finds the ledger leg via ``narration``, where the actual order reference
appears". This module is that lookup, kept separate from any one stage because
``exact_ref`` needs it now and three-way resolution needs the same extraction
next.

A row whose narration yields nothing is **not** dropped. It stays in the
unmatched pool so the exception pipeline can call it ``missing_in_gateway`` /
``missing_in_ledger``, and it is counted so "the matcher missed it" stays
distinguishable from "the row had nothing to match on".
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from fc.models.transaction import TransactionEvent

__all__ = ["LedgerRefIndex", "LedgerRefs", "extract_refs", "index_ledger_refs"]

logger = logging.getLogger(__name__)

#: ULIDs are Crockford base32 - no I, L, O or U - so a loose alphanumeric class
#: would match text that cannot be an identifier. Anchored on the entity prefix
#: because a bare 26-character token is not evidence of anything.
#: Compiled at module level, never per row (CLAUDE.md conventions).
_LEDGER_REF = re.compile(r"\b(order|setl|pay|rfnd)_([0-9A-HJKMNP-TV-Z]{26})\b")

_FIELD_BY_PREFIX = {
    "order": "order_ids",
    "setl": "settlement_ids",
    "pay": "payment_ids",
    "rfnd": "refund_ids",
}


@dataclass(frozen=True)
class LedgerRefs:
    """Gateway identifiers found in one narration, deduplicated, order preserved."""

    order_ids: tuple[str, ...] = ()
    settlement_ids: tuple[str, ...] = ()
    payment_ids: tuple[str, ...] = ()
    refund_ids: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.order_ids or self.settlement_ids or self.payment_ids or self.refund_ids)

    def identity_claims(self) -> LedgerRefs:
        """The subset usable as "this row *is* that money", not "this row mentions it".

        A narration can cite a reference without being it. ``Rolling reserve
        release settlement setl_B for setl_A`` names the settlement it belongs
        to and the one it refunds, and nothing in the text distinguishes them
        without reading it - which is the LLM's job, and the LLM does not get to
        decide what is reconciled (hard rule 2). Two candidate answers and no
        deterministic way to choose is an abstention (hard rule 4), so a
        narration citing several ids of one kind contributes none of them.

        Treating both as identity claims merges two settlements into one match,
        which is how a 100%-precision stage quietly stops being one.
        """
        return LedgerRefs(
            order_ids=self.order_ids if len(self.order_ids) == 1 else (),
            settlement_ids=self.settlement_ids if len(self.settlement_ids) == 1 else (),
            payment_ids=self.payment_ids if len(self.payment_ids) == 1 else (),
            refund_ids=self.refund_ids if len(self.refund_ids) == 1 else (),
        )


@dataclass(frozen=True)
class LedgerRefIndex:
    """Per-event extraction results plus the rows that yielded nothing."""

    refs: Mapping[str, LedgerRefs]
    #: Ledger event ids whose narration cited several ids of one kind, so none
    #: of them could be taken as an identity claim. Counted, not hidden.
    ambiguous: tuple[str, ...] = field(default=())
    #: Ledger event ids with no extractable gateway reference. These remain
    #: candidates for later stages and for the exception pipeline; they are
    #: reported, never silently discarded.
    without_reference: tuple[str, ...] = field(default=())

    def for_event(self, event_id: str) -> LedgerRefs:
        """Everything extracted from the row, cross-references included."""
        return self.refs.get(event_id, LedgerRefs())

    def identity_for_event(self, event_id: str) -> LedgerRefs:
        """Only what the row can be said to *be* - see :meth:`LedgerRefs.identity_claims`."""
        return self.for_event(event_id).identity_claims()


def extract_refs(narration: str | None) -> LedgerRefs:
    """Pull ``order_``/``setl_``/``pay_``/``rfnd_`` identifiers out of a narration."""
    if not narration:
        return LedgerRefs()
    buckets: dict[str, list[str]] = {name: [] for name in _FIELD_BY_PREFIX.values()}
    for prefix, body in _LEDGER_REF.findall(narration):
        bucket = buckets[_FIELD_BY_PREFIX[prefix]]
        value = f"{prefix}_{body}"
        if value not in bucket:
            bucket.append(value)
    return LedgerRefs(
        order_ids=tuple(buckets["order_ids"]),
        settlement_ids=tuple(buckets["settlement_ids"]),
        payment_ids=tuple(buckets["payment_ids"]),
        refund_ids=tuple(buckets["refund_ids"]),
    )


def index_ledger_refs(events: Iterable[TransactionEvent]) -> LedgerRefIndex:
    """Extract references for every ledger event, and record the barren ones."""
    refs: dict[str, LedgerRefs] = {}
    barren: list[str] = []
    ambiguous: list[str] = []
    for event in events:
        if event.source != "ledger":
            continue
        found = extract_refs(event.raw_narration)
        refs[event.event_id] = found
        if found.empty:
            barren.append(event.event_id)
        elif found.identity_claims().empty:
            ambiguous.append(event.event_id)
    if barren:
        logger.info(
            "ledger rows with no extractable gateway reference: %d of %d",
            len(barren),
            len(refs),
        )
    return LedgerRefIndex(
        refs=refs,
        without_reference=tuple(sorted(barren)),
        ambiguous=tuple(sorted(ambiguous)),
    )
