"""Exceptions: what the system refuses to close — PRD §4.3, §6.8, Appendix E.

An exception is a success, not a failure. Abstention is a correct outcome
(CLAUDE.md hard rule 4): when several answers are valid the pipeline emits
``ambiguous_multi_candidate`` rather than guessing.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AUTO_SAFE",
    "NEVER_AUTO",
    "ExceptionCategory",
    "ExceptionStatus",
    "Exception_",
    "ResolvedBy",
    "RuleApplicationRef",
    "Tier",
]

# The §6.8 classification tree, in tree order. Eleven real categories plus the
# `unknown` fallback: §0.1 counts eleven, §2.5.4 counts nine, and the tree emits
# twelve labels. The tree is authoritative — it is the code that runs — and
# `unknown` cannot be dropped because NEVER_AUTO names it.
ExceptionCategory = Literal[
    "missing_in_bank",
    "missing_in_gateway",
    "missing_in_ledger",
    "duplicate_ledger_entry",
    "chargeback_unrecorded",
    "partial_refund",
    "nach_batch_unexploded",
    "timing_lag",
    "ambiguous_multi_candidate",
    "reference_truncated",
    "amount_variance",
    "unknown",
]

Tier = Literal["auto", "monitor", "escalate"]

# Appendix E. `superseded` is reached only by a replay creating a newer run.
ExceptionStatus = Literal[
    "open",
    "monitoring",
    "resolved",
    "written_off",
    "snoozed",
    "escalated",
    "superseded",
]

ResolvedBy = Literal["system", "rule", "recheck", "human"]

#: Categories a sufficiently confident match may close on its own (§6.8).
AUTO_SAFE: frozenset[str] = frozenset(
    {"timing_lag", "amount_variance", "partial_refund", "reference_truncated"}
)

#: Categories that escalate regardless of confidence. High confidence alone is
#: never sufficient here; this is what holds false auto-resolutions at zero.
NEVER_AUTO: frozenset[str] = frozenset(
    {
        "chargeback_unrecorded",
        "duplicate_ledger_entry",
        "ambiguous_multi_candidate",
        "nach_batch_unexploded",
        "unknown",
    }
)


class RuleApplicationRef(BaseModel):
    """A rule that shrank this exception, recorded in ``exceptions.rules_applied``."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    version: int
    version_hash: str
    explained_paise: int
    arithmetic: str | None = None


class Exception_(BaseModel):
    """An unresolved item with a ranked place in the human queue."""

    model_config = ConfigDict(extra="forbid")

    exception_id: str
    run_id: str
    tenant_id: str
    event_ids: list[str] = Field(min_length=1)
    category: ExceptionCategory
    amount_paise: int
    residual_paise: int
    confidence: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    tier: Tier
    priority_score: Decimal
    cluster_id: str | None = None
    rules_applied: list[RuleApplicationRef] = Field(default_factory=list)
    recommended_action: str
    consequence: str | None = None
    deadline: date | None = None
    recheck_at: datetime | None = None
    recheck_count: int = 0
    status: ExceptionStatus = "open"
    resolved_by: ResolvedBy | None = None
    resolved_by_user: str | None = None
    resolved_via: str | None = None  # verbatim human instruction
    resolution_reason: str | None = None
    resolution_category: str | None = None
    resolved_at: datetime | None = None
    signature: str  # shape hash for 3x learning
    created_at: datetime

    @property
    def never_auto(self) -> bool:
        return self.category in NEVER_AUTO


class Cluster(BaseModel):
    """A root cause shared by several exceptions. Mirrors the ``clusters`` table."""

    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    run_id: str
    tenant_id: str
    root_cause: str
    label: str  # LLM-written, cosmetic, never affects membership
    grouping_key: str  # the deterministic key that formed it
    member_count: int
    total_paise: int
    max_tier: Tier
    suggested_fix: str | None = None
    created_at: datetime
