"""Stage 3, date shift — PRD §6.3. Base confidence ``0.92 - 0.02 * days``.

Amount and a partial reference agree, but the two sides are booked one to three
days apart: a value-date shift, a refund landing after its origin settlement.

The subtle part is "partial reference agrees". A fixed shared-prefix rule is
unsound on real references. An RBI UTR is ``bank + year + day-of-year +
sequence``, so every UTR one bank issues in a month shares its first eight
characters - in the generated corpus a single eight-character prefix has
fourteen completions. Matching on a shared prefix would manufacture matches at
a rate the coverage curve would eventually expose.

So a partial reference agrees only when it has exactly **one** completion among
the references in play. If a fragment could belong to fourteen settlements, it
is evidence for none of them, and the pair falls through to be raised as an
exception rather than guessed at.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from fc.config import Config
from fc.matching.blocking import BlockIndex, PrefixIndex, candidate_pairs, reference_values
from fc.matching.stages import StageMatch, StageOutput
from fc.matching.tolerance import tolerance_terms
from fc.models.transaction import TransactionEvent

__all__ = ["BASE_CONFIDENCE", "MAX_SHIFT_DAYS", "MIN_PARTIAL_LEN", "find_matches"]

#: §6.3: 0.92 at one day, falling 0.02 per day.
BASE_CONFIDENCE = Decimal("0.92")
_PENALTY_PER_DAY = Decimal("0.02")

#: §6.3: shift in {1, 2, 3}. A zero-day shift is not this stage's business and
#: a longer one is not a shift, it is a different transaction.
MAX_SHIFT_DAYS = 3

#: Below this a fragment is too short to be worth testing for uniqueness.
MIN_PARTIAL_LEN = 6


@dataclass(frozen=True)
class _Agreement:
    partial: str
    completion: str


def find_matches(
    events: Sequence[TransactionEvent], *, index: BlockIndex, cfg: Config
) -> StageOutput:
    """Pair blocked candidates whose amount and partial reference both agree."""
    by_id: Mapping[str, TransactionEvent] = {e.event_id: e for e in events}
    prefixes = PrefixIndex(value for event in events for value in reference_values(event))

    matches: list[StageMatch] = []
    abstained: list[str] = []
    ambiguous_fragments = 0

    for left_id, right_id in candidate_pairs(index, by_id):
        left, right = by_id[left_id], by_id[right_id]
        days = abs(left.effective_date.toordinal() - right.effective_date.toordinal())
        if not 1 <= days <= MAX_SHIFT_DAYS:
            continue

        delta = left.amount_paise - right.amount_paise
        basis = max(abs(left.amount_paise), abs(right.amount_paise))
        if abs(delta) > tolerance_terms(basis, 1, cfg).value:
            continue

        agreement = _partial_agreement(left, right, prefixes)
        if agreement is None:
            if _shares_a_fragment(left, right):
                ambiguous_fragments += 1
                abstained.append(left_id)
            continue

        matches.append(
            StageMatch(
                stage="date_shift",
                group_key=f"date_shift:{agreement.completion}",
                event_ids=(left_id, right_id),
                base_confidence=BASE_CONFIDENCE - _PENALTY_PER_DAY * Decimal(days),
                fields_agreed=("amount_paise", "reference_prefix"),
                fields_disagreed=("effective_date",),
                arithmetic=(
                    f"partial reference {agreement.partial!r} completes uniquely to "
                    f"{agreement.completion!r}; amounts agree within tolerance "
                    f"{days} day(s) apart"
                ),
                delta_paise=delta,
                amount_basis_paise=basis,
                date_shift_days=days,
                candidates_considered=1,
            )
        )

    return StageOutput(
        matches=tuple(matches),
        abstained=tuple(sorted(set(abstained))),
        diagnostics={"ambiguous_reference_fragments": ambiguous_fragments},
    )


def _partial_agreement(
    left: TransactionEvent, right: TransactionEvent, prefixes: PrefixIndex
) -> _Agreement | None:
    """The shorter reference completes uniquely to the longer one, or ``None``."""
    for a in reference_values(left):
        for b in reference_values(right):
            short, long = (a, b) if len(a) <= len(b) else (b, a)
            if len(short) < MIN_PARTIAL_LEN or not long.startswith(short):
                continue
            if short == long:
                # Identical references, which stage 1 would already have joined
                # unless one of them was withheld as truncated.
                return _Agreement(partial=short, completion=long)
            if prefixes.unique_completion(short) == long:
                return _Agreement(partial=short, completion=long)
    return None


def _shares_a_fragment(left: TransactionEvent, right: TransactionEvent) -> bool:
    """A prefix relationship existed but was not discriminating.

    Recorded separately from "no relationship at all" so the eval report can
    show how often the uniqueness rule is what held a match back.
    """
    for a in reference_values(left):
        for b in reference_values(right):
            short, long = (a, b) if len(a) <= len(b) else (b, a)
            if len(short) >= MIN_PARTIAL_LEN and long.startswith(short):
                return True
    return False
