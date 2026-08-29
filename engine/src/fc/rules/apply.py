"""Rule application — PRD §6.7's algorithm, and the behaviour that matters.

**A rule shrinks an exception.** It does not pass or fail it. When the Blinkit
commission rule explains ₹15,760 of a ₹19,000 gap, the output is
``₹3,240 unexplained after Blinkit commission rule applied`` with the rule's
version hash attached — not ``₹19,000 mismatch``, and not a boolean. Every field
needed to say that sentence is on :class:`RuleOutcomeResult`, and the partial
path is the reason the loop below keeps going after a rule that helped instead
of returning.

**A rule can never raise an item above the auto-close threshold on its own.**
Stated as a boolean that is easier to hold than a number:
:meth:`RuleOutcomeResult.confidence_after` is monotonically non-increasing —
``min(prior, ceiling)`` — so a rule can lower a confidence or leave it alone and
has no arithmetic path to raising one, whatever ``effective_confidence`` it
carries. Independently, :attr:`RuleOutcomeResult.may_auto_close` is ``False``
whenever any residual survives: an item with unexplained money left in it does
not close at *any* confidence, which is not a threshold anyone can tune.

Nothing here imports ``fc.llm``. The LLM does not decide whether money is
reconciled (hard rule 2), and this module is where a rule stops being a
suggestion and starts closing things.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fc.config import Config
from fc.ingest.aliases import AliasTable
from fc.models.exception_ import RuleApplicationRef
from fc.models.money import fmt_inr
from fc.models.rule import Rule, RuleApplication, RuleOutcome
from fc.models.transaction import TransactionEvent
from fc.rules.evaluator import Stack, evaluate_deductions
from fc.rules.scope import candidates

__all__ = [
    "RuleOutcomeResult",
    "apply_rules",
    "rule_tolerance_paise",
]

_HUNDRED = Decimal(100)
_WHOLE = Decimal(1)
_ONE = Decimal(1)


class RuleOutcomeResult(BaseModel):
    """What the rulebook made of one gap.

    ``applications`` holds only the rules that actually moved the number. A rule
    that was considered and did nothing is not evidence of anything and is
    counted in ``considered`` rather than listed, so the evidence pack shows the
    reasoning that mattered instead of the search that found it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    outcome: RuleOutcome
    gross_paise: int
    gap_before_paise: int
    explained_paise: int
    residual_paise: int
    applications: tuple[RuleApplication, ...] = ()
    considered: int = 0
    #: The highest confidence any of the applied rules permits (§6.7: "it confers
    #: at most ``rule.effective_confidence``"). 1 when no rule applied, because a
    #: rulebook that said nothing must not cap anything.
    confidence_ceiling: Decimal = Field(default=_ONE, ge=Decimal(0), le=_ONE)

    @model_validator(mode="after")
    def _the_ceiling_is_the_weakest_rule(self) -> RuleOutcomeResult:
        """No rule confers more than its own ``effective_confidence``.

        A stack of rules is only as trustworthy as its least trustworthy member,
        exactly as a match group is only as provable as its weakest leg. Taking
        the ceiling from the *first* rule instead would let a 0.99 MDR rule that
        explained ₹200 raise the ceiling on a gap whose remaining ₹15,000 was
        explained by a 0.70 learned draft.
        """
        if self.applications:
            weakest = min(app.effective_confidence for app in self.applications)
            if self.confidence_ceiling > weakest:
                raise ValueError(
                    f"confidence_ceiling {self.confidence_ceiling} exceeds the weakest applied "
                    f"rule's effective_confidence {weakest}"
                )
        if self.explained_paise + self.residual_paise != self.gap_before_paise:
            raise ValueError(
                f"explained {self.explained_paise} + residual {self.residual_paise} != "
                f"gap {self.gap_before_paise}"
            )
        if self.outcome == "not_applicable" and self.applications:
            raise ValueError("not_applicable carries rule applications")
        if self.outcome != "not_applicable" and not self.applications:
            raise ValueError(f"{self.outcome} carries no rule applications")
        return self

    @property
    def may_auto_close(self) -> bool:
        """Whether the rulebook accounted for the whole gap.

        Not a confidence comparison. Money that is still unexplained is still
        unexplained however confident the explanation of the rest was, so a
        partially explained item cannot close and there is no threshold to tune
        that would let it.
        """
        return self.outcome == "fully_explained"

    def confidence_after(self, prior: Decimal | None = None) -> Decimal:
        """The confidence this item carries once the rulebook has spoken.

        Monotonically non-increasing in ``prior``. This is the enforcement of
        "a rule can never raise an item above the auto-close threshold on its
        own": there is no argument to this function that produces a number
        larger than the one it was given.
        """
        if prior is None:
            return self.confidence_ceiling
        return min(prior, self.confidence_ceiling)

    def as_exception_refs(self) -> tuple[RuleApplicationRef, ...]:
        """The applications as ``exceptions.rules_applied`` rows."""
        return tuple(
            RuleApplicationRef(
                rule_id=app.rule_id,
                version=app.version,
                version_hash=app.version_hash,
                explained_paise=app.explained_paise,
                arithmetic=app.arithmetic,
            )
            for app in self.applications
        )

    def narrative(self) -> str:
        """The sentence §6.7 asks for.

        ``₹3,240 unexplained after Blinkit commission rule applied`` — the
        residual first, because the residual is the finding, and the rule named,
        because a number a human cannot trace back to a rule is not an
        explanation.
        """
        if self.outcome == "not_applicable":
            return f"{fmt_inr(abs(self.gap_before_paise))} unexplained; no rule applies"
        names = _and_list([app.rule_id for app in self.applications])
        plural = "rules" if len(self.applications) > 1 else "rule"
        if self.outcome == "fully_explained":
            return (
                f"{fmt_inr(abs(self.gap_before_paise))} fully explained by "
                f"{names} {plural} ({fmt_inr(self.explained_paise)} accounted for)"
            )
        return (
            f"{fmt_inr(abs(self.residual_paise))} unexplained after {names} {plural} applied "
            f"({fmt_inr(self.explained_paise)} of {fmt_inr(abs(self.gap_before_paise))} "
            "accounted for)"
        )


def rule_tolerance_paise(
    rule: Rule, gross_paise: int, *, n_txns: int = 1, cfg: Config | None = None
) -> int:
    """The §6.5 tolerance for one rule against one gross.

    Three terms, the same shape as :func:`fc.matching.tolerance.tolerance_terms`
    but with the rule's own absolute and percentage overriding the run-wide
    defaults — a marketplace rule knows its own settlement's slop better than a
    global constant does. The ``n_txns * rounding_drift_paise`` term is carried
    over unchanged: a batch's fee is a sum of per-transaction roundings whoever
    computes it, and dropping the term here would raise a spurious few-paise
    residual on every rule-explained batch (CLAUDE.md).
    """
    percentage = _paise(Decimal(abs(gross_paise)) * rule.tolerance.percent / _HUNDRED)
    drift = max(n_txns, 0) * (cfg.rounding_drift_paise if cfg is not None else 0)
    return max(rule.tolerance.absolute_paise, percentage, drift)


def apply_rules(
    rules: Iterable[Rule],
    *,
    event: TransactionEvent,
    on_date: date,
    gap_paise: int,
    gross_paise: int,
    n_txns: int = 1,
    cfg: Config | None = None,
    aliases: AliasTable | None = None,
    include_inactive: bool = False,
) -> RuleOutcomeResult:
    """Run §6.7's algorithm over one gap.

    ``gap_paise`` is ``expected - actual``: positive when money is missing,
    which is the ordinary case for a settlement whose deductions the books have
    not modelled. ``gross_paise`` is what the rates apply to — the settlement's
    gross, not the gap.

    The loop is §6.7 verbatim, including the ``continue`` that most
    implementations turn into a ``return``. A rule that shrinks the gap without
    closing it hands the *smaller* gap to the next rule, so a marketplace
    commission rule and a separate TDS rule can between them explain what
    neither explains alone.

    ``include_inactive`` exists for one caller: :mod:`fc.rules.backtest`, which
    has to replay a rule that is by definition not active yet. It defaults to
    ``False`` so the reconciliation path can only ever apply approved rules, and
    so a draft cannot close anything by being passed to the wrong function.
    """
    ordered = candidates(rules, event, on_date, aliases=aliases, include_inactive=include_inactive)

    gap = gap_paise
    applications: list[RuleApplication] = []
    for rule in ordered:
        stack = evaluate_deductions(rule.deductions, gross_paise)
        # A stack that deducts more than the gross explains money that never
        # existed. Reachable with a flat fee on a very small settlement, so it is
        # a skip rather than an error.
        if stack.exceeds_gross:
            continue

        residual = gap - stack.total_paise
        tolerance = rule_tolerance_paise(rule, gross_paise, n_txns=n_txns, cfg=cfg)

        if abs(residual) <= tolerance:
            applications.append(
                _application(rule, stack, gap, residual, tolerance, "fully_explained", gross_paise)
            )
            return _result(
                "fully_explained", gross_paise, gap_paise, residual, applications, len(ordered)
            )

        if abs(residual) < abs(gap):
            applications.append(
                _application(
                    rule, stack, gap, residual, tolerance, "partially_explained", gross_paise
                )
            )
            gap = residual
            continue
        # The rule made it worse or did nothing. Skipped, and deliberately not
        # recorded: "we tried a rule and it did not help" is not evidence.

    if applications:
        return _result(
            "partially_explained", gross_paise, gap_paise, gap, applications, len(ordered)
        )
    return _result("not_applicable", gross_paise, gap_paise, gap_paise, (), len(ordered))


def _application(
    rule: Rule,
    stack: Stack,
    gap_before: int,
    residual: int,
    tolerance: int,
    outcome: RuleOutcome,
    gross_paise: int,
) -> RuleApplication:
    explained = gap_before - residual
    return RuleApplication(
        rule_id=rule.rule_id,
        version=rule.version,
        version_hash=rule.version_hash,
        outcome=outcome,
        gross_paise=gross_paise,
        gap_before_paise=gap_before,
        stack=list(stack.items),
        explained_paise=explained,
        residual_paise=residual,
        tolerance_paise=tolerance,
        effective_confidence=rule.effective_confidence,
        arithmetic=(
            f"gap {fmt_inr(gap_before)} - [{stack.format_arithmetic()}] "
            f"= {fmt_inr(residual)} residual (tolerance {fmt_inr(tolerance)})"
        ),
    )


def _result(
    outcome: RuleOutcome,
    gross_paise: int,
    gap_before: int,
    residual: int,
    applications: Sequence[RuleApplication],
    considered: int,
) -> RuleOutcomeResult:
    ceiling = min((app.effective_confidence for app in applications), default=_ONE)
    return RuleOutcomeResult(
        outcome=outcome,
        gross_paise=gross_paise,
        gap_before_paise=gap_before,
        explained_paise=gap_before - residual,
        residual_paise=residual,
        applications=tuple(applications),
        considered=considered,
        confidence_ceiling=ceiling,
    )


def _paise(value: Decimal) -> int:
    return int(value.quantize(_WHOLE, rounding=ROUND_HALF_UP))


def _and_list(names: Sequence[str]) -> str:
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]
