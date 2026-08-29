"""Learning a rule from repeated human resolutions — PRD §8.8, §2.6 D5.

The machine does what it can prove; the human supplies what only they know; the
system turns that into a rule so it needs asking less next time. Three
resolutions of the same shape, resolved the same way, with no active rule
covering them, produce a **draft**.

**It never auto-activates.** Not at three, not at thirty. A draft is a proposal
with a back-test attached, and a human approves it with the numbers in front of
them (§8.8). :func:`detect_drafts` cannot return an active rule — the status is
set in one place and asserted before return — and ``fc.rules.scope.candidates``
filters drafts out, so an unapproved draft has no path to closing anything even
if something later forgets to check its status.

**Deliberate deviation from §8.8.** The PRD drafts via
``llm.call("rule_draft", ...)``. The numbers here are derived arithmetically
from the three resolutions instead. Two reasons, both hard rules: ``make eval``
must run with no network (rule 6) and the same input must produce byte-identical
output (rule 9), neither of which survives a model in the loop. An LLM may still
*name and describe* a draft — prose that decides nothing — and the rates it
would have guessed are exactly what the resolutions already state.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import get_args

from fc.ingest.aliases import AliasTable
from fc.models.exception_ import NEVER_AUTO, ExceptionCategory
from fc.models.money import fmt_inr
from fc.models.rule import Deduction, Rail, Rule, Scope, Tolerance
from fc.models.transaction import TransactionEvent
from fc.rules.evaluator import evaluate_deductions
from fc.rules.loader import version_hash
from fc.rules.scope import scope_matches

__all__ = [
    "DRAFT_THRESHOLD",
    "LEARNED_DRAFT_CONFIDENCE",
    "Resolution",
    "RuleDraft",
    "amount_band",
    "detect_drafts",
    "gap_shape",
    "signature",
]

#: §8.8: "if count >= 3". Three is the point at which a coincidence becomes a
#: pattern a merchant would recognise, and it is the number the PRD commits to.
DRAFT_THRESHOLD = 3

#: The ceiling a learned draft proposes for itself. Below the shipped
#: ``auto_threshold`` on purpose: a rule nobody has approved does not carry an
#: item to auto-close on its own strength. A human raising it afterwards is a
#: decision with a name attached, which is the point.
LEARNED_DRAFT_CONFIDENCE = Decimal("0.90")

_HUNDRED = Decimal(100)
_TWO_PLACES = Decimal("0.01")
_WHOLE = Decimal(1)

#: Amount bands, in paise. Order-of-magnitude buckets: two ₹4,000 settlements
#: are the same shape, a ₹4,000 and a ₹4,00,000 are not, and a band finer than
#: this would make three matching resolutions vanishingly rare.
_BANDS: tuple[tuple[int, str], ...] = (
    (1_000_00, "<1k"),
    (10_000_00, "1k-10k"),
    (1_00_000_00, "10k-1L"),
    (10_00_000_00, "1L-10L"),
)
_TOP_BAND = ">10L"

#: Gap-shape resolution, in percentage points of gross. Half a point: 18% and
#: 20% commission are different shapes, 18.02% and 18.04% are the same one seen
#: through per-transaction rounding.
_SHAPE_STEP = Decimal("0.5")

#: ``Scope.rail``'s closed vocabulary, for narrowing an ingested rail string.
_RAILS: frozenset[str] = frozenset(get_args(Rail))


@dataclass(frozen=True)
class Resolution:
    """One exception a human resolved, with the shape that made it what it was."""

    exception_id: str
    category: ExceptionCategory
    #: What the human said this was — the second half of §8.8's count predicate.
    resolution_category: str
    event: TransactionEvent
    on_date: date
    gap_paise: int
    gross_paise: int
    n_txns: int = 1

    @property
    def signature(self) -> str:
        """The value stored on ``exceptions.signature``."""
        return signature(
            category=self.category,
            counterparty_norm=self.event.counterparty_norm,
            rail=self.event.rail,
            amount_paise=self.event.amount_paise,
            gap_paise=self.gap_paise,
            gross_paise=self.gross_paise,
        )


@dataclass(frozen=True)
class RuleDraft:
    """A proposed rule and the evidence that produced it (§5.9 ``/rules/suggestions``)."""

    rule: Rule
    signature: str
    occurrences: int
    exception_ids: tuple[str, ...]
    resolution_category: str
    observed_rate_percent: Decimal
    #: Every case the draft was learned from, replayable by the back-test.
    resolutions: tuple[Resolution, ...]


def signature(
    *,
    category: str,
    counterparty_norm: str | None,
    rail: str | None,
    amount_paise: int,
    gap_paise: int,
    gross_paise: int,
) -> str:
    """§8.8's shape hash.

    Five components, joined by a separator that cannot occur inside any of them
    so ``("AB", "C")`` and ``("A", "BC")`` cannot collide. The amount and the gap
    enter as *bands*, not values: the signature has to group items that are the
    same problem, and no two settlements share an exact amount.
    """
    parts = (
        category,
        counterparty_norm or "-",
        rail or "-",
        amount_band(amount_paise),
        gap_shape(gap_paise, gross_paise),
    )
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def amount_band(paise: int) -> str:
    """The order-of-magnitude band an amount falls in."""
    magnitude = abs(paise)
    for ceiling, label in _BANDS:
        if magnitude < ceiling:
            return label
    return _TOP_BAND


def gap_shape(gap_paise: int, gross_paise: int) -> str:
    """The gap as a proportion of gross, quantised to half a percentage point.

    This is what makes the signature about a *deduction* rather than an amount:
    every Blinkit settlement short by the same 18% lands in the same shape
    whatever its size, and a settlement short by a flat ₹2,000 does not.
    """
    if gross_paise == 0:
        return "gross=0"
    ratio = Decimal(abs(gap_paise)) * _HUNDRED / Decimal(abs(gross_paise))
    floor = (ratio / _SHAPE_STEP).to_integral_value(rounding="ROUND_FLOOR") * _SHAPE_STEP
    return f"{_text(floor)}-{_text(floor + _SHAPE_STEP)}%"


def detect_drafts(
    resolutions: Iterable[Resolution],
    *,
    active_rules: Sequence[Rule] = (),
    tenant_id: str,
    created_at: datetime,
    created_by: str = "system:learner",
    threshold: int = DRAFT_THRESHOLD,
    aliases: AliasTable | None = None,
) -> tuple[RuleDraft, ...]:
    """Draft a rule for every signature resolved the same way ``threshold`` times.

    ``NEVER_AUTO`` categories are excluded before counting rather than caught by
    the back-test afterwards. Three chargebacks resolved identically say
    something true about the merchant's process and nothing at all about a
    deduction rate; drafting a rule from them would put a proposal in front of a
    human whose only correct answer is "discard", and offering it at all is a
    small invitation to click activate.
    """
    grouped: dict[tuple[str, str], list[Resolution]] = {}
    for resolution in resolutions:
        if resolution.category in NEVER_AUTO:
            continue
        if resolution.gross_paise == 0 or resolution.gap_paise == 0:
            continue
        grouped.setdefault((resolution.signature, resolution.resolution_category), []).append(
            resolution
        )

    drafts: list[RuleDraft] = []
    for (shape, resolution_category), members in sorted(grouped.items()):
        if len(members) < threshold:
            continue
        ordered = tuple(sorted(members, key=lambda r: r.exception_id))
        if _already_covered(ordered, active_rules, aliases):
            continue
        drafts.append(
            _draft(shape, resolution_category, ordered, tenant_id, created_at, created_by)
        )
    return tuple(drafts)


def _already_covered(
    members: Sequence[Resolution], active_rules: Sequence[Rule], aliases: AliasTable | None
) -> bool:
    """Whether an active rule already speaks to every case in this group.

    Every, not any. A rule that covers two of the three leaves the third
    recurring, which is the situation the learner exists to notice.
    """
    if not active_rules:
        return False
    return all(
        any(
            scope_matches(rule, member.event, member.on_date, aliases=aliases)
            for rule in active_rules
        )
        for member in members
    )


def _draft(
    shape: str,
    resolution_category: str,
    members: Sequence[Resolution],
    tenant_id: str,
    created_at: datetime,
    created_by: str,
) -> RuleDraft:
    rate = _median_rate_percent(members)
    deductions = [Deduction(type="custom", basis="gross", rate=rate)]
    # The tolerance is the widest miss the learned rate leaves across the very
    # cases it was learned from, so the draft demonstrably explains all of them.
    # Deriving it from the evidence rather than from a constant is also what
    # keeps a noisy group honest: three cases that disagree produce a wide
    # tolerance, and a wide tolerance is visible to the human approving it.
    worst = max(
        abs(member.gap_paise - evaluate_deductions(deductions, member.gross_paise).total_paise)
        for member in members
    )
    tolerance = Tolerance(absolute_paise=worst, percent=Decimal("0.05"))

    anchor = members[0].event
    scope = Scope(
        counterparty_matches=[anchor.counterparty_norm] if anchor.counterparty_norm else None,
        source=anchor.source,
        rail=_known_rail(anchor.rail),
        date_from=min(member.on_date for member in members),
    )
    counterparty = anchor.counterparty_norm or "unnamed counterparty"
    rule = Rule(
        rule_id=f"learned_{resolution_category}_{shape[:12]}",
        version=1,
        tenant_id=tenant_id,
        version_hash=version_hash(scope, deductions, tolerance),
        name=f"Learned: {resolution_category} for {counterparty}",
        description=(
            f"Drafted from {len(members)} human resolutions of the same shape "
            f"({', '.join(m.exception_id for m in members)}), each resolved as "
            f"{resolution_category!r}. Observed deduction {_text(rate)}% of gross; widest "
            f"miss across those cases {fmt_inr(worst)}. Not applied until a human activates it."
        ),
        scope=scope,
        deductions=deductions,
        tolerance=tolerance,
        priority=50,  # below hand-written rules; a guess yields to a statement
        effective_confidence=LEARNED_DRAFT_CONFIDENCE,
        effective_from=scope.date_from,
        status="draft",
        origin="learned",
        created_by=created_by,
        created_at=created_at,
    )
    # §8.8, stated twice on purpose: the assertion costs nothing and the
    # invariant is the entire safety story of this module.
    assert rule.status == "draft" and rule.origin == "learned", "learner produced a live rule"
    return RuleDraft(
        rule=rule,
        signature=shape,
        occurrences=len(members),
        exception_ids=tuple(member.exception_id for member in members),
        resolution_category=resolution_category,
        observed_rate_percent=rate,
        resolutions=tuple(members),
    )


def _known_rail(rail: str | None) -> Rail | None:
    """Narrow an ingested rail string to the scope vocabulary.

    ``TransactionEvent.rail`` is free text from a narration parser; ``Scope.rail``
    is a closed set. A rail nobody named leaves the clause off rather than
    inventing one, which makes the draft *wider* and therefore visible to the
    human rather than quietly inert.
    """
    return rail if rail in _RAILS else None  # type: ignore[return-value]


def _median_rate_percent(members: Sequence[Resolution]) -> Decimal:
    """The middle observed ``gap / gross``, as a percentage to two places.

    Median rather than mean: one mis-resolved case in three should not drag the
    rate, and the lower median on an even count keeps the result a pure function
    of the inputs with no tie-breaking rule to remember.
    """
    rates = sorted(
        Decimal(abs(m.gap_paise)) * _HUNDRED / Decimal(abs(m.gross_paise)) for m in members
    )
    middle = rates[(len(rates) - 1) // 2]
    return middle.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")
