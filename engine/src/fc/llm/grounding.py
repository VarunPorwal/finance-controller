"""``sql_narrate``'s downstream check — PRD §7.1: the model never states a
number it did not receive from a query.

``sql_narrate`` is handed a list of already-computed facts (rendered from SQL
rows or a run diff, never by the model) and asked to phrase them as prose. A
narration is *grounded* when every number it states can be traced back,
digit for digit, to a number already present in the facts it was given —
checked here, deterministically, after the call returns. An ungrounded
narration is discarded by the caller (``client.reject``, never cached) and
the deterministic fallback answer is used instead; see
``fc.llm.schemas.HAS_DOWNSTREAM_CHECK``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation

__all__ = ["is_grounded", "numbers_in"]

#: A currency amount, a percentage, or a bare number — never a token mixed
#: with letters (an exception id like ``exc_01J8X4`` must never be treated as
#: a number, or a real id would falsely fail grounding, or worse, falsely
#: pass it).
_NUMBER = re.compile(r"(?<![A-Za-z0-9_])₹?\d[\d,]*(?:\.\d+)?%?(?![A-Za-z0-9_])")


def numbers_in(text: str) -> set[Decimal]:
    """Every distinct numeral in ``text``, as exact :class:`Decimal` values —
    ``₹1,24,500.00`` and ``124500`` and ``124,500.00`` all normalise to the
    same value, which is the point: formatting differs, the number must not.
    """
    out: set[Decimal] = set()
    for match in _NUMBER.finditer(text):
        raw = match.group().lstrip("₹").rstrip("%").replace(",", "")
        try:
            out.add(Decimal(raw))
        except InvalidOperation:
            continue
    return out


def is_grounded(narrative: str, facts: Sequence[str]) -> bool:
    """Every number ``narrative`` states must appear among the numbers in
    ``facts``. An empty narration is trivially grounded (nothing to check);
    a narration with numbers but no facts to have drawn them from is not.
    """
    stated = numbers_in(narrative)
    if not stated:
        return True
    available = numbers_in(" ".join(facts))
    return stated.issubset(available)
