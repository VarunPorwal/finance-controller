"""Tolerance model — PRD §6.5.

Three terms, and the third is the one that matters. Razorpay computes MDR per
transaction and rounds each one, so a batch settlement's fee total carries a few
paise of drift against any fee recomputed on the batch total. ``n_txns *
rounding_drift_paise`` absorbs exactly that; without it every batch settlement
raises a spurious exception (CLAUDE.md: "Don't remove that term").

Integer paise throughout, ``Decimal`` for the percentage intermediate. No float.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from fc.config import Config

__all__ = ["BindingTerm", "ToleranceTerms", "tolerance_paise", "tolerance_terms"]

BindingTerm = Literal["absolute", "percentage", "rounding_drift"]


@dataclass(frozen=True)
class ToleranceTerms:
    """Each §6.5 term evaluated, plus which one bound.

    ``binding`` exists so the eval report can show that the rounding-drift term
    earns its place rather than asserting that it does.
    """

    absolute_paise: int
    percentage_paise: int
    rounding_drift_paise: int
    binding: BindingTerm
    value: int


def tolerance_terms(amount_paise: int, n_txns: int, cfg: Config) -> ToleranceTerms:
    """Evaluate all three §6.5 terms for one comparison.

    ``amount_paise`` is taken as a magnitude: a debit leg must not produce a
    negative tolerance. ``n_txns`` is the number of transactions composing the
    amount — 1 for a row-to-row comparison, the batch size for a settlement.
    """
    absolute = cfg.tolerance_abs_paise
    percentage = int(Decimal(abs(amount_paise)) * cfg.tolerance_pct)
    drift = max(n_txns, 0) * cfg.rounding_drift_paise

    value = max(absolute, percentage, drift)
    # Ties resolve in §6.5's own order, so the reported binding term is stable.
    binding: BindingTerm = (
        "absolute"
        if value == absolute
        else "percentage"
        if value == percentage
        else "rounding_drift"
    )
    return ToleranceTerms(
        absolute_paise=absolute,
        percentage_paise=percentage,
        rounding_drift_paise=drift,
        binding=binding,
        value=value,
    )


def tolerance_paise(amount_paise: int, n_txns: int, cfg: Config) -> int:
    """The §6.5 tolerance: the largest of the absolute floor, the percentage
    band and the per-transaction rounding drift."""
    return tolerance_terms(amount_paise, n_txns, cfg).value
