"""Match results and the evidence that justifies them — PRD §4.3, §6.3, §6.6.

Nothing closes without evidence: stage, fields agreed, arithmetic, rule version
(CLAUDE.md hard rule 5). Empty evidence is a bug, so ``MatchResult`` requires at
least one ``MatchEvidence`` entry.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fc.models.transaction import Source

__all__ = [
    "AUTO_CLOSABLE_STAGES",
    "FUZZY_CONFIDENCE_CAP",
    "GROUPED_ONLY_STAGES",
    "group_confidence_cap",
    "ConfidenceDerivation",
    "MatchEvidence",
    "MatchResult",
    "MatchStage",
    "stage_confidence_cap",
    "stage_may_auto_close",
]

MatchStage = Literal[
    "exact_ref",
    "fee_adjusted",
    "date_shift",
    "many_to_one",
    "fuzzy",
    "rule",
]

# Hard cap from §6.3: a fuzzy match never auto-closes, whatever it scores.
FUZZY_CONFIDENCE_CAP = Decimal("0.75")

_ONE = Decimal(1)

#: §6.3: fuzzy is absent, and never gains membership.
AUTO_CLOSABLE_STAGES: frozenset[MatchStage] = frozenset(
    {"exact_ref", "fee_adjusted", "date_shift", "many_to_one", "rule"}
)

#: §6.3 reads "Yes **if grouped**" for stage 4: a settlement id is proof that
#: rows belong together, a subset that merely adds up is arithmetic that happens
#: to fit.
GROUPED_ONLY_STAGES: frozenset[MatchStage] = frozenset({"many_to_one"})


def stage_may_auto_close(stage: MatchStage, *, grouped_by: str | None) -> bool:
    """Whether one evidence leg permits its group to close on its own."""
    if stage not in AUTO_CLOSABLE_STAGES:
        return False
    return not (stage in GROUPED_ONLY_STAGES and grouped_by is None)


def stage_confidence_cap(stage: MatchStage) -> Decimal:
    """The §6.3 ceiling for one leg's stage."""
    return FUZZY_CONFIDENCE_CAP if stage == "fuzzy" else _ONE


def group_confidence_cap(legs: Iterable[MatchEvidence]) -> Decimal:
    """The ceiling for a whole group: the lowest any contributing leg allows.

    The group-level twin of :func:`stage_may_auto_close`, and it exists for the
    same reason. Reading the cap off the *host* stage would let a fuzzy leg
    extended into an ``exact_ref`` group be capped at 1.0 instead of 0.75, and
    the group would then close at high confidence with an unproven leg inside
    it - a false auto-resolution that eval scores as correct, because ground
    truth says the members do belong together.
    """
    return min((stage_confidence_cap(leg.stage) for leg in legs), default=_ONE)


class ConfidenceDerivation(BaseModel):
    """The factors of §6.6, stored so the evidence pack shows arithmetic, not a number."""

    model_config = ConfigDict(extra="forbid")

    base_stage_confidence: Decimal
    field_agreement_factor: Decimal
    amount_delta_ratio: Decimal
    date_penalty: Decimal
    ambiguity_penalty: Decimal
    source_coverage_bonus: Decimal
    result: Decimal


class MatchEvidence(BaseModel):
    """One step of the justification. Serialises to the ``matches.evidence`` JSONB."""

    model_config = ConfigDict(extra="forbid")

    stage: MatchStage
    fields_agreed: list[str] = Field(default_factory=list)
    fields_disagreed: list[str] = Field(default_factory=list)
    arithmetic: str | None = None
    delta_paise: int = 0
    date_shift_days: int = 0
    candidates_considered: int = 1
    #: The key the forming stage grouped on, where grouping is what makes the leg
    #: trustworthy (§6.3 stage 4: "Yes **if grouped**"). Lives on the evidence
    #: rather than on ``MatchResult`` because ``matches.evidence`` is JSONB, so
    #: recording it needs no migration - and because it is a property of one leg,
    #: not of the group.
    grouped_by: str | None = None
    rule_id: str | None = None
    rule_version_hash: str | None = None
    confidence_derivation: ConfidenceDerivation | None = None


class MatchResult(BaseModel):
    """A group of events proven to be the same money. Mirrors the ``matches`` table."""

    model_config = ConfigDict(extra="forbid")

    match_id: str
    run_id: str
    tenant_id: str
    group_key: str
    event_ids: list[str] = Field(min_length=1)
    sources_covered: list[Source] = Field(min_length=1)
    stage: MatchStage
    confidence: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    residual_paise: int = 0
    rule_version_hash: str | None = None
    evidence: list[MatchEvidence] = Field(min_length=1)
    auto_closed: bool = False
    created_at: datetime

    @model_validator(mode="after")
    def _the_stage_ceilings_hold(self) -> MatchResult:
        """§6.3's per-stage ceilings, enforced by the type rather than by callers.

        Putting these here rather than in the cascade is the difference between a
        rule and a convention. ``fc/matching/`` is not the only place a
        ``MatchResult`` can be constructed, and a hard cap that depends on every
        future construction site remembering to call a helper is not a hard cap.
        A group is only as provable as its weakest leg, so every evidence entry
        is asked, not just the stage that formed the group.
        """
        cap = group_confidence_cap(self.evidence)
        if self.confidence > cap:
            weakest = min(self.evidence, key=lambda leg: stage_confidence_cap(leg.stage))
            raise ValueError(
                f"confidence {self.confidence} exceeds the §6.3 cap {cap} set by this "
                f"group's weakest leg ({weakest.stage!r})"
            )
        if self.auto_closed:
            for leg in self.evidence:
                if not stage_may_auto_close(leg.stage, grouped_by=leg.grouped_by):
                    raise ValueError(
                        f"auto_closed match carries a {leg.stage!r} leg that may not "
                        f"auto-close (grouped_by={leg.grouped_by!r})"
                    )
        return self

    @property
    def is_three_way(self) -> bool:
        return len(set(self.sources_covered)) == 3
