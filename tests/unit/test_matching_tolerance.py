"""The §6.5 tolerance keeps all three terms, and each one can be the binding one.

The rounding-drift term is the one a reader is most likely to think redundant.
It is not: Razorpay rounds MDR per transaction, so a batch's fee total drifts a
few paise from any fee recomputed on the batch total, and removing the term
raises a spurious exception on every batch settlement.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from fc.config import Config, load_config
from fc.matching.tolerance import tolerance_paise, tolerance_terms


def _cfg(**overrides: object) -> Config:
    base = load_config(env_file=None, environ={})
    return base.model_copy(update=overrides)


def test_absolute_floor_binds_for_small_single_transactions() -> None:
    terms = tolerance_terms(50_00, 1, _cfg())
    assert terms.value == 100
    assert terms.binding == "absolute"


def test_percentage_binds_for_large_amounts() -> None:
    terms = tolerance_terms(1_00_00_000, 1, _cfg())
    assert terms.percentage_paise == 5000
    assert terms.binding == "percentage"
    assert terms.value == 5000


def test_rounding_drift_binds_for_a_large_batch() -> None:
    # 500 transactions at 1 paise each beats the 100-paise floor.
    terms = tolerance_terms(1000, 500, _cfg())
    assert terms.rounding_drift_paise == 500
    assert terms.binding == "rounding_drift"
    assert terms.value == 500


def test_all_three_terms_are_always_evaluated() -> None:
    terms = tolerance_terms(2_00_000, 14, _cfg())
    assert terms.absolute_paise == 100
    assert terms.percentage_paise == 100
    assert terms.rounding_drift_paise == 14


def test_removing_the_drift_term_would_change_the_answer() -> None:
    """Guards the term against a future "simplification"."""
    with_drift = tolerance_terms(1000, 500, _cfg()).value
    without_drift = tolerance_terms(1000, 500, _cfg(rounding_drift_paise=0)).value
    assert with_drift == 500
    assert without_drift == 100


def test_a_debit_leg_never_yields_a_negative_tolerance() -> None:
    assert tolerance_paise(-1_00_00_000, 1, _cfg()) == 5000


@given(
    amount=st.integers(min_value=-(10**12), max_value=10**12),
    n_txns=st.integers(min_value=0, max_value=5_000),
)
def test_tolerance_is_at_least_every_term_and_never_negative(amount: int, n_txns: int) -> None:
    cfg = _cfg()
    terms = tolerance_terms(amount, n_txns, cfg)
    assert terms.value >= terms.absolute_paise
    assert terms.value >= terms.percentage_paise
    assert terms.value >= terms.rounding_drift_paise
    assert terms.value > 0


def test_no_float_reaches_the_percentage_term() -> None:
    cfg = _cfg(tolerance_pct=Decimal("0.0005"))
    assert isinstance(tolerance_terms(3_33_333, 1, cfg).percentage_paise, int)
