"""``sql_narrate``'s downstream check — PRD §7.1: the model never states a
number it did not receive from a query."""

from __future__ import annotations

from decimal import Decimal

from fc.llm.grounding import is_grounded, numbers_in


def test_identical_value_grounds_regardless_of_formatting() -> None:
    # Facts are already rendered in the units a reader sees (rupees, via
    # fmt_inr) — the check compares what the narration says to what the
    # facts actually display, not to the underlying paise integer.
    facts = ["total_at_risk_paise: ₹82,401.00"]
    assert is_grounded("Rs 82,401.00 is at risk.", facts)
    assert is_grounded("₹82401 is at risk.", facts)


def test_an_invented_number_is_not_grounded() -> None:
    facts = ["total_at_risk_paise: ₹82,401.00"]
    assert not is_grounded("Rs 90,000 is at risk.", facts)


def test_a_count_must_also_be_present_in_the_facts() -> None:
    facts = ["total_at_risk_paise: ₹82,401.00"]
    # "6 exceptions" states a count the facts never mentioned.
    assert not is_grounded("Rs 82,401.00 is at risk across 6 exceptions.", facts)
    assert is_grounded(
        "Rs 82,401.00 is at risk across 6 exceptions.",
        [*facts, "exception_count: 6"],
    )


def test_exception_ids_are_never_treated_as_numbers() -> None:
    # A real id containing digits must not falsely pass (or fail) grounding.
    assert is_grounded("The largest is exc_01J8X4Q7ZK.", [])


def test_narration_with_no_numbers_is_trivially_grounded() -> None:
    assert is_grounded("Nothing is currently at risk.", [])


def test_numbers_in_deduplicates_and_normalises() -> None:
    # Decimal("124500.00") == Decimal("124500"), so all three collapse to one.
    found = numbers_in("₹1,24,500.00 and 124500 and 124,500")
    assert found == {Decimal("124500")}
    assert len(found) == 1
