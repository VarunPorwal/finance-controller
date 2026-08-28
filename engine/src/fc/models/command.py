"""The human instruction layer's command set — PRD §8.2, §8.3.

Gemini parses free text into one of these; a deterministic validator then checks
params, resolves references, verifies amounts and confirms permissions before a
preview is rendered. The LLM proposes the shape; it never decides the outcome.

§8.2 lists thirteen rows, but row nine is ``split_cluster / merge_cluster`` and
the two take different parameters, so there are fourteen payload models. Cluster
split/merge is CUT in §0.1: the models exist so the command set is complete, but
no router and no Gemini function declaration references them. ``CUT_VERBS``
below is what the validator refuses on.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from fc.models.exception_ import ExceptionCategory
from fc.models.rule import Deduction, Scope, Tolerance

__all__ = [
    "CUT_VERBS",
    "READ_ONLY_VERBS",
    "WRITE_VERBS",
    "CommandPayload",
    "CommandVerb",
    "CreateRuleCommand",
    "EscalateCommand",
    "ExplainCommand",
    "LinkToCommand",
    "MergeClusterCommand",
    "NotifyCommand",
    "ParsedCommand",
    "PostEntriesCommand",
    "QueryCommand",
    "ReclassifyCommand",
    "RerunCommand",
    "ResolveCommand",
    "RuleDraft",
    "SnoozeCommand",
    "SplitClusterCommand",
    "WriteOffCommand",
]

CommandVerb = Literal[
    "resolve",
    "write_off",
    "link_to",
    "post_entries",
    "escalate",
    "snooze",
    "reclassify",
    "create_rule",
    "split_cluster",
    "merge_cluster",
    "rerun",
    "notify",
    "query",
    "explain",
]

#: Commands that mutate state. Every one requires a preview and a confirmation.
WRITE_VERBS: frozenset[str] = frozenset(
    {
        "resolve",
        "write_off",
        "link_to",
        "post_entries",
        "escalate",
        "snooze",
        "reclassify",
        "create_rule",
        "split_cluster",
        "merge_cluster",
        "rerun",
        "notify",
    }
)

#: Commands that read only, and need no confirmation.
READ_ONLY_VERBS: frozenset[str] = frozenset({"query", "explain"})

#: Parseable but not built (§0.1). The validator refuses these by name.
CUT_VERBS: frozenset[str] = frozenset({"split_cluster", "merge_cluster"})


class ResolveCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["resolve"] = "resolve"
    exception_id: str
    category: str
    reason: str


class WriteOffCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["write_off"] = "write_off"
    exception_ids: list[str] = Field(min_length=1)
    reason: str


class LinkToCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["link_to"] = "link_to"
    exception_id: str
    target_type: Literal["order", "payment", "settlement", "voucher", "exception"]
    target_ref: str


class PostEntriesCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["post_entries"] = "post_entries"
    exception_id: str
    dr: str  # ledger account debited
    cr: str  # ledger account credited
    amount_paise: int


class EscalateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["escalate"] = "escalate"
    exception_id: str
    assignee: str
    note: str | None = None


class SnoozeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["snooze"] = "snooze"
    exception_id: str
    until: date


class ReclassifyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["reclassify"] = "reclassify"
    exception_id: str
    category: ExceptionCategory


class RuleDraft(BaseModel):
    """A proposed rule. Back-tested and human-approved before it becomes a Rule."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    scope: Scope
    deductions: list[Deduction] = Field(default_factory=list)
    tolerance: Tolerance
    priority: int = 100
    effective_confidence: Decimal = Field(default=Decimal("0.95"), ge=Decimal(0), le=Decimal(1))


class CreateRuleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["create_rule"] = "create_rule"
    rule_draft: RuleDraft


class SplitClusterCommand(BaseModel):
    """CUT per §0.1. Present for completeness; the validator refuses it."""

    model_config = ConfigDict(extra="forbid")

    verb: Literal["split_cluster"] = "split_cluster"
    cluster_id: str
    exception_ids: list[str] = Field(min_length=1)


class MergeClusterCommand(BaseModel):
    """CUT per §0.1. Present for completeness; the validator refuses it."""

    model_config = ConfigDict(extra="forbid")

    verb: Literal["merge_cluster"] = "merge_cluster"
    cluster_ids: list[str] = Field(min_length=2)


class RerunCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["rerun"] = "rerun"
    period_start: date
    period_end: date
    reason: str | None = None


class NotifyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["notify"] = "notify"
    recipients: list[str] = Field(min_length=1)
    exception_ids: list[str] = Field(min_length=1)
    note: str | None = None


class QueryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["query"] = "query"
    question: str
    run_id: str | None = None


class ExplainCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verb: Literal["explain"] = "explain"
    exception_id: str


CommandPayload = Annotated[
    ResolveCommand
    | WriteOffCommand
    | LinkToCommand
    | PostEntriesCommand
    | EscalateCommand
    | SnoozeCommand
    | ReclassifyCommand
    | CreateRuleCommand
    | SplitClusterCommand
    | MergeClusterCommand
    | RerunCommand
    | NotifyCommand
    | QueryCommand
    | ExplainCommand,
    Field(discriminator="verb"),
]


class ParsedCommand(BaseModel):
    """One instruction, parsed. Carries its own provenance for the audit trail."""

    model_config = ConfigDict(extra="forbid")

    command_id: str
    instruction_text: str  # verbatim, stored on the audit event and resolved_via
    payload: CommandPayload
    confidence: Decimal = Field(ge=Decimal(0), le=Decimal(1))
    model_used: str | None = None
    ladder_position: int | None = None
    parsed_at: datetime

    @property
    def verb(self) -> str:
        return self.payload.verb

    @property
    def writes(self) -> bool:
        return self.verb in WRITE_VERBS
