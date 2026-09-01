"""Tiering — PRD §6.8. Auto / monitor / escalate.

High confidence alone is never sufficient for a ``NEVER_AUTO`` category. That
check runs first and nothing after it can override the escalate it returns —
this is the single design decision that keeps false auto-resolutions at zero,
and CLAUDE.md is explicit that it must not be softened to raise coverage.

No LLM: this is one of CLAUDE.md hard rule 2's four named decision modules,
enforced by ``tests/unit/test_architecture.py``'s AST scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fc.config import Config
from fc.models.exception_ import AUTO_SAFE, NEVER_AUTO, ExceptionCategory, Tier

__all__ = ["TierDecision", "tier_for"]


@dataclass(frozen=True)
class TierDecision:
    tier: Tier
    recheck_at: datetime | None = None


def tier_for(
    category: ExceptionCategory,
    *,
    confidence: Decimal,
    cfg: Config,
    expected_resolution_date: date | None = None,
    explained_by_rule: bool = True,
) -> TierDecision:
    """§6.8's tiering, verbatim.

    ``category in NEVER_AUTO`` is checked before anything else and returns
    immediately: a 0.99-confidence chargeback still escalates, because the
    category check is not a tie-breaker against confidence, it is a gate that
    confidence never reaches.
    """
    if category in NEVER_AUTO:
        return TierDecision(tier="escalate")

    # An ``amount_variance`` is auto-safe because the Rulebook *shrank* it: the
    # deduction stack explains the gap, the residual is inside tolerance, and
    # the rule version stamped on it is the evidence. A variance nobody applied
    # a rule to is a different animal — a ledger receipt booked ₹2,219.90 above
    # the credit that paid it, say — and it inherited the match group's own
    # confidence of 1.00 and auto-closed on the strength of how well the *bank*
    # and *gateway* agreed, which is not what was being questioned.
    if category == "amount_variance" and not explained_by_rule:
        return TierDecision(tier="escalate")

    if confidence >= cfg.auto_threshold and category in AUTO_SAFE:
        return TierDecision(tier="auto")

    if category == "timing_lag" and expected_resolution_date is not None:
        recheck_at = datetime.combine(expected_resolution_date, time.min, tzinfo=UTC) + timedelta(
            days=1
        )
        return TierDecision(tier="monitor", recheck_at=recheck_at)

    return TierDecision(tier="escalate")
