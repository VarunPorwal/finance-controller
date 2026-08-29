"""Priority score — PRD §6.8. Weighted, deterministic ranking."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fc.exceptions.priority import deadline_urgency, priority_score

_TODAY = date(2026, 8, 29)


def test_deadline_urgency_is_one_with_no_room_left() -> None:
    assert deadline_urgency(_TODAY, as_of=_TODAY) == Decimal(1)
    assert deadline_urgency(_TODAY + timedelta(days=2), as_of=_TODAY) == Decimal(1)


def test_deadline_urgency_decays_to_zero_at_thirty_days() -> None:
    assert deadline_urgency(_TODAY + timedelta(days=30), as_of=_TODAY) == Decimal(0)
    assert deadline_urgency(_TODAY + timedelta(days=365), as_of=_TODAY) == Decimal(0)


def test_deadline_urgency_is_zero_with_no_deadline() -> None:
    assert deadline_urgency(None, as_of=_TODAY) == Decimal(0)


def test_deadline_urgency_falls_monotonically_between_the_endpoints() -> None:
    near = deadline_urgency(_TODAY + timedelta(days=5), as_of=_TODAY)
    far = deadline_urgency(_TODAY + timedelta(days=20), as_of=_TODAY)
    assert Decimal(0) < far < near < Decimal(1)


def test_priority_ranks_a_larger_amount_higher_all_else_equal() -> None:
    small = priority_score(
        amount_paise=10_000_00,
        tier="escalate",
        confidence=Decimal("0.5"),
        deadline=None,
        as_of=_TODAY,
        cluster_size=0,
    )
    large = priority_score(
        amount_paise=50_00_000_00,
        tier="escalate",
        confidence=Decimal("0.5"),
        deadline=None,
        as_of=_TODAY,
        cluster_size=0,
    )
    assert large > small


def test_priority_ranks_escalate_above_monitor_above_auto() -> None:
    def score(tier: str) -> Decimal:
        return priority_score(
            amount_paise=1_00_000_00,
            tier=tier,
            confidence=Decimal("0.8"),  # type: ignore[arg-type]
            deadline=None,
            as_of=_TODAY,
            cluster_size=0,
        )

    assert score("escalate") > score("monitor") > score("auto")


def test_priority_ranks_an_imminent_deadline_above_a_distant_one() -> None:
    def score(deadline: date | None) -> Decimal:
        return priority_score(
            amount_paise=1_00_000_00,
            tier="escalate",
            confidence=Decimal("0.8"),
            deadline=deadline,
            as_of=_TODAY,
            cluster_size=0,
        )

    assert score(_TODAY + timedelta(days=1)) > score(_TODAY + timedelta(days=25)) > score(None)


def test_priority_is_never_negative_and_the_best_case_is_the_floor() -> None:
    worst = priority_score(
        amount_paise=10_00_00_00_00,
        tier="escalate",
        confidence=Decimal(0),
        deadline=_TODAY,
        as_of=_TODAY,
        cluster_size=1000,
    )
    best = priority_score(
        amount_paise=0,
        tier="auto",
        confidence=Decimal(1),
        deadline=None,
        as_of=_TODAY,
        cluster_size=0,
    )
    assert best == Decimal(0)
    assert best <= worst


def test_priority_stays_clamped_to_one_however_large_the_amount() -> None:
    absurd = priority_score(
        amount_paise=10_00_00_00_00_00_00,  # far past the ~₹100cr calibration point
        tier="escalate",
        confidence=Decimal(0),
        deadline=_TODAY,
        as_of=_TODAY,
        cluster_size=1000,
    )
    assert absurd == Decimal(1)
