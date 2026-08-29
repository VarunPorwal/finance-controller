"""Priority score — PRD §6.8.

Five weighted terms, all ``Decimal``: an exception's rank in the queue is a
sort key, not a financial figure, but it is still computed without float so a
seeded run stays byte-identical (CLAUDE.md hard rule 9) down to the ordering
a human sees.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fc.models.exception_ import Tier

__all__ = ["deadline_urgency", "priority_score"]

_AMOUNT_WEIGHT = Decimal("0.40")
_TIER_WEIGHT_FACTOR = Decimal("0.25")
_CONFIDENCE_WEIGHT = Decimal("0.15")
_DEADLINE_WEIGHT = Decimal("0.15")
_CLUSTER_WEIGHT = Decimal("0.05")

_LOG_DIVISOR = Decimal(9)  # log10 of a ~₹100cr amount, so the term saturates near 1
_TIER_WEIGHT: dict[Tier, Decimal] = {
    "escalate": Decimal(1),
    "monitor": Decimal("0.4"),
    "auto": Decimal(0),
}

#: "1.0 if <48h" -> inside 2 days. "linear decay to 0 at 30d".
_URGENT_DAYS = Decimal(2)
_ZERO_DAYS = Decimal(30)
_CLUSTER_SATURATION = Decimal(20)

_QUANT = Decimal("0.0001")


def deadline_urgency(deadline: date | None, *, as_of: date) -> Decimal:
    """1.0 inside 48 hours of the deadline (or past it), decaying linearly to
    0.0 at 30 days out. 0.0 when there is no deadline at all."""
    if deadline is None:
        return Decimal(0)
    days_remaining = Decimal((deadline - as_of).days)
    if days_remaining <= _URGENT_DAYS:
        return Decimal(1)
    if days_remaining >= _ZERO_DAYS:
        return Decimal(0)
    span = _ZERO_DAYS - _URGENT_DAYS
    return (Decimal(1) - (days_remaining - _URGENT_DAYS) / span).quantize(_QUANT)


def priority_score(
    *,
    amount_paise: int,
    tier: Tier,
    confidence: Decimal,
    deadline: date | None,
    as_of: date,
    cluster_size: int,
) -> Decimal:
    """§6.8's weighted score, clamped to [0, 1] so it stays a comparable rank
    across every exception the pipeline ever produces, including a settlement
    larger than the ~₹100cr the log term was calibrated against."""
    amount_ratio = min(Decimal(abs(amount_paise) + 1).log10() / _LOG_DIVISOR, Decimal(1))
    amount_term = _AMOUNT_WEIGHT * amount_ratio
    tier_term = _TIER_WEIGHT_FACTOR * _TIER_WEIGHT[tier]
    confidence_term = _CONFIDENCE_WEIGHT * (Decimal(1) - confidence)
    deadline_term = _DEADLINE_WEIGHT * deadline_urgency(deadline, as_of=as_of)
    cluster_ratio = Decimal(max(cluster_size, 0)) / _CLUSTER_SATURATION
    cluster_term = _CLUSTER_WEIGHT * min(cluster_ratio, Decimal(1))

    total = amount_term + tier_term + confidence_term + deadline_term + cluster_term
    return min(total, Decimal(1)).quantize(_QUANT)
