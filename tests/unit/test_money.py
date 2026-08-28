"""Money is integer paise. These tests are the enforcement, not documentation.

The AST scan at the bottom is the one that matters most: it prevents the most
expensive class of bug in this system by making a float in the money path a
test failure rather than a rounding drift someone notices in December.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fc.models.money import already_paise, fmt_inr, to_paise

ENGINE_SRC = Path(__file__).resolve().parents[2] / "engine" / "src"
MONEY_MODULE = ENGINE_SRC / "fc" / "models" / "money.py"


@given(st.integers(min_value=0, max_value=10**10))
def test_paise_roundtrip(paise: int) -> None:
    assert to_paise(fmt_inr(paise)) == paise


@given(st.integers(min_value=-(10**10), max_value=10**10))
def test_paise_roundtrip_signed(paise: int) -> None:
    assert to_paise(fmt_inr(paise)) == paise


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1234.50", 123450),
        ("0.00", 0),
        ("0.01", 1),
        ("1,24,500.00", 12450000),  # Indian digit grouping
        ("1,24,500", 12450000),  # no decimal part
        ("(-)1,24,500.00", -12450000),  # Tally negative prefix
        ("(1,234.00)", -123400),  # parenthesised negative
        ("₹1,24,500.00", 12450000),
        ("-₹1,234.00", -123400),
        ("  1,000.00  ", 100000),
        ("INR 1,000.00", 100000),
    ],
)
def test_to_paise_formats(text: str, expected: int) -> None:
    assert to_paise(text) == expected


def test_to_paise_rounds_half_up() -> None:
    assert to_paise(Decimal("99.995")) == 10000
    assert to_paise("0.005") == 1
    assert to_paise("0.004") == 0


@pytest.mark.parametrize("value", [100000, 0, -1, True])
def test_to_paise_rejects_int(value: Any) -> None:
    """A bare int is ambiguous between rupees and paise. Callers must say which."""
    with pytest.raises(TypeError):
        to_paise(value)


def test_to_paise_rejects_float() -> None:
    with pytest.raises(TypeError):
        to_paise(1234.5)  # type: ignore[arg-type]


@pytest.mark.parametrize("text", ["", "   ", "abc", "12.3.4", "1,2a4.00", "--5"])
def test_to_paise_rejects_junk(text: str) -> None:
    with pytest.raises(ValueError):
        to_paise(text)


@pytest.mark.parametrize(
    ("paise", "expected"),
    [
        (0, "₹0.00"),
        (5, "₹0.05"),
        (100000, "₹1,000.00"),
        (12450000, "₹1,24,500.00"),
        (10**10, "₹10,00,00,000.00"),
        (-123400, "-₹1,234.00"),
    ],
)
def test_fmt_inr(paise: int, expected: str) -> None:
    assert fmt_inr(paise) == expected


def test_already_paise_passes_through() -> None:
    assert already_paise(12450000) == 12450000


@pytest.mark.parametrize("value", ["12450000", 124.5, True])
def test_already_paise_rejects_non_int(value: Any) -> None:
    with pytest.raises(TypeError):
        already_paise(value)


def test_no_float_in_money_module() -> None:
    """AST scan: no float literal and no float() cast anywhere in money.py."""
    tree = ast.parse(MONEY_MODULE.read_text(encoding="utf-8"), filename=str(MONEY_MODULE))
    offences: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offences.append(f"float literal {node.value!r} at line {node.lineno}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"float", "round"}
        ):
            offences.append(f"{node.func.id}() call at line {node.lineno}")
    assert offences == [], f"{MONEY_MODULE.name}: " + "; ".join(offences)
