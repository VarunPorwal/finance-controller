"""Match results and the evidence that justifies them — PRD §4.3, §6.3, §6.6.

Nothing closes without evidence: stage, fields agreed, arithmetic, rule version
(CLAUDE.md hard rule 5). Empty evidence is a bug, so ``MatchResult`` requires at
least one ``MatchEvidence`` entry.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fc.models.transaction import Source

__all__ = ["ConfidenceDerivation", "MatchEvidence", "MatchResult", "MatchStage"]

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

    @property
    def is_three_way(self) -> bool:
        return len(set(self.sources_covered)) == 3
