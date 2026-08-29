"""Cascade stage vocabulary — PRD §6.3.

The types every stage speaks. Kept in the package root so a stage never imports
``cascade`` (which imports the stages) and stages never import each other: the
cascade order is the design, and modules that reach into each other's internals
are how that order quietly stops holding.

A stage is a pure function of events plus config. It returns
:class:`StageMatch` facts; the cascade turns them into
:class:`fc.models.match.MatchResult` with confidence and evidence attached, so
no stage can construct a match without going through the derivation.

Abstention is first class. :class:`StageOutput` carries the events a stage
looked at and deliberately refused to decide, because "several answers were
valid so I emitted none" is a success (CLAUDE.md hard rule 4) and needs to be
visible as one rather than looking like a miss.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from fc.ingest.narration.base import NEFT_RTGS_UTR_LEN, is_truncated
from fc.models.match import MatchStage
from fc.models.transaction import TransactionEvent

__all__ = [
    "AUTO_CLOSABLE_STAGES",
    "StageMatch",
    "StageOutput",
    "reference_is_truncated",
    "trusted_bank_reference",
]

#: Expected reference length per rail, for the truncation test.
#:
#: ``TransactionEvent`` has no ``truncated`` field - ``fc/ingest/bank_csv.py``
#: computes it and drops it - so it is re-derived here from ``raw_narration``
#: and ``rail`` using ingest's own :func:`is_truncated`. Every bank parser in
#: ``fc/ingest/narration/`` uses ``NEFT_RTGS_UTR_LEN`` for NEFT/RTGS
#: (HDFC_UTR_LEN, IDFC_UTR_LEN and ICICI_REF_LEN are all aliases of it) and the
#: common-rail parser uses 12 for the UPI/IMPS RRN. A test asserts this table
#: agrees with the ingest parsers over the whole corpus, because the knowledge
#: is duplicated here and duplicated knowledge drifts.
_EXPECTED_REF_LEN = {
    "neft": NEFT_RTGS_UTR_LEN,
    "rtgs": NEFT_RTGS_UTR_LEN,
    "upi": 12,
    "imps": 12,
}

#: A NACH line is marked, never decomposed into its mandates, so truncation of
#: the batch reference is not evaluated (``fc/ingest/narration/base.py``).
_TRUNCATION_EXEMPT_RAILS = frozenset({"nach"})


def reference_is_truncated(event: TransactionEvent) -> bool:
    """Re-derive ingest's truncation verdict for a narration-sourced reference.

    Only bank events carry narration-sourced references. Gateway and ledger
    references come from structured fields or from an identifier embedded whole
    in a narration, so neither can be cut mid-token.
    """
    if event.source != "bank" or event.raw_narration is None:
        return False
    if event.rail in _TRUNCATION_EXEMPT_RAILS:
        return False
    reference = event.utr or event.rrn
    expected = _EXPECTED_REF_LEN.get(event.rail or "", NEFT_RTGS_UTR_LEN)
    return is_truncated(event.raw_narration, reference, expected)


def trusted_bank_reference(event: TransactionEvent) -> str | None:
    """The bank reference usable as evidence, or ``None`` if there is none."""
    if reference_is_truncated(event):
        return None
    return event.utr or event.rrn or None


#: §6.3: fuzzy never auto-closes. The others may, subject to the confidence
#: threshold and - once ``fc/exceptions/tier.py`` exists - the NEVER_AUTO
#: category gate, which is not yet applied anywhere.
AUTO_CLOSABLE_STAGES: frozenset[MatchStage] = frozenset(
    {"exact_ref", "fee_adjusted", "date_shift", "many_to_one", "rule"}
)


@dataclass(frozen=True)
class StageMatch:
    """What a stage proved, before confidence is derived from it."""

    stage: MatchStage
    group_key: str
    event_ids: tuple[str, ...]
    base_confidence: Decimal
    fields_agreed: tuple[str, ...] = ()
    fields_disagreed: tuple[str, ...] = ()
    arithmetic: str | None = None
    delta_paise: int = 0
    #: Denominator for ``amount_delta_ratio``; 0 means the stage proved nothing
    #: about amounts and the factor stays 1.
    amount_basis_paise: int = 0
    date_shift_days: int = 0
    candidates_considered: int = 1
    #: The subset of ``event_ids`` this stage is newly deciding. Empty means all
    #: of them. A stage that reconciles an unmatched row against a group an
    #: earlier stage already formed names only the new row here: the cascade
    #: then extends that group instead of building a rival one, so "a row
    #: matched at one stage never reaches the next" still holds - the settled
    #: rows are context, not re-decided.
    anchors: tuple[str, ...] = ()

    @property
    def decided(self) -> tuple[str, ...]:
        return self.anchors or self.event_ids


@dataclass(frozen=True)
class StageOutput:
    """One stage's verdict: what it matched, what it refused, what it counted."""

    matches: tuple[StageMatch, ...] = ()
    #: Event ids the stage had candidates for and declined to decide.
    abstained: tuple[str, ...] = ()
    #: Free-form counters surfaced by ``make eval`` (which tolerance term bound,
    #: how many references were withheld as truncated, and so on).
    diagnostics: Mapping[str, int] = field(default_factory=dict)
