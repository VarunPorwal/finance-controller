"""Deduction stack evaluation — PRD §6.7.

Bases **chain**. A deduction's basis is ``gross``, ``net``, or the *type* of a
deduction computed earlier in the same list, and that is the whole reason
``gst_on_fee`` is computable at all: GST is 18% of the commission, not 18% of
the sale. Order within the list is therefore significant, and swapping two lines
is a different rule, not the same rule written differently.

``net`` is live: it is gross minus everything deducted *so far*, so a reserve
levied on ``net`` after MDR is a smaller number than the same rate on ``net``
before it. This is the behaviour a real settlement has and the reason the PRD
puts ``net`` in the basis vocabulary at all.

``Decimal`` for every intermediate, ``ROUND_HALF_UP`` to integer paise per line,
never on the total. Razorpay rounds per transaction and sums, so rounding the
sum instead would disagree with the source data by a few paise on every batch —
the drift the §6.5 tolerance term exists to absorb. No ``float``, no ``round()``:
``fc/rules`` sits inside the AST money scan in ``tests/unit/test_architecture.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from fc.models.money import fmt_inr
from fc.models.rule import Deduction, DeductionStackItem

__all__ = ["Stack", "UnknownBasisError", "evaluate_deductions"]

_HUNDRED = Decimal(100)
_WHOLE = Decimal(1)


class UnknownBasisError(ValueError):
    """A deduction naming a basis nothing has published yet.

    Normally caught at load (:mod:`fc.rules.loader` validates the chain), so
    reaching this means a ``Rule`` was constructed in code rather than read from
    a file. It raises rather than defaulting to zero: a basis that silently
    evaluates to nothing produces a rule that explains less than it claims, and
    an under-explaining rule leaves a residual that looks like a real finding.
    """


@dataclass(frozen=True)
class Stack:
    """One evaluated deduction stack.

    ``computed`` is the §6.7 basis map — ``gross``, ``net`` and every deduction
    type by name — kept so a later line's basis can be looked up and so the
    evidence pack can show which number each rate was applied to.
    """

    gross_paise: int
    items: tuple[DeductionStackItem, ...]
    total_paise: int
    computed: Mapping[str, int]

    @property
    def net_paise(self) -> int:
        return self.gross_paise - self.total_paise

    @property
    def exceeds_gross(self) -> bool:
        """Whether the stack deducts more than the money it was deducted from.

        Reachable with a fixed fee on a tiny settlement, which is a real thing
        that happens. :mod:`fc.rules.apply` declines such a rule rather than
        letting it explain money that never existed.
        """
        return self.total_paise > self.gross_paise

    def format_arithmetic(self) -> str:
        """The stack rendered for a human, one line per deduction."""
        if not self.items:
            return f"{fmt_inr(self.gross_paise)} gross, no deductions"
        parts = [
            f"{item.type} {_rate_text(item.rate)}% of {item.basis} "
            f"{fmt_inr(item.basis_paise)} = {fmt_inr(item.amount_paise)}"
            for item in self.items
        ]
        return (
            f"{fmt_inr(self.gross_paise)} gross: "
            + "; ".join(parts)
            + f"; total {fmt_inr(self.total_paise)}, net {fmt_inr(self.net_paise)}"
        )


def evaluate_deductions(deductions: Sequence[Deduction], gross_paise: int) -> Stack:
    """Evaluate a deduction list against one gross amount (§6.7).

    ``gross_paise`` is taken as a magnitude: a settlement's gross is the money
    that moved, and a debit leg expressed as a negative must not invert every
    rate in the stack.
    """
    gross = abs(gross_paise)
    computed: dict[str, int] = {"gross": gross, "net": gross}
    items: list[DeductionStackItem] = []
    total = 0

    for deduction in deductions:
        if deduction.basis not in computed:
            raise UnknownBasisError(
                f"deduction {deduction.type!r} names basis {deduction.basis!r}, which no "
                f"earlier line published (available: {sorted(computed)})"
            )
        basis_paise = computed[deduction.basis]
        amount = _paise(Decimal(basis_paise) * deduction.rate / _HUNDRED)
        if deduction.fixed_paise:
            amount += deduction.fixed_paise
        computed[deduction.type] = amount
        total += amount
        computed["net"] = gross - total
        items.append(
            DeductionStackItem(
                type=deduction.type,
                basis=deduction.basis,
                basis_paise=basis_paise,
                rate=deduction.rate,
                amount_paise=amount,
            )
        )

    return Stack(gross_paise=gross, items=tuple(items), total_paise=total, computed=dict(computed))


def _paise(value: Decimal) -> int:
    return int(value.quantize(_WHOLE, rounding=ROUND_HALF_UP))


def _rate_text(rate: Decimal) -> str:
    return format(rate.normalize(), "f")
