"""Tiering — PRD §6.8. The gate that keeps false auto-resolutions at zero.

High confidence must never be sufficient for a ``NEVER_AUTO`` category: that
is the whole point of the design, so it gets the most direct test in the
suite.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fc.config import load_config
from fc.exceptions.tier import tier_for
from fc.models.exception_ import AUTO_SAFE, NEVER_AUTO

_CFG = load_config(env_file=None, environ={})


@pytest.mark.parametrize("category", sorted(NEVER_AUTO))
def test_never_auto_escalates_even_at_full_confidence(category: str) -> None:
    decision = tier_for(category, confidence=Decimal("0.99"), cfg=_CFG)
    assert decision.tier == "escalate"
    assert decision.recheck_at is None


@pytest.mark.parametrize("category", sorted(AUTO_SAFE))
def test_auto_safe_above_threshold_auto_closes(category: str) -> None:
    decision = tier_for(category, confidence=_CFG.auto_threshold, cfg=_CFG)
    assert decision.tier == "auto"


@pytest.mark.parametrize("category", sorted(AUTO_SAFE))
def test_auto_safe_below_threshold_does_not_auto_close(category: str) -> None:
    decision = tier_for(category, confidence=_CFG.auto_threshold - Decimal("0.01"), cfg=_CFG)
    assert decision.tier != "auto"


def test_timing_lag_with_a_known_date_monitors_and_reschedules() -> None:
    decision = tier_for(
        "timing_lag",
        confidence=Decimal("0.50"),
        cfg=_CFG,
        expected_resolution_date=date(2026, 8, 29),
    )
    assert decision.tier == "monitor"
    assert decision.recheck_at is not None
    assert decision.recheck_at.date() == date(2026, 8, 30)


def test_timing_lag_without_a_known_date_escalates() -> None:
    decision = tier_for("timing_lag", confidence=Decimal("0.50"), cfg=_CFG)
    assert decision.tier == "escalate"


def test_a_099_confidence_chargeback_still_escalates() -> None:
    """The literal claim in the PRD's tiering section, asserted directly."""
    decision = tier_for("chargeback_unrecorded", confidence=Decimal("0.99"), cfg=_CFG)
    assert decision.tier == "escalate"
