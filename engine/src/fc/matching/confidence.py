"""Confidence derivation — PRD §6.6.

Six factors multiplied and clamped. Every one of them is stored on
:class:`fc.models.match.ConfidenceDerivation` so the evidence pack renders the
arithmetic rather than asserting a number. That is the whole point: a system
that shows its working can be argued with, one that prints 0.94 cannot.

``Decimal`` throughout, quantized to four places because ``matches.confidence``
is ``Numeric(5, 4)`` and Postgres would otherwise truncate silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from fc.models.match import FUZZY_CONFIDENCE_CAP, ConfidenceDerivation, MatchStage

__all__ = [
    "DATE_PENALTY_PER_DAY",
    "THREE_WAY_BONUS",
    "ConfidenceInputs",
    "DerivationOutcome",
    "cap_for_stage",
    "derive",
]

#: §6.6: date_penalty = 1 - 0.02 * days_shift.
DATE_PENALTY_PER_DAY = Decimal("0.02")

#: §6.6: source_coverage_bonus, applied only when all three sources are present.
THREE_WAY_BONUS = Decimal("1.05")

_QUANTUM = Decimal("0.0001")
_ONE = Decimal(1)
_ZERO = Decimal(0)


@dataclass(frozen=True)
class ConfidenceInputs:
    """Everything §6.6 needs, gathered by a stage and handed here."""

    #: Needed because the §6.3 per-stage ceiling is applied *inside* :func:`derive`.
    #: Capping afterwards let ``ConfidenceDerivation.result`` disagree with the
    #: confidence actually stored - a fuzzy match would render arithmetic ending
    #: in 0.7875 beside a stated 0.75, which is the exact failure this module
    #: exists to prevent.
    stage: MatchStage
    base: Decimal
    fields_agreed: int
    fields_disagreed: int
    amount_delta_paise: int
    amount_basis_paise: int
    days_shift: int
    n_candidates: int
    distinct_sources: int


@dataclass(frozen=True)
class DerivationOutcome:
    """The derivation, plus whether the three-way bonus actually moved anything.

    A bonus of 1.05 applied to a product that already clamps at 1.0 changes
    nothing, and neither does one applied to a fuzzy score the 0.75 cap then
    erases. ``bonus_was_load_bearing`` compares the two **post-cap** confidences,
    so it reports what the bonus did to the number that is actually stored rather
    than to an intermediate nobody sees.
    """

    derivation: ConfidenceDerivation
    bonus_was_load_bearing: bool


def derive(inputs: ConfidenceInputs) -> DerivationOutcome:
    """Apply §6.6 and keep every factor."""
    agreement = _ratio(inputs.fields_agreed, inputs.fields_agreed + inputs.fields_disagreed)
    delta_ratio = _clamp(_ratio(abs(inputs.amount_delta_paise), abs(inputs.amount_basis_paise), 0))
    date_penalty = _clamp(_ONE - DATE_PENALTY_PER_DAY * Decimal(max(inputs.days_shift, 0)))
    ambiguity = _ONE / Decimal(inputs.n_candidates) if inputs.n_candidates > 1 else _ONE
    bonus = THREE_WAY_BONUS if inputs.distinct_sources >= 3 else _ONE

    without_bonus = inputs.base * agreement * (_ONE - delta_ratio) * date_penalty * ambiguity
    result = cap_for_stage(inputs.stage, _quantize(_clamp(without_bonus * bonus)))
    bare = cap_for_stage(inputs.stage, _quantize(_clamp(without_bonus)))

    return DerivationOutcome(
        derivation=ConfidenceDerivation(
            base_stage_confidence=_quantize(inputs.base),
            field_agreement_factor=_quantize(agreement),
            amount_delta_ratio=_quantize(delta_ratio),
            date_penalty=_quantize(date_penalty),
            ambiguity_penalty=_quantize(ambiguity),
            source_coverage_bonus=_quantize(bonus),
            result=result,
        ),
        bonus_was_load_bearing=bonus != _ONE and result != bare,
    )


def cap_for_stage(stage: MatchStage, value: Decimal) -> Decimal:
    """Apply the §6.3 per-stage ceiling.

    A fuzzy match never auto-closes whatever it scores, and the assertion is
    here rather than in the stage so stage 5 cannot be written without it.
    """
    if stage == "fuzzy":
        capped = min(value, FUZZY_CONFIDENCE_CAP)
        assert capped <= FUZZY_CONFIDENCE_CAP, "fuzzy confidence exceeded its hard cap"
        return capped
    return value


def _ratio(numerator: int, denominator: int, when_undefined: int = 1) -> Decimal:
    if denominator == 0:
        return Decimal(when_undefined)
    return Decimal(numerator) / Decimal(denominator)


def _clamp(value: Decimal) -> Decimal:
    return max(_ZERO, min(_ONE, value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_UP)
