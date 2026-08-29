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

:class:`StageRefusal` is the categorised form of that. ``abstained`` says *which
rows* a stage declined; a refusal says *why*, in the vocabulary the exception
pipeline already speaks. It is deliberately not an :class:`fc.models.exception_.Exception_`:
that model needs a tier, a priority score and a signature, and the code that
computes them (``fc/exceptions/``) is a later prompt. A stage states the finding
and the category; ranking it is somebody else's job.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from fc.ingest.narration.base import NEFT_RTGS_UTR_LEN, is_truncated
from fc.models.exception_ import NEVER_AUTO, ExceptionCategory
from fc.models.match import (
    AUTO_CLOSABLE_STAGES,
    GROUPED_ONLY_STAGES,
    MatchStage,
    stage_may_auto_close,
)
from fc.models.transaction import TransactionEvent

__all__ = [
    "AUTO_CLOSABLE_STAGES",
    "GROUPED_ONLY_STAGES",
    "StageMatch",
    "StageOutput",
    "StageRefusal",
    "reference_is_truncated",
    "stage_may_auto_close",
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
    #: The key the stage grouped on, where grouping is what makes the match
    #: trustworthy. ``None`` means "this adds up" rather than "these belong
    #: together"; :func:`stage_may_auto_close` treats the difference as decisive.
    grouped_by: str | None = None
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
class StageRefusal:
    """A categorised abstention: what the stage weighed, and why it declined.

    The category is *named* here, not *classified* here. ``fc/exceptions/`` owns
    the §6.8 classification tree and is a later prompt; a stage only states the
    category it can already prove from evidence in its hand - "two settlements
    reconciled to this credit" is ``ambiguous_multi_candidate`` by construction,
    not by inference.

    This is deliberately not an :class:`fc.models.exception_.Exception_`: that
    model needs a tier, a priority score and a signature, and nothing in the
    matching package is entitled to invent them.
    """

    category: ExceptionCategory
    event_ids: tuple[str, ...]
    amount_paise: int
    reason: str

    @property
    def never_auto(self) -> bool:
        return self.category in NEVER_AUTO


@dataclass(frozen=True)
class StageOutput:
    """One stage's verdict: what it matched, what it refused, what it counted."""

    matches: tuple[StageMatch, ...] = ()
    #: What the stage declined to decide, and under which category.
    refusals: tuple[StageRefusal, ...] = ()
    #: Free-form counters surfaced by ``make eval`` (which tolerance term bound,
    #: how many references were withheld as truncated, and so on).
    diagnostics: Mapping[str, int] = field(default_factory=dict)

    @property
    def abstained(self) -> tuple[str, ...]:
        """Event ids the stage had candidates for and declined to decide.

        Derived from :attr:`refusals` rather than carried alongside them, because
        two fields asserting the same fact are two fields that eventually
        disagree - which is exactly how ``AUTO_CLOSABLE_STAGES`` came to claim
        stage 4 auto-closes unconditionally while §6.3 said "if grouped".
        """
        return tuple(sorted({e for refusal in self.refusals for e in refusal.event_ids}))
