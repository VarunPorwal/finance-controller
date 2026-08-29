"""The Deduction Rulebook — PRD §4.3, §6.7, Appendix D.

A rule *shrinks* an exception, it does not pass or fail it: the output reads
"₹3,240 unexplained after Blinkit commission rule applied", not "₹19,000
mismatch". Rules are immutable per version — an edit creates version N+1, and a
database trigger enforces it.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fc.models.transaction import Source

__all__ = [
    "Deduction",
    "DeductionBasis",
    "DeductionStackItem",
    "DeductionType",
    "Method",
    "Rail",
    "Rule",
    "RuleApplication",
    "RuleOrigin",
    "RuleOutcome",
    "RuleStatus",
    "Scope",
    "Tolerance",
]

DeductionType = Literal[
    "commission",
    "mdr",
    "gst_on_fee",
    "tds_194o",
    "reserve",
    "platform_fee",
    "custom",
]

#: ``gross``, ``net``, or a prior deduction type. Chained bases are what make
#: ``gst_on_fee`` computable: its basis is ``commission``, not ``gross``.
DeductionBasis = Literal[
    "gross",
    "net",
    "commission",
    "mdr",
    "gst_on_fee",
    "tds_194o",
    "reserve",
    "platform_fee",
    "custom",
]

RuleStatus = Literal["draft", "active", "retired"]
RuleOrigin = Literal["manual", "learned", "imported"]
RuleOutcome = Literal["fully_explained", "partially_explained", "not_applicable"]

Method = Literal["card", "upi", "netbanking", "wallet", "emi"]
Rail = Literal["neft", "rtgs", "imps", "upi", "nach", "internal"]


class Scope(BaseModel):
    """Which transactions a rule applies to. All present clauses must match."""

    model_config = ConfigDict(extra="forbid")

    counterparty_matches: list[str] | None = None  # normalised, case-insensitive
    narration_contains: list[str] | None = None
    source: Source | None = None
    method: Method | None = None
    rail: Rail | None = None
    amount_min_paise: int | None = None
    amount_max_paise: int | None = None
    date_from: date
    date_to: date | None = None

    @property
    def specificity(self) -> int:
        """Number of constraining clauses; ties in priority break on this (§6.7)."""
        clauses = (
            self.counterparty_matches,
            self.narration_contains,
            self.source,
            self.method,
            self.rail,
            self.amount_min_paise,
            self.amount_max_paise,
            self.date_to,
        )
        return sum(1 for clause in clauses if clause is not None)


class Deduction(BaseModel):
    """One layer of the deduction stack. Order matters — bases chain."""

    model_config = ConfigDict(extra="forbid")

    type: DeductionType
    basis: DeductionBasis
    rate: Decimal  # percent
    fixed_paise: int | None = None  # for flat fees


class Tolerance(BaseModel):
    """How far off a residual may be and still count as explained (§6.5).

    ``percent`` is a **percentage**, the same convention as :attr:`Deduction.rate`
    — ``Decimal("0.05")`` means 0.05%, not 5%. Both fields come from Appendix D,
    which names them together, so they read the same way. Note this differs from
    ``Config.tolerance_pct``, which is a fraction applied directly; the two are
    never mixed, and :func:`fc.rules.apply.rule_tolerance_paise` is the only
    place that converts.
    """

    model_config = ConfigDict(extra="forbid")

    absolute_paise: int
    percent: Decimal


class Rule(BaseModel):
    """One version of one rule. Immutable once ``status == 'active'``."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str  # stable across versions
    version: int
    tenant_id: str
    version_hash: str
    name: str
    description: str | None = None
    scope: Scope
    deductions: list[Deduction] = Field(default_factory=list)
    tolerance: Tolerance
    priority: int = 100  # higher wins
    effective_confidence: Decimal = Field(
        default=Decimal("0.95"), ge=Decimal(0), le=Decimal(1)
    )  # ceiling this rule can confer
    effective_from: date
    effective_to: date | None = None
    status: RuleStatus
    origin: RuleOrigin
    created_by: str
    created_at: datetime
    activated_by: str | None = None
    activated_at: datetime | None = None
    backtest_result: dict[str, object] | None = None


class DeductionStackItem(BaseModel):
    """One computed line of a deduction stack, in evaluation order."""

    model_config = ConfigDict(extra="forbid")

    type: DeductionType
    basis: DeductionBasis
    basis_paise: int
    rate: Decimal
    amount_paise: int


class RuleApplication(BaseModel):
    """The result of running one rule against one gap (§6.7).

    The invariants below are on the model rather than in
    :mod:`fc.rules.apply` for the same reason the §6.3 stage ceilings are on
    ``MatchResult``: this is not the only place a ``RuleApplication`` can be
    built — the API preview endpoint and the back-test both construct them — and
    an invariant that depends on every construction site remembering it is a
    convention, not an invariant.
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    version: int
    version_hash: str
    outcome: RuleOutcome
    gross_paise: int
    gap_before_paise: int
    stack: list[DeductionStackItem] = Field(default_factory=list)
    explained_paise: int
    residual_paise: int
    tolerance_paise: int
    effective_confidence: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    arithmetic: str

    @model_validator(mode="after")
    def _the_arithmetic_closes(self) -> RuleApplication:
        """What the rule explained plus what it left must be what it was given.

        Every number a human sees on a shrunken exception is one of these three,
        and a set of three that does not add up is worse than no numbers at all:
        it reads as a precise account of the money while quietly losing some.
        """
        if self.explained_paise + self.residual_paise != self.gap_before_paise:
            raise ValueError(
                f"rule {self.rule_id} v{self.version}: explained {self.explained_paise} + "
                f"residual {self.residual_paise} != gap {self.gap_before_paise}"
            )
        if self.outcome == "fully_explained" and abs(self.residual_paise) > self.tolerance_paise:
            raise ValueError(
                f"rule {self.rule_id} v{self.version}: outcome is fully_explained but the "
                f"residual {self.residual_paise} exceeds tolerance {self.tolerance_paise}"
            )
        if self.outcome == "not_applicable" and self.explained_paise != 0:
            raise ValueError(
                f"rule {self.rule_id} v{self.version}: outcome is not_applicable but it "
                f"claims to have explained {self.explained_paise}"
            )
        return self
