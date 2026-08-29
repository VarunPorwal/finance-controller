"""Types the router speaks — PRD §7.2, §7.4.

Every LLM call in this codebase is validated against a Pydantic model in this
module before its output is allowed anywhere. There is no free-form parsing: a
response that does not validate is a rotation trigger, not something to repair.

Note what the response models do *not* ask a model for. :class:`PdfRow` takes
amounts as the literal strings printed on the statement, not as paise, because
converting rupees to paise is arithmetic and arithmetic is
:func:`fc.models.money.to_paise`'s job (hard rule 1). Transcribing a number off
a page is extraction; multiplying it by a hundred is a monetary computation,
and only one of those is on the permitted side of §7.1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "FUNCTIONS",
    "HAS_DOWNSTREAM_CHECK",
    "MULTIMODAL",
    "STRUCTURED",
    "TEXT_ONLY",
    "Capabilities",
    "ClusterLabel",
    "ClusterLabelsOut",
    "Explanation",
    "ExplanationsOut",
    "ExtractionOut",
    "LLMCallRecord",
    "LLMResult",
    "ModelSpec",
    "NarrativeOut",
    "Outcome",
    "PdfRow",
    "Provider",
    "Purpose",
    "RuleProseOut",
    "SqlPlan",
    "Thinking",
]

Provider = Literal["gemini", "groq"]
Thinking = Literal["none", "low", "high"]

#: The eight routed purposes (§7.2 TASK_ROUTE).
Purpose = Literal[
    "command_parse",
    "text_to_sql",
    "narrative",
    "cluster_label",
    "explanation",
    "rule_draft",
    "pdf_extract",
    "embedding",
]

#: ``llm_calls.outcome`` (PRD §4.2.11), plus ``terminal`` for a non-LLM outcome.
Outcome = Literal["ok", "rate_limited", "timeout", "schema_fail", "down", "terminal"]

#: Purposes whose output faces a *deterministic check outside the router*, and
#: which therefore must not be cached at parse time — see ``fc.llm.client.confirm``.
#:
#: Guard (§7.3): cache poisoning. ``pdf_extract`` is only believable once
#: ``verify_balance_continuity`` has agreed with it, so a response that parsed
#: cleanly but failed the arithmetic must not survive to be re-served on the
#: next attempt. For every other purpose schema validation *is* the check, and
#: caching inline is correct. Adding a purpose with a downstream check means
#: adding it here; forgetting to means a rejected output gets cached forever.
HAS_DOWNSTREAM_CHECK: frozenset[str] = frozenset({"pdf_extract"})


@dataclass(frozen=True)
class Capabilities:
    """What a task needs, and what a model offers. Compared before rotation."""

    structured: bool = False
    functions: bool = False
    multimodal: bool = False


TEXT_ONLY = Capabilities()
STRUCTURED = Capabilities(structured=True)
FUNCTIONS = Capabilities(structured=True, functions=True)
MULTIMODAL = Capabilities(structured=True, multimodal=True)


@dataclass(frozen=True)
class ModelSpec:
    """One model, as the router sees it. Quota limits are the free-tier figures."""

    provider: Provider
    model: str
    thinking: Thinking = "low"
    structured: bool = True
    functions: bool = True
    multimodal: bool = False
    rpm_limit: int = 15
    rpd_limit: int = 1000

    @property
    def key(self) -> str:
        """Health is tracked per (provider, model, thinking level).

        The thinking level belongs in the key because ``deep`` and ``standard``
        name the same underlying model at different reasoning budgets, and a
        cooldown earned by one is not evidence about the other.
        """
        return f"{self.provider}:{self.model}:{self.thinking}"

    def satisfies(self, requires: Capabilities) -> bool:
        """Capability gate (§7.2). A model may only serve a task it can perform."""
        return (
            (self.structured or not requires.structured)
            and (self.functions or not requires.functions)
            and (self.multimodal or not requires.multimodal)
        )


class LLMResult(BaseModel):
    """One call's outcome. ``text`` is JSON that has already validated against
    the caller's schema, or a terminal's deterministic output."""

    model_config = ConfigDict(extra="forbid")

    text: str
    purpose: str
    provider: str
    model: str
    tier: str
    ladder_position: int
    cached: bool = False
    terminal: bool = False
    #: ``None`` means "awaiting a downstream check" — see :data:`HAS_DOWNSTREAM_CHECK`.
    verified: bool | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    #: Where ``fc.llm.client.confirm`` will write this result, once verified.
    cache_key: str = ""


class LLMCallRecord(BaseModel):
    """One ``llm_calls`` row, as data.

    The router cannot write that table: ``tests/unit/test_architecture.py``
    forbids importing ``sqlalchemy`` anywhere under ``engine/src``, and that is
    the right constraint rather than an inconvenience — the engine has no
    business knowing a database exists. So the router emits these to an
    injected sink, and ``api/`` persists them.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str | None = None
    run_id: str | None = None
    purpose: str
    provider: str
    model: str
    tier: str
    ladder_position: int
    prompt_hash: str
    cached: bool
    outcome: str
    verified: bool | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    created_at: datetime | None = None


# --- response schemas, one per purpose --------------------------------------


class PdfRow(BaseModel):
    """One statement line, transcribed. Amounts are the strings as printed.

    :func:`fc.models.money.to_paise` converts them. The model is not asked to
    multiply by a hundred, drop a comma or resolve a ``(-)`` prefix — those are
    arithmetic and parsing, and both are already written and tested.
    """

    model_config = ConfigDict(extra="forbid")

    txn_date: str = Field(description="transaction date exactly as printed, dd/mm/yyyy")
    value_date: str | None = Field(default=None, description="value date, dd/mm/yyyy, or null")
    narration: str = Field(description="the narration text, verbatim, including any truncation")
    chq_ref_no: str | None = None
    withdrawal: str | None = Field(
        default=None, description="withdrawal amount as printed, or null if the column is blank"
    )
    deposit: str | None = Field(
        default=None, description="deposit amount as printed, or null if the column is blank"
    )
    closing_balance: str = Field(description="running balance as printed")


class ExtractionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[PdfRow]


class SqlPlan(BaseModel):
    """§7.8. ``answerable=false`` is a correct outcome, not a failure."""

    model_config = ConfigDict(extra="forbid")

    answerable: bool
    sql: str | None = None
    reason: str | None = None


class NarrativeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrative: str


class ClusterLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    label: str


class ClusterLabelsOut(BaseModel):
    """Batched (§7.10): every cluster in one call, not one call per cluster."""

    model_config = ConfigDict(extra="forbid")

    labels: list[ClusterLabel]


class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_id: str
    explanation: str


class ExplanationsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanations: list[Explanation]


class RuleProseOut(BaseModel):
    """Prose only. The learner derives every number arithmetically from the
    resolutions it learned from (``fc/rules/learner.py``); a model that supplied
    a rate would be deciding money, which §7.1 forbids."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
