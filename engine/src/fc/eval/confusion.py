"""PRD §12.4 confusion matrix — the auto-close decision against ground truth,
scored at pair granularity so it composes with the rest of the pairwise
scoring in :mod:`fc.eval.report`.

|                        | GT: should match | GT: should not match |
|------------------------|-------------------|-----------------------|
| **we auto-closed**     | TP                | FP ← the dangerous cell |
| **we abstained/flagged** | FN              | TN                    |

"We auto-closed" means the pair sits inside a :class:`~fc.models.match.MatchResult`
with ``auto_closed=True`` — nothing else counts, including a match the cascade
formed at lower confidence. That is deliberate: PRD §12.4's table is a
statement about the auto-close *decision*, not about matching in general, so a
correct-but-non-auto match is scored as an abstention here even though
``fc.eval.report``'s own precision/recall (over *all* predicted pairs) counts
it as a hit.

``TN`` is not sampled: with a 500-record corpus, ``C(500, 2)`` is small enough
(~124k) to hold exactly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

from fc.models.match import MatchResult

__all__ = ["ConfusionMatrix", "confusion_matrix", "ratio"]


def ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal(0)
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


@dataclass(frozen=True)
class ConfusionMatrix:
    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision_auto(self) -> Decimal:
        return ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> Decimal:
        return ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> Decimal:
        p, r = self.precision_auto, self.recall
        if p + r == 0:
            return Decimal(0)
        return ((2 * p * r) / (p + r)).quantize(Decimal("0.0001"))

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.fn + self.tn


def confusion_matrix(
    event_ids: Sequence[str],
    matches: Sequence[MatchResult],
    group_of: Mapping[str, str | None],
) -> ConfusionMatrix:
    """Build the table over every pair of ``event_ids``.

    ``group_of`` maps an event id to its ``gt_match_group`` (``None`` when
    ground truth says it belongs to no group, e.g. a genuine exception).
    """
    total_pairs = len(event_ids) * (len(event_ids) - 1) // 2

    sizes: dict[str, int] = {}
    for event_id in event_ids:
        group = group_of.get(event_id)
        if group is not None:
            sizes[group] = sizes.get(group, 0) + 1
    true_pairs = sum(n * (n - 1) // 2 for n in sizes.values())

    tp = 0
    auto_pairs = 0
    for match in matches:
        if not match.auto_closed:
            continue
        for left, right in combinations(sorted(match.event_ids), 2):
            auto_pairs += 1
            left_group, right_group = group_of.get(left), group_of.get(right)
            if left_group is not None and left_group == right_group:
                tp += 1

    fp = auto_pairs - tp
    fn = true_pairs - tp
    tn = total_pairs - tp - fp - fn
    return ConfusionMatrix(tp=tp, fp=fp, fn=fn, tn=tn)
