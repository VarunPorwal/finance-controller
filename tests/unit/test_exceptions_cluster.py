"""Clustering — PRD §6.8. Deterministic membership, cosmetic label."""

from __future__ import annotations

from decimal import Decimal

from fc.exceptions.classify import Classified
from fc.exceptions.cluster import cluster_exceptions, grouping_key


def _classified(
    *,
    category: str = "timing_lag",
    counterparty: str | None = "BLINKIT",
    rail: str | None = None,
    amount: int = 5_000_00,
    residual: int = 0,
) -> Classified:
    return Classified(
        event_ids=(f"e{amount}{residual}",),
        category=category,  # type: ignore[arg-type]
        amount_paise=amount,
        residual_paise=residual,
        reason="test",
        confidence=Decimal("0.8"),
        counterparty_norm=counterparty,
        rail=rail,
        gross_paise=amount,
        gap_paise=residual,
    )


def test_two_items_with_the_same_key_share_one_cluster() -> None:
    items = [_classified(amount=5_000_00), _classified(amount=6_000_00)]

    clusters = cluster_exceptions(items, ["escalate", "monitor"])

    assert len(clusters) == 1
    assert set(clusters[0].member_indices) == {0, 1}
    assert clusters[0].total_paise == 11_000_00


def test_a_singleton_does_not_form_a_cluster() -> None:
    items = [_classified(amount=5_000_00), _classified(counterparty="ZEPTO")]

    clusters = cluster_exceptions(items, ["escalate", "escalate"])

    assert clusters == ()


def test_grouping_key_ignores_amount_within_a_band_but_not_across_bands() -> None:
    small = _classified(amount=5_000_00)
    also_small = _classified(amount=5_500_00)
    large = _classified(amount=50_00_000_00)

    assert grouping_key(small) == grouping_key(also_small)
    assert grouping_key(small) != grouping_key(large)


def test_different_categories_never_share_a_cluster() -> None:
    a = _classified(category="timing_lag")
    b = _classified(category="amount_variance")

    clusters = cluster_exceptions([a, b], ["monitor", "escalate"])

    assert clusters == ()


def test_max_tier_is_the_most_severe_tier_among_members() -> None:
    items = [_classified(amount=1_000_00), _classified(amount=1_100_00)]

    clusters = cluster_exceptions(items, ["auto", "escalate"])

    assert clusters[0].max_tier == "escalate"


def test_clustering_is_a_pure_function_of_its_input() -> None:
    items = [_classified(amount=5_000_00), _classified(amount=6_000_00)]
    tiers = ["escalate", "escalate"]

    first = cluster_exceptions(items, tiers)
    second = cluster_exceptions(items, tiers)

    assert first == second
