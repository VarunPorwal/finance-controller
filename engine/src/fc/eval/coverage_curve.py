"""PRD §12.4 coverage-precision curve.

Sweeps ``cfg.auto_threshold`` from 0.70 to 1.00 in 0.01 steps and re-runs the
cascade at each point — the threshold is the only knob :func:`fc.matching.cascade.run_cascade`
reads to decide ``auto_closed`` (``fc/matching/cascade.py`` line ~406), so a
sweep is a re-run, not a re-derivation from one run's confidences. 31 re-runs
over a 500-row corpus is well inside the eval suite's own latency budget.

At each threshold: coverage (share of events sitting in an auto-closed
match), pairwise precision on the auto-closed set (:mod:`fc.eval.confusion`),
false positives, and abstentions (events not auto-closed). The shipped
threshold and its rationale are printed by :func:`fc.eval.report.render`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from fc.config import Config
from fc.eval.confusion import confusion_matrix, ratio
from fc.matching.cascade import run_cascade
from fc.models.transaction import TransactionEvent

__all__ = ["CoveragePoint", "STEP", "START", "STOP", "sweep"]

START = Decimal("0.70")
STOP = Decimal("1.00")
STEP = Decimal("0.01")


@dataclass(frozen=True)
class CoveragePoint:
    threshold: Decimal
    coverage: Decimal
    precision: Decimal
    false_positives: int
    abstentions: int


def sweep(
    events: Sequence[TransactionEvent],
    group_of: Mapping[str, str | None],
    *,
    cfg: Config,
    run_id: str,
    tenant_id: str,
    issue_id: Callable[[str], str],
    created_at: datetime,
) -> tuple[CoveragePoint, ...]:
    event_ids = [event.event_id for event in events]
    points: list[CoveragePoint] = []
    threshold = START
    while threshold <= STOP:
        run_cfg = cfg.model_copy(update={"auto_threshold": threshold})
        result = run_cascade(
            events,
            cfg=run_cfg,
            run_id=run_id,
            tenant_id=tenant_id,
            issue_id=issue_id,
            created_at=created_at,
        )
        auto_closed_ids = {e for m in result.matches if m.auto_closed for e in m.event_ids}
        cm = confusion_matrix(event_ids, result.matches, group_of)
        points.append(
            CoveragePoint(
                threshold=threshold,
                coverage=ratio(len(auto_closed_ids), len(event_ids)),
                precision=cm.precision_auto,
                false_positives=cm.fp,
                abstentions=len(event_ids) - len(auto_closed_ids),
            )
        )
        threshold = (threshold + STEP).quantize(STEP)
    return tuple(points)


def render(points: Sequence[CoveragePoint], *, shipped: Decimal) -> str:
    """A plot needs a chart library; a table read top to bottom is the ASCII
    equivalent and needs nothing but a terminal."""
    lines = ["", "Coverage-precision curve (PRD 12.4) — auto_threshold sweep 0.70-1.00", ""]
    header = f"  {'threshold':>9}  {'coverage':>8}  {'precision':>9}  {'FP':>5}  {'abstain':>7}"
    lines.append(header)
    for point in points:
        marker = "  <- shipped" if point.threshold == shipped else ""
        lines.append(
            f"  {point.threshold:>9}  {point.coverage * 100:>7.2f}%  "
            f"{point.precision * 100:>8.2f}%  {point.false_positives:>5}  "
            f"{point.abstentions:>7}{marker}"
        )
    lines.append("")
    return "\n".join(lines)
