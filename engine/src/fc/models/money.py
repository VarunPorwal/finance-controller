"""Money conversion and display. Integer paise only — PRD §6.1, hard rule 1.

There is no float in this module and there must never be one: an AST scan in
``tests/unit/test_money.py`` asserts it. All intermediate arithmetic is
``Decimal`` with ``ROUND_HALF_UP``; all stored and returned money is ``int``
paise.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

__all__ = ["RUPEE", "already_paise", "fmt_inr", "to_paise"]

RUPEE = "₹"

_TWO_PLACES = Decimal("0.01")
_PAISE_PER_RUPEE = 100

# Compiled at module level, never per row (CLAUDE.md conventions).
_NUMERIC = re.compile(r"\d+(?:\.\d+)?")
_SYMBOLS = re.compile(r"(?:₹|INR|Rs\.?)", re.IGNORECASE)
# Commas, ASCII space, non-breaking space, narrow no-break space, underscore.
_SEPARATORS = str.maketrans("", "", ",   _")


def to_paise(value: str | Decimal) -> int:
    """Convert a rupee-denominated amount to integer paise.

    Handles plain decimal strings, Indian digit grouping, an optional rupee
    symbol, the Tally ``(-)`` negative prefix and parenthesised negatives::

        to_paise("1234.50")           ->   123450
        to_paise("1,24,500.00")       -> 12450000
        to_paise("(-)1,24,500.00")    -> -12450000
        to_paise("(1,234.00)")        ->  -123400
        to_paise(Decimal("99.995"))   ->    10000   (ROUND_HALF_UP)

    A bare ``int`` is rejected. "1000" as rupees and 1000 as paise are the same
    value written two ways and there is no safe default, so the unit is never
    inferred: pass a ``str`` or ``Decimal`` for rupees, or call
    :func:`already_paise` for a value that is paise already. Razorpay amounts
    arrive as paise and go through :func:`already_paise` (PRD §6.1); bank and
    Tally amounts are rupee strings and come here.
    """
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, str):
        amount = _parse_rupee_string(value)
    else:
        raise TypeError(
            f"to_paise() takes a rupee str or Decimal, got {type(value).__name__}. "
            "For a value that is already integer paise, use already_paise()."
        )
    return int(amount.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP) * _PAISE_PER_RUPEE)


def already_paise(value: int) -> int:
    """Validate and pass through a value that is integer paise already.

    Razorpay settlement and payment amounts are integer paise at the source and
    must not be run through :func:`to_paise`. This exists so that fact is
    explicit at the call site rather than implied by an argument's type.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"already_paise() takes an int, got {type(value).__name__}")
    return value


def fmt_inr(paise: int) -> str:
    """Format integer paise for display with Indian digit grouping.

        fmt_inr(12450000)   -> "₹1,24,500.00"
        fmt_inr(-123400)    -> "-₹1,234.00"

    ``to_paise(fmt_inr(n)) == n`` for every int ``n``.
    """
    if isinstance(paise, bool) or not isinstance(paise, int):
        raise TypeError(f"fmt_inr() takes an int, got {type(paise).__name__}")
    sign = "-" if paise < 0 else ""
    rupees, remainder = divmod(abs(paise), _PAISE_PER_RUPEE)
    return f"{sign}{RUPEE}{_group_indian(str(rupees))}.{remainder:02d}"


def _parse_rupee_string(raw: str) -> Decimal:
    text = _SYMBOLS.sub("", raw).strip()
    if not text:
        raise ValueError(f"empty amount: {raw!r}")

    negative = False
    if text.startswith("(-)"):
        negative, text = True, text[3:]
    elif text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    elif text.startswith("-"):
        negative, text = True, text[1:]
    elif text.startswith("+"):
        text = text[1:]

    text = text.translate(_SEPARATORS)
    if _NUMERIC.fullmatch(text) is None:
        raise ValueError(f"not a rupee amount: {raw!r}")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover — guarded by the regex
        raise ValueError(f"not a rupee amount: {raw!r}") from exc
    return -amount if negative else amount


def _group_indian(digits: str) -> str:
    """Last three digits, then pairs: 124500 -> 1,24,500."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.append(head[-2:])
        head = head[:-2]
    if head:
        groups.append(head)
    return ",".join(reversed(groups)) + "," + tail
