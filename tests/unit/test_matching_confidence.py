"""§6.6 keeps every factor, stays inside [0, 1], and never emits more than 4 dp.

Four places is not cosmetic: ``matches.confidence`` is ``Numeric(5, 4)``, so a
fifth place would be truncated by Postgres and the stored number would stop
matching the arithmetic shown beside it.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from fc.matching.confidence import ConfidenceInputs, cap_for_stage, derive
from fc.models.match import FUZZY_CONFIDENCE_CAP

_QUANTUM = Decimal("0.0001")


def _inputs(**overrides: object) -> ConfidenceInputs:
    base = ConfidenceInputs(
        stage="exact_ref",
        base=Decimal("1.00"),
        fields_agreed=1,
        fields_disagreed=0,
        amount_delta_paise=0,
        amount_basis_paise=0,
        days_shift=0,
        n_candidates=1,
        distinct_sources=2,
    )
    return ConfidenceInputs(**{**base.__dict__, **overrides})


def test_a_clean_exact_match_scores_one() -> None:
    assert derive(_inputs()).derivation.result == Decimal("1.0000")


def test_every_factor_is_stored_not_just_the_result() -> None:
    d = derive(
        _inputs(
            base=Decimal("0.92"),
            fields_agreed=3,
            fields_disagreed=1,
            amount_delta_paise=50,
            amount_basis_paise=1000,
            days_shift=2,
            n_candidates=2,
            distinct_sources=3,
        )
    ).derivation
    assert d.base_stage_confidence == Decimal("0.9200")
    assert d.field_agreement_factor == Decimal("0.7500")
    assert d.amount_delta_ratio == Decimal("0.0500")
    assert d.date_penalty == Decimal("0.9600")
    assert d.ambiguity_penalty == Decimal("0.5000")
    assert d.source_coverage_bonus == Decimal("1.0500")


def test_disagreement_lowers_the_field_agreement_factor() -> None:
    agree = derive(_inputs(fields_agreed=2, fields_disagreed=0)).derivation.result
    disagree = derive(_inputs(fields_agreed=2, fields_disagreed=2)).derivation.result
    assert disagree < agree


def test_a_date_shift_costs_two_points_a_day() -> None:
    assert derive(_inputs(days_shift=3)).derivation.date_penalty == Decimal("0.9400")


def test_no_agreement_or_disagreement_leaves_the_factor_at_one() -> None:
    assert derive(
        _inputs(fields_agreed=0, fields_disagreed=0)
    ).derivation.field_agreement_factor == Decimal("1.0000")


def test_the_three_way_bonus_only_applies_with_three_sources() -> None:
    assert derive(_inputs(distinct_sources=2)).derivation.source_coverage_bonus == Decimal("1.0000")
    assert derive(_inputs(distinct_sources=3)).derivation.source_coverage_bonus == Decimal("1.0500")


def test_the_bonus_is_not_load_bearing_when_the_product_already_clamps() -> None:
    """A 1.05 multiplier on a value that is already 1.0 changes nothing."""
    outcome = derive(_inputs(base=Decimal("1.00"), distinct_sources=3))
    assert outcome.derivation.result == Decimal("1.0000")
    assert outcome.bonus_was_load_bearing is False


def test_the_bonus_is_load_bearing_when_it_actually_moves_the_number() -> None:
    outcome = derive(_inputs(base=Decimal("0.80"), distinct_sources=3))
    assert outcome.bonus_was_load_bearing is True


def test_fuzzy_is_capped_by_assertion_whatever_it_scores() -> None:
    assert cap_for_stage("fuzzy", Decimal("0.99")) == FUZZY_CONFIDENCE_CAP
    assert cap_for_stage("exact_ref", Decimal("0.99")) == Decimal("0.99")


@given(
    base=st.decimals(min_value=0, max_value=1, places=2),
    agreed=st.integers(min_value=0, max_value=8),
    disagreed=st.integers(min_value=0, max_value=8),
    delta=st.integers(min_value=-(10**9), max_value=10**9),
    basis=st.integers(min_value=0, max_value=10**9),
    days=st.integers(min_value=0, max_value=90),
    candidates=st.integers(min_value=1, max_value=50),
    sources=st.integers(min_value=1, max_value=3),
)
def test_confidence_is_always_a_four_place_decimal_in_the_unit_interval(
    base: Decimal,
    agreed: int,
    disagreed: int,
    delta: int,
    basis: int,
    days: int,
    candidates: int,
    sources: int,
) -> None:
    result = derive(
        ConfidenceInputs(
            stage="exact_ref",
            base=Decimal(base),
            fields_agreed=agreed,
            fields_disagreed=disagreed,
            amount_delta_paise=delta,
            amount_basis_paise=basis,
            days_shift=days,
            n_candidates=candidates,
            distinct_sources=sources,
        )
    ).derivation.result
    assert Decimal(0) <= result <= Decimal(1)
    assert result == result.quantize(_QUANTUM)
