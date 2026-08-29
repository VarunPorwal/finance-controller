"""The deduction stack chains bases, and order within it is significant.

``gst_on_fee`` is the case the whole design exists for: GST is 18% of the
commission, not 18% of the sale, so its basis is ``commission`` and it can only
be computed after the line that publishes that name.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fc.models.rule import Deduction
from fc.rules.evaluator import UnknownBasisError, evaluate_deductions

BLINKIT = (
    Deduction(type="commission", basis="gross", rate=Decimal("18")),
    Deduction(type="gst_on_fee", basis="commission", rate=Decimal("18")),
    Deduction(type="tds_194o", basis="gross", rate=Decimal("1")),
)


def test_gst_is_charged_on_the_commission_not_on_the_gross() -> None:
    stack = evaluate_deductions(BLINKIT, 1_00_000_00)
    by_type = {item.type: item for item in stack.items}
    assert by_type["commission"].amount_paise == 18_000_00
    assert by_type["gst_on_fee"].basis_paise == 18_000_00
    assert by_type["gst_on_fee"].amount_paise == 3_240_00
    assert by_type["tds_194o"].basis_paise == 1_00_000_00
    assert stack.total_paise == 22_240_00
    assert stack.net_paise == 77_760_00


def test_the_basis_map_publishes_every_line_by_name() -> None:
    stack = evaluate_deductions(BLINKIT, 1_00_000_00)
    assert stack.computed["gross"] == 1_00_000_00
    assert stack.computed["commission"] == 18_000_00
    assert stack.computed["net"] == 77_760_00


def test_net_is_live_so_a_later_rate_sees_the_smaller_base() -> None:
    """A reserve on ``net`` after MDR is smaller than the same rate before it."""
    after = evaluate_deductions(
        (
            Deduction(type="mdr", basis="gross", rate=Decimal("10")),
            Deduction(type="reserve", basis="net", rate=Decimal("10")),
        ),
        1_00_000_00,
    )
    before = evaluate_deductions(
        (
            Deduction(type="reserve", basis="net", rate=Decimal("10")),
            Deduction(type="mdr", basis="gross", rate=Decimal("10")),
        ),
        1_00_000_00,
    )
    assert after.computed["reserve"] == 9_000_00  # 10% of 90,000
    assert before.computed["reserve"] == 10_000_00  # 10% of the full gross
    assert after.total_paise != before.total_paise


def test_reordering_gross_based_lines_leaves_the_total_alone() -> None:
    """The complement to the test above, so "order matters" is not read too widely.

    Order changes the answer exactly when a later line reads ``net`` or a name an
    earlier line published. Three lines that all read ``gross`` (and one that
    reads a name still present in both orderings) sum the same either way — which
    is why the version hash covers the *sequence*, not a set of rates: it has to
    distinguish the orderings that differ without asserting these ones do.
    """
    forward = evaluate_deductions(BLINKIT, 87_654_32)
    swapped = evaluate_deductions((BLINKIT[2], BLINKIT[0], BLINKIT[1]), 87_654_32)
    assert forward.total_paise == swapped.total_paise
    assert [i.type for i in forward.items] != [i.type for i in swapped.items]


def test_a_basis_naming_a_later_line_is_an_error_not_a_zero() -> None:
    """A silent zero would under-explain, and an under-explaining rule invents a residual."""
    with pytest.raises(UnknownBasisError, match="gst_on_fee"):
        evaluate_deductions(
            (
                Deduction(type="gst_on_fee", basis="commission", rate=Decimal("18")),
                Deduction(type="commission", basis="gross", rate=Decimal("18")),
            ),
            1_00_000_00,
        )


def test_rounding_is_half_up_per_line_never_on_the_total() -> None:
    """Razorpay rounds per transaction and sums; rounding the sum disagrees."""
    stack = evaluate_deductions((Deduction(type="mdr", basis="gross", rate=Decimal("2")),), 12_50)
    assert stack.total_paise == 25  # 2% of 1250 paise = 25 exactly

    half = evaluate_deductions((Deduction(type="mdr", basis="gross", rate=Decimal("1")),), 1_25)
    assert half.total_paise == 1  # 1.25 paise rounds half up


def test_fixed_fees_add_on_top_of_the_rate() -> None:
    stack = evaluate_deductions(
        (Deduction(type="platform_fee", basis="gross", rate=Decimal("1"), fixed_paise=500),),
        1_00_000_00,
    )
    assert stack.total_paise == 1_000_00 + 500


def test_gross_is_taken_as_a_magnitude() -> None:
    """A debit leg expressed as a negative must not invert every rate."""
    assert evaluate_deductions(BLINKIT, -1_00_000_00).total_paise == 22_240_00


def test_an_empty_stack_explains_nothing() -> None:
    stack = evaluate_deductions((), 1_00_000_00)
    assert stack.total_paise == 0
    assert stack.net_paise == 1_00_000_00
    assert not stack.exceeds_gross


def test_a_flat_fee_larger_than_the_settlement_reports_exceeds_gross() -> None:
    """Real: a ₹20 collection fee on a ₹5 settlement. Reported, not clamped."""
    stack = evaluate_deductions(
        (Deduction(type="platform_fee", basis="gross", rate=Decimal("0"), fixed_paise=20_00),),
        5_00,
    )
    assert stack.exceeds_gross


def test_the_blinkit_stack_reads_as_arithmetic_a_human_can_check() -> None:
    text = evaluate_deductions(BLINKIT, 1_00_000_00).format_arithmetic()
    assert "commission 18% of gross ₹1,00,000.00 = ₹18,000.00" in text
    assert "gst_on_fee 18% of commission ₹18,000.00 = ₹3,240.00" in text


# PRD §12.3's property, restated for the rates a loaded rule can carry: the
# loader rejects a stack whose rates total more than 100% of gross, so within
# that bound the stack can never deduct more money than existed.
@given(
    gross=st.integers(min_value=1, max_value=10**10),
    commission=st.decimals(min_value=0, max_value=50, places=2),
    gst=st.decimals(min_value=0, max_value=30, places=2),
    tds=st.decimals(min_value=0, max_value=5, places=2),
)
def test_deduction_stack_never_exceeds_gross(
    gross: int, commission: Decimal, gst: Decimal, tds: Decimal
) -> None:
    stack = evaluate_deductions(
        (
            Deduction(type="commission", basis="gross", rate=commission),
            Deduction(type="gst_on_fee", basis="commission", rate=gst),
            Deduction(type="tds_194o", basis="gross", rate=tds),
        ),
        gross,
    )
    assert stack.total_paise <= gross
    assert stack.net_paise >= 0


@given(
    gross=st.integers(min_value=0, max_value=10**10),
    rate=st.decimals(min_value=0, max_value=100, places=3),
)
def test_every_line_is_an_integer_number_of_paise(gross: int, rate: Decimal) -> None:
    stack = evaluate_deductions((Deduction(type="mdr", basis="gross", rate=rate),), gross)
    assert all(isinstance(item.amount_paise, int) for item in stack.items)
    assert stack.total_paise == sum(item.amount_paise for item in stack.items)
