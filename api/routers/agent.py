"""The instruction layer — PRD §5.10, §7.5, §7.8, §8.3.

Four endpoints, and one sentence that governs all of them: **the returned
function call is never executed.** A model turns a sentence into a command
shape; a deterministic validator checks it and derives its effects; a human
confirms; the existing endpoints — the same ones a click goes through — carry
it out. The model proposes, the human disposes, deterministic code executes.

``/agent/execute`` calls those endpoint functions directly rather than
reimplementing what they do. That is deliberate: an instruction must not be
able to do anything a click cannot, and the surest way to guarantee it is for
both to run the same function, with the same validation, the same audit event
and the same ``dry_run`` contract.

**The parsed-command store is in this process.** A restart, or a second API
instance, loses previews. That is the same single-instance limitation the LLM
health tracker carries (§7.3), for the same reason, and both move to Redis
together in Tier 2. It is survivable because the store is a *convenience*, not
a source of truth: ``/agent/execute`` re-validates against fresh database state
and refuses if the effects have changed, so the worst a lost preview costs is
one re-parse.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit_log import append_audit
from api.converters import exception_from_row
from api.deps import (
    AuthenticatedUser,
    LLMCallBuffer,
    current_user,
    db_session,
    get_config,
    get_llm_buffer,
    get_llm_client,
    persist_llm_calls,
    readonly_session,
    rescope,
    sql_isolation_layers,
)
from api.errors import ApiError
from api.routers import exceptions as exceptions_router
from api.routers import rules as rules_router
from db.models import Cluster as ClusterRow
from db.models import ExceptionRow, Run, TransactionEventRow
from fc.agent.permissions import can, roles_permitting
from fc.agent.validator import (
    CommandContext,
    ExceptionFacts,
    Preview,
    RefCandidate,
    validate,
)
from fc.audit.replay import ReplayDiff, diff_exceptions
from fc.config import Config
from fc.llm.client import LLMClient, load_prompt
from fc.llm.grounding import is_grounded
from fc.llm.injection import sanitise, scan_narration, wrap_untrusted
from fc.llm.schemas import FUNCTIONS, STRUCTURED, NarrativeOut, SqlPlan
from fc.llm.sql_guard import MAX_ROWS, SqlRejected, guard
from fc.models.command import CUT_VERBS, CommandPayload, ParsedCommand
from fc.models.ids import new_ulid
from fc.models.money import fmt_inr

router = APIRouter(prefix="/agent", tags=["agent"])

#: How long a preview stays confirmable. Long enough to read and think about,
#: short enough that the world has probably not moved underneath it — and if it
#: has, ``/agent/execute`` catches that separately and refuses.
COMMAND_TTL_SECONDS = 15 * 60
_MAX_STORED_COMMANDS = 500


# --- the 13 function declarations (§7.5) -------------------------------------


def _declaration(verb: str, model: type[BaseModel], description: str) -> dict[str, Any]:
    """One command payload model, as a provider-neutral function declaration.

    Derived from the Pydantic model rather than hand-written, so the declared
    parameters cannot drift from the ones the validator will actually read.
    ``verb`` is stripped: it is the discriminator, not something for a model to
    fill in — the choice of function already carries it.
    """
    schema = model.model_json_schema()
    properties = {k: v for k, v in schema.get("properties", {}).items() if k != "verb"}
    required = [r for r in schema.get("required", []) if r != "verb"]
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
    }
    if "$defs" in schema:
        parameters["$defs"] = schema["$defs"]
    return {"name": verb, "description": description, "parameters": parameters}


def _command_declarations() -> list[dict[str, Any]]:
    from fc.models.command import (
        CreateRuleCommand,
        EscalateCommand,
        ExplainCommand,
        LinkToCommand,
        MergeClusterCommand,
        NotifyCommand,
        PostEntriesCommand,
        QueryCommand,
        ReclassifyCommand,
        RerunCommand,
        ResolveCommand,
        SnoozeCommand,
        SplitClusterCommand,
        WriteOffCommand,
    )

    return [
        _declaration("resolve", ResolveCommand, "Close one exception with a reason and category."),
        _declaration("write_off", WriteOffCommand, "Accept a loss on one or more exceptions."),
        _declaration(
            "link_to", LinkToCommand, "Tie an exception to a specific order, payment or voucher."
        ),
        _declaration(
            "post_entries", PostEntriesCommand, "Record a journal entry against an exception."
        ),
        _declaration("escalate", EscalateCommand, "Hand an exception to a named person."),
        _declaration("snooze", SnoozeCommand, "Defer an exception until a date."),
        _declaration("reclassify", ReclassifyCommand, "Change an exception's category."),
        _declaration("create_rule", CreateRuleCommand, "Draft a deduction rule from a pattern."),
        _declaration("split_cluster", SplitClusterCommand, "Split a cluster (not built)."),
        _declaration("merge_cluster", MergeClusterCommand, "Merge clusters (not built)."),
        _declaration("rerun", RerunCommand, "Re-reconcile a date range."),
        _declaration("notify", NotifyCommand, "Email people about specific exceptions."),
        _declaration("query", QueryCommand, "Answer a question about the reconciliation data."),
        _declaration("explain", ExplainCommand, "Explain why one exception is unresolved."),
    ]


COMMAND_DECLARATIONS = _command_declarations()


# --- the parsed-command store ------------------------------------------------


class _StoredCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    command: ParsedCommand
    preview_fingerprint: str
    expected_state: dict[str, str]
    stored_at: float
    user_id: str
    tenant_id: str


_COMMANDS: dict[str, _StoredCommand] = {}


def _store(command_id: str, entry: _StoredCommand) -> None:
    _evict_expired()
    if len(_COMMANDS) >= _MAX_STORED_COMMANDS:
        oldest = min(_COMMANDS, key=lambda k: _COMMANDS[k].stored_at)
        del _COMMANDS[oldest]
    _COMMANDS[command_id] = entry


def _evict_expired() -> None:
    cutoff = time.time() - COMMAND_TTL_SECONDS
    for key in [k for k, v in _COMMANDS.items() if v.stored_at < cutoff]:
        del _COMMANDS[key]


def _take(command_id: str, user: AuthenticatedUser) -> _StoredCommand:
    """Fetch a stored command, or say plainly that it is gone.

    404 for never-existed and 410 for expired are different answers to
    different questions, and neither is a silent re-parse. If the plan somebody
    approved is no longer available, they need to see the new plan before
    confirming it — re-parsing on their behalf would produce a confirmation for
    something they never read.

    Deliberately does *not* sweep expired entries first: doing so turned every
    410 into a 404, which is the less useful of the two answers. "Your preview
    aged out, the queue may have moved" tells somebody what happened; "I have
    never heard of this" sends them looking for a bug. ``_store`` does the
    sweeping, so the dictionary is still bounded.
    """
    entry = _COMMANDS.get(command_id)
    if entry is None:
        raise ApiError(
            404,
            "unknown command",
            f"{command_id} is not a command this server parsed. Parse the instruction "
            "again — previews are held in memory and do not survive a restart.",
        )
    if entry.stored_at < time.time() - COMMAND_TTL_SECONDS:
        del _COMMANDS[command_id]
        raise ApiError(
            410,
            "preview expired",
            f"{command_id} was parsed more than {COMMAND_TTL_SECONDS // 60} minutes ago. "
            "Parse it again and read the new preview — the queue may have moved since.",
        )
    if entry.user_id != user.user_id or entry.tenant_id != user.tenant_id:
        raise ApiError(404, "unknown command", f"{command_id} was not parsed by you.")
    return entry


# --- request and response models ---------------------------------------------


class ParseContextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_id: str | None = None
    cluster_id: str | None = None
    run_id: str | None = None


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    context: ParseContextIn = ParseContextIn()


class EffectOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    subject: str
    summary: str
    detail: dict[str, Any] = {}


class WarningOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    detail: dict[str, Any] = {}


class RefusalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    candidates: list[str] = []
    detail: dict[str, Any] = {}


class ClusterOfferOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    member_count: int


class PreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    effects: list[EffectOut] = []
    warnings: list[WarningOut] = []
    requires_typed_confirmation: bool = False
    typed_confirmation_paise: int | None = None
    requires_acknowledgement: bool = False
    cluster_offer: ClusterOfferOut | None = None
    refusal: RefusalOut | None = None


class ParseOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str
    command: ParsedCommand | None
    confidence: Decimal
    preview: PreviewOut
    model_used: str | None = None
    ladder_position: int | None = None
    #: True when no model could parse the sentence and the client should render
    #: the command form instead. Not an error — the same commands, typed in.
    parse_unavailable: bool = False
    form_verbs: list[str] = []


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str
    confirmed: bool = False
    typed_confirmation: str | None = None
    acknowledged: bool = False
    apply_to_cluster: bool = False


class AppliedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exception_id: str
    ok: bool
    detail: str | None = None


class ExecuteOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied: list[AppliedOut]
    audit_seq: int | None = None
    excluded: list[AppliedOut] = []


class AskTurnIn(BaseModel):
    """One prior turn, supplied by the client — the server keeps no
    conversation state (PRD §3.7 has no session table, and CLAUDE.md forbids
    a schema change to add one). The client sends the last 5; the server
    caps it there too, defence in depth."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    run_id: str | None = None
    history: list[AskTurnIn] = []


class AskOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answerable: bool
    answer: str | None = None
    #: Which tool answered — "sql" (a guarded SELECT) or "diff" (a run
    #: comparison via fc.audit.replay.diff_exceptions). Logged so "which
    #: tool answered" is visible without re-deriving it from the SQL field's
    #: presence.
    tool: str | None = None
    sql: str | None = None
    rows: list[dict[str, Any]] = []
    row_count: int = 0
    #: True when the evidence is worth rendering as a table — a list request
    #: or more than a handful of rows. False means the prose in `answer` is
    #: the whole answer; the rows are still attached for "how I got this."
    show_table: bool = False
    #: Set only for tool="diff" — which two runs were compared.
    compared_from_run_id: str | None = None
    compared_to_run_id: str | None = None
    refusal_reason: str | None = None
    model_used: str | None = None
    cached: bool = False
    truncated: bool = False


class NarrativeOutModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    narrative: str
    generated_at: datetime
    model_used: str
    cached: bool


class HealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiers: dict[str, list[dict[str, Any]]]
    #: Per-model RPD used/limit/remaining, deduplicated by quota bucket. The
    #: Flash models allow 20 requests a day each, so this is the number that
    #: matters on demo day.
    budget: dict[str, Any]
    mode: str
    degraded: bool
    health_scope: str
    calls_this_run: int
    calls_total: int
    cache_hit_rate: str
    sql_isolation: list[str]
    prompts: dict[str, str]


# --- shared plumbing ---------------------------------------------------------


def _to_preview_out(preview: Preview) -> PreviewOut:
    return PreviewOut(
        summary=preview.summary,
        effects=[
            EffectOut(
                action=e.action, subject=e.subject, summary=e.summary, detail=_jsonable(e.detail)
            )
            for e in preview.effects
        ],
        warnings=[
            WarningOut(code=w.code, message=w.message, detail=_jsonable(w.detail))
            for w in preview.warnings
        ],
        requires_typed_confirmation=preview.requires_typed_confirmation,
        typed_confirmation_paise=preview.typed_confirmation_paise,
        requires_acknowledgement=preview.requires_acknowledgement,
        cluster_offer=(
            None
            if preview.cluster_offer is None
            else ClusterOfferOut(
                cluster_id=preview.cluster_offer.cluster_id,
                member_count=preview.cluster_offer.member_count,
            )
        ),
        refusal=(
            None
            if preview.refusal is None
            else RefusalOut(
                code=preview.refusal.code,
                message=preview.refusal.message,
                candidates=list(preview.refusal.candidates),
                detail=_jsonable(preview.refusal.detail),
            )
        ),
    )


def _jsonable(detail: Any) -> dict[str, Any]:
    return {
        k: (v.isoformat() if isinstance(v, date | datetime) else v) for k, v in dict(detail).items()
    }


# --- context assembly --------------------------------------------------------


async def _build_context(
    session: AsyncSession,
    *,
    command: ParsedCommand,
    expected_state: dict[str, str] | None = None,
) -> CommandContext:
    """Everything the validator needs, read fresh from the database.

    Called twice per instruction — once at parse to build the preview, once at
    execute to check the preview still holds. Both times against live rows,
    which is what makes the concurrent-edit rule (§8.5) real rather than
    theoretical.
    """
    payload = command.payload
    ids: list[str] = []
    single = getattr(payload, "exception_id", None)
    if isinstance(single, str):
        ids.append(single)
    many = getattr(payload, "exception_ids", None)
    if isinstance(many, list):
        ids.extend(str(i) for i in many)

    facts: dict[str, ExceptionFacts] = {}
    cluster_sizes: dict[str, int] = {}
    near: dict[str, list[RefCandidate]] = {}

    if ids:
        rows = (
            await session.scalars(select(ExceptionRow).where(ExceptionRow.exception_id.in_(ids)))
        ).all()
        found = {r.exception_id: r for r in rows}
        event_ids = sorted({eid for r in rows for eid in r.event_ids})
        events = (
            (
                await session.scalars(
                    select(TransactionEventRow).where(TransactionEventRow.event_id.in_(event_ids))
                )
            ).all()
            if event_ids
            else []
        )
        by_event = {e.event_id: e for e in events}

        for exception_id, row in found.items():
            linked = [by_event[e] for e in row.event_ids if e in by_event]
            patterns = sorted({p for e in linked for p in scan_narration(e.raw_narration).patterns})
            facts[exception_id] = ExceptionFacts(
                exception_id=exception_id,
                amount_paise=row.amount_paise,
                residual_paise=row.residual_paise,
                category=row.category,
                status=row.status,
                tier=row.tier,
                cluster_id=row.cluster_id,
                state_fingerprint=_state_fingerprint(row),
                has_dispute_reference=any(e.txn_type == "dispute" for e in linked),
                suspicious_patterns=tuple(patterns),
            )
            if row.cluster_id:
                cluster_sizes.setdefault(row.cluster_id, 0)

        for missing in [i for i in ids if i not in found]:
            near[missing] = await _near_exceptions(session, missing)

    for cluster_id in list(cluster_sizes):
        cluster = await session.get(ClusterRow, cluster_id)
        cluster_sizes[cluster_id] = cluster.member_count if cluster else 0

    resolved: dict[str, RefCandidate] = {}
    ambiguous: dict[str, list[RefCandidate]] = {}
    target_ref = getattr(payload, "target_ref", None)
    if isinstance(target_ref, str) and target_ref:
        matches = await _resolve_reference(session, target_ref)
        if len(matches) == 1:
            resolved[target_ref] = matches[0]
        elif len(matches) > 1:
            ambiguous[target_ref] = matches
        else:
            near[target_ref] = await _near_references(session, target_ref)

    return CommandContext(
        exceptions=facts,
        resolved_refs=resolved,
        ambiguous_refs=ambiguous,
        near_matches=near,
        cluster_sizes=cluster_sizes,
        expected_state=expected_state,
    )


def _state_fingerprint(row: ExceptionRow) -> str:
    """Everything about an exception a preview depends on, as one string.

    Deliberately not ``updated_at`` — there is no such column, and adding one
    would be a schema change. These are the fields an effect is derived from, so
    a change in any of them is exactly a change the human needs to re-read.
    """
    return "|".join(
        str(v)
        for v in (
            row.status,
            row.category,
            row.amount_paise,
            row.residual_paise,
            row.tier,
            row.cluster_id,
            row.resolved_at,
        )
    )


async def _near_exceptions(session: AsyncSession, ref: str) -> list[RefCandidate]:
    """Exceptions whose id looks like the one that was not found (§8.5 rule 2).

    Listed for a human to choose from. Never chosen from here — a near match is
    evidence, and picking one on somebody's behalf is the guess this whole layer
    exists to avoid.
    """
    fragment = ref.replace("exc_", "")[:6]
    if len(fragment) < 3:
        return []
    rows = (
        await session.scalars(
            select(ExceptionRow).where(ExceptionRow.exception_id.ilike(f"%{fragment}%")).limit(5)
        )
    ).all()
    return [
        RefCandidate(ref=r.exception_id, kind="exception", amount_paise=r.amount_paise)
        for r in rows
    ]


_REF_COLUMNS = (
    ("order", TransactionEventRow.order_id),
    ("payment", TransactionEventRow.payment_id),
    ("settlement", TransactionEventRow.settlement_id),
    ("voucher", TransactionEventRow.voucher_number),
)


async def _resolve_reference(session: AsyncSession, ref: str) -> list[RefCandidate]:
    out: list[RefCandidate] = []
    for kind, column in _REF_COLUMNS:
        rows = (
            await session.scalars(select(TransactionEventRow).where(column == ref).limit(5))
        ).all()
        out.extend(
            RefCandidate(
                ref=ref,
                kind=kind,
                amount_paise=r.amount_paise,
                txn_date=r.txn_date,
                event_id=r.event_id,
            )
            for r in rows
        )
    return out


async def _near_references(session: AsyncSession, ref: str) -> list[RefCandidate]:
    fragment = ref.split("_", 1)[-1][:6]
    if len(fragment) < 3:
        return []
    out: list[RefCandidate] = []
    for kind, column in _REF_COLUMNS:
        rows = (
            await session.scalars(
                select(TransactionEventRow).where(column.ilike(f"%{fragment}%")).limit(3)
            )
        ).all()
        out.extend(
            RefCandidate(
                ref=getattr(r, f"{kind}_id", None) or getattr(r, "voucher_number", None) or ref,
                kind=kind,
                amount_paise=r.amount_paise,
                txn_date=r.txn_date,
                event_id=r.event_id,
            )
            for r in rows
        )
    return out[:5]


# --- POST /agent/parse -------------------------------------------------------


@router.post("/parse", response_model=ParseOut)
async def parse_instruction(
    body: ParseRequest,
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
    client: LLMClient = Depends(get_llm_client),
    buffer: LLMCallBuffer = Depends(get_llm_buffer),
) -> ParseOut:
    """Sentence in, preview out. Nothing is executed and nothing is written."""
    instruction = body.text.strip()
    if not instruction:
        raise ApiError(422, "empty instruction", "there is nothing to parse")

    prompt = _parse_prompt(instruction, body.context)
    result = await client.call(
        "command_parse",
        prompt=prompt,
        system=load_prompt("command_system"),
        tenant_id=user.tenant_id,
        run_id=body.context.run_id,
        tools=COMMAND_DECLARATIONS,
        requires=FUNCTIONS,
        fallback=json.dumps({"name": "__form__", "args": {}}),
    )
    await persist_llm_calls(session, buffer, tenant_id=user.tenant_id)

    call = json.loads(result.text)
    if call.get("name") == "__form__":
        await session.commit()
        return ParseOut(
            command_id="",
            command=None,
            confidence=Decimal(0),
            preview=PreviewOut(
                summary=(
                    "No model was available to read that sentence. Pick a command and "
                    "fill in the fields — the same instruction, typed in."
                )
            ),
            parse_unavailable=True,
            form_verbs=[d["name"] for d in COMMAND_DECLARATIONS if d["name"] not in CUT_VERBS],
        )

    command = _to_parsed_command(call, instruction, result.model, result.ladder_position)
    ctx = await _build_context(session, command=command)
    preview = validate(command, ctx, cfg=cfg, role=user.role)

    # §8.5 rules 2 and 3 are the two the PRD raises as 422 (§5.10): they need an
    # answer from the person, not a confirmation. Everything else renders as a
    # preview with its push-back attached, because the person can still proceed
    # once they have read it.
    if preview.refusal is not None and preview.refusal.code in ("ambiguous", "not_found"):
        await session.commit()
        raise ApiError(
            422,
            preview.refusal.code,
            preview.refusal.message,
            type_="https://fc.dev/errors/agent",
            candidates=list(preview.refusal.candidates),
        )

    command_id = new_ulid("cmd_")
    _store(
        command_id,
        _StoredCommand(
            command=command,
            preview_fingerprint=preview.fingerprint(),
            expected_state={k: v.state_fingerprint for k, v in ctx.exceptions.items()},
            stored_at=time.time(),
            user_id=user.user_id,
            tenant_id=user.tenant_id,
        ),
    )
    await session.commit()
    return ParseOut(
        command_id=command_id,
        command=command.model_copy(update={"command_id": command_id}),
        confidence=command.confidence,
        preview=_to_preview_out(preview),
        model_used=result.model,
        ladder_position=result.ladder_position,
    )


def _parse_prompt(instruction: str, context: ParseContextIn) -> str:
    """Instruction plus context, with the instruction wrapped as untrusted.

    The operator's own sentence is trusted *as an instruction* — that is what it
    is — but it is still sanitised (§10.3 layer 3), because an operator can
    paste a narration into the box, and a narration is somebody else's text.
    """
    lines = [
        "Current date: " + datetime.now(UTC).date().isoformat(),
        "Context: " + json.dumps(context.model_dump(exclude_none=True)),
        "",
        "Operator instruction:",
        sanitise(instruction, max_chars=2000),
    ]
    return "\n".join(lines)


def _to_parsed_command(
    call: dict[str, Any], instruction: str, model: str, ladder_position: int
) -> ParsedCommand:
    """Validate the function call against the command union, or refuse it.

    §7.4: validation is the gate. A call naming a function that does not exist,
    or filling it with fields the payload model does not declare, produces a 422
    here rather than a partially-understood command downstream.
    """
    name = call.get("name")
    args = call.get("args") or {}
    if not isinstance(name, str) or not isinstance(args, dict):
        raise ApiError(422, "unparseable", "the model did not return a usable command")
    try:
        payload: CommandPayload = _validate_payload({**args, "verb": name})
    except ValidationError as exc:
        raise ApiError(
            422,
            "unparseable",
            f"'{instruction}' did not resolve to a command I can carry out. "
            "Try naming the exception and what you want done with it.",
            type_="https://fc.dev/errors/agent",
            errors=json.loads(exc.json()),
        ) from exc
    return ParsedCommand(
        command_id=new_ulid("cmd_"),
        instruction_text=instruction,
        payload=payload,
        confidence=Decimal("0.90"),
        model_used=model,
        ladder_position=ladder_position,
        parsed_at=datetime.now(UTC),
    )


class _PayloadEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: CommandPayload


def _validate_payload(raw: dict[str, Any]) -> CommandPayload:
    return _PayloadEnvelope.model_validate({"payload": raw}).payload


# --- POST /agent/execute -----------------------------------------------------


@router.post("/execute", response_model=ExecuteOut)
async def execute_command(
    body: ExecuteRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    cfg: Config = Depends(get_config),
) -> ExecuteOut:
    """Carry out a previously previewed command, after re-checking it holds."""
    entry = _take(body.command_id, user)
    command = entry.command

    if not body.confirmed:
        raise ApiError(422, "not confirmed", "set confirmed=true — a preview is not an instruction")

    ctx = await _build_context(session, command=command, expected_state=entry.expected_state)
    preview = validate(command, ctx, cfg=cfg, role=user.role)

    if preview.refusal is not None:
        raise ApiError(
            409 if preview.refusal.code == "conflict" else 422,
            preview.refusal.code,
            preview.refusal.message,
            type_="https://fc.dev/errors/agent",
            candidates=list(preview.refusal.candidates),
            preview=_to_preview_out(preview).model_dump(mode="json"),
        )

    # The whole point of a preview: what runs must be what was shown. If
    # re-validation against fresh state produces different effects, the human
    # approved a plan that no longer exists, and consent does not transfer.
    if preview.fingerprint() != entry.preview_fingerprint:
        raise ApiError(
            409,
            "preview stale",
            "The effects of this instruction changed since you saw them. Nothing has "
            "been applied. Read the revised preview below and confirm again if it is "
            "still what you want.",
            type_="https://fc.dev/errors/agent",
            preview=_to_preview_out(preview).model_dump(mode="json"),
        )

    if command.verb not in _EXECUTABLE_VERBS:
        raise ApiError(
            422,
            "no execution path",
            f"{command.verb.replace('_', ' ')} parses, but this build cannot carry it "
            f"out. {_NO_EXECUTION_PATH.get(command.verb, '')}".strip(),
            type_="https://fc.dev/errors/agent",
            preview=_to_preview_out(preview).model_dump(mode="json"),
        )

    _check_confirmations(preview, body)

    targets = _targets(command, preview)
    if not targets:
        raise ApiError(
            422,
            "nothing to apply",
            "The preview derived no effect this build can carry out. Nothing was changed.",
            type_="https://fc.dev/errors/agent",
            preview=_to_preview_out(preview).model_dump(mode="json"),
        )
    screened_out: list[AppliedOut] = []
    if body.apply_to_cluster and command.verb != "create_rule":
        primary = list(targets)
        targets = await _expand_cluster(session, targets, ctx)
        targets, screened_out = await _screen_targets(
            session, command=command, targets=targets, primary=primary, cfg=cfg, role=user.role
        )

    applied, excluded = await _dispatch(
        session, command=command, targets=targets, user=user, cfg=cfg, dry_run=dry_run
    )

    # Each dispatched endpoint called ``finish``, which ended the transaction
    # this session's tenant scope was set on. Re-apply it before writing
    # anything else, or RLS refuses the audit event below.
    await rescope(session, user)

    audit = await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="agent.execute",
        subject_type="command",
        subject_id=body.command_id,
        payload={
            # Verbatim, per §8.3 — the audit trail records what the person
            # actually said, not our paraphrase of it.
            "instruction_text": command.instruction_text,
            "verb": command.verb,
            "model_used": command.model_used,
            "ladder_position": command.ladder_position,
            "preview_fingerprint": entry.preview_fingerprint,
            "applied": [a.exception_id for a in applied if a.ok],
            "excluded": [a.exception_id for a in screened_out + excluded],
            "apply_to_cluster": body.apply_to_cluster,
            "dry_run": dry_run,
        },
        created_at=datetime.now(UTC),
    )
    audit_seq = audit.seq
    result = ExecuteOut(applied=applied, audit_seq=audit_seq, excluded=screened_out + excluded)
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    if not dry_run:
        del _COMMANDS[body.command_id]
    return result


def _check_confirmations(preview: Preview, body: ExecuteRequest) -> None:
    """§8.5 rules 4 and 5 — the two that need something extra from the person."""
    if preview.requires_acknowledgement and not body.acknowledged:
        raise ApiError(
            422,
            "acknowledgement required",
            next(
                (w.message for w in preview.warnings if w.code == "chargeback_without_dispute_ref"),
                "this action needs an explicit acknowledgement",
            ),
        )
    if preview.requires_typed_confirmation:
        expected = preview.typed_confirmation_paise or 0
        typed = (body.typed_confirmation or "").strip()
        if not typed or not _matches_amount(typed, expected):
            raise ApiError(
                422,
                "typed confirmation required",
                f"This moves {fmt_inr(expected)}, which is above the typed-confirmation "
                f"threshold. Type the amount to confirm it.",
                expected_paise=expected,
            )


def _matches_amount(typed: str, expected_paise: int) -> bool:
    """Accept any faithful spelling of the amount, reject a different number.

    ``52000``, ``52,000``, ``52000.00`` and ``₹52,000.00`` are the same person
    agreeing to the same figure. The check is that the number matches — not
    that they guessed our formatting.
    """
    from fc.models.money import to_paise

    try:
        return to_paise(typed) == expected_paise
    except (ValueError, TypeError):
        return False


#: Verbs ``_apply_one`` can actually carry out. Anything else is refused at
#: execute time by name.
#:
#: This list is the fix for a bug worth recording: ``_targets`` used to collect
#: only ``exception.*`` effects, so ``create_rule`` — whose effect is
#: ``rule.create`` — dispatched nothing, and ``/agent/execute`` returned 200
#: with an empty ``applied`` list and wrote an audit event saying the
#: instruction had been carried out. "Looks applied but isn't" is the worst
#: shape of failure this system can have, and silence was how it happened.
_EXECUTABLE_VERBS: frozenset[str] = frozenset(
    {"resolve", "write_off", "escalate", "snooze", "reclassify", "link_to", "create_rule"}
)

#: What to tell somebody whose verb parsed but has nowhere to go.
_NO_EXECUTION_PATH: dict[str, str] = {
    "query": "Questions are answered by POST /agent/ask, which writes nothing.",
    "explain": "Use GET /exceptions/{id}/evidence — it shows the whole evidence pack.",
    "notify": (
        "Emailing arbitrary recipients about specific exceptions is not built. "
        "Escalating an item does send the configured address an alert."
    ),
    "rerun": (
        "Re-reconciling a date range is not built. POST /runs starts a fresh run, "
        "and POST /runs/{run_id}/replay re-runs one that already exists."
    ),
    "post_entries": (
        "This build posts no journal entries — the preview shows the Dr/Cr lines "
        "so you can post them in Tally and resolve the exception with that reason."
    ),
}


def _targets(command: ParsedCommand, preview: Preview) -> list[str]:
    """The subjects ``_dispatch`` will act on, one per underlying call."""
    if command.verb == "create_rule":
        # One call, not one per exception — a rule is not scoped to a row.
        return [command.payload.rule_draft.name]  # type: ignore[union-attr]
    seen: list[str] = []
    for effect in preview.effects:
        if effect.action.startswith("exception.") and effect.subject not in seen:
            seen.append(effect.subject)
    return seen


async def _expand_cluster(
    session: AsyncSession, targets: Sequence[str], ctx: CommandContext
) -> list[str]:
    """§8.6. Every other member of the same cluster, added to the target list.

    Membership comes from the cluster the exception already belongs to — a
    deterministic grouping key, not the model's opinion about what is similar.
    """
    out = list(targets)
    for target in targets:
        facts = ctx.exceptions.get(target)
        if facts is None or facts.cluster_id is None:
            continue
        rows = (
            await session.scalars(
                select(ExceptionRow).where(
                    ExceptionRow.cluster_id == facts.cluster_id,
                    ExceptionRow.status.in_(["open", "monitoring", "snoozed", "escalated"]),
                )
            )
        ).all()
        out.extend(r.exception_id for r in rows if r.exception_id not in out)
    return out


def _retarget(command: ParsedCommand, target: str) -> ParsedCommand:
    """The same instruction, pointed at a different exception."""
    payload = command.payload
    if hasattr(payload, "exception_ids"):
        updated = payload.model_copy(update={"exception_ids": [target]})
    else:
        updated = payload.model_copy(update={"exception_id": target})
    return command.model_copy(update={"payload": updated})


async def _screen_targets(
    session: AsyncSession,
    *,
    command: ParsedCommand,
    targets: Sequence[str],
    primary: Sequence[str],
    cfg: Config,
    role: str,
) -> tuple[list[str], list[AppliedOut]]:
    """§8.6: "applying to all runs the same validator per item".

    Not the endpoint's own status guard — the *whole* validator, including the
    push-back rules. Without this, a confirmation given for one ₹1,200 timing
    lag would carry a ₹90,000 chargeback out of the same cluster on its back,
    and the endpoint's guard would have no reason to object.

    An item that needs its own confirmation — a chargeback wanting an
    acknowledgement, an amount over the typed-confirmation threshold — is
    excluded rather than applied, because the human confirmed a different item.
    Every exclusion is reported by name; none is silently skipped.
    """
    allowed: list[str] = []
    excluded: list[AppliedOut] = []
    for target in targets:
        if target in primary:
            allowed.append(target)  # already validated, previewed and confirmed
            continue
        retargeted = _retarget(command, target)
        preview = validate(
            retargeted,
            await _build_context(session, command=retargeted),
            cfg=cfg,
            role=role,
        )
        if preview.refusal is not None:
            excluded.append(
                AppliedOut(exception_id=target, ok=False, detail=preview.refusal.message)
            )
        elif preview.requires_acknowledgement or preview.requires_typed_confirmation:
            excluded.append(
                AppliedOut(
                    exception_id=target,
                    ok=False,
                    detail=(
                        "needs its own confirmation, which was given for a different "
                        "item — resolve this one on its own."
                    ),
                )
            )
        else:
            allowed.append(target)
    return allowed, excluded


async def _dispatch(
    session: AsyncSession,
    *,
    command: ParsedCommand,
    targets: Sequence[str],
    user: AuthenticatedUser,
    cfg: Config,
    dry_run: bool,
) -> tuple[list[AppliedOut], list[AppliedOut]]:
    """Run each effect through the endpoint a click would have gone through.

    Per-item, and an item that fails is reported by name rather than taking the
    others down with it (§8.6). ``finish`` inside each endpoint commits its own
    work, which is why a failure mid-way leaves the earlier items applied and
    named in the response instead of silently rolled back.
    """
    payload = command.payload
    verb = command.verb
    applied: list[AppliedOut] = []
    excluded: list[AppliedOut] = []

    for target in targets:
        try:
            await _apply_one(
                session,
                verb=verb,
                payload=payload,
                target=target,
                instruction=command.instruction_text,
                user=user,
                cfg=cfg,
                dry_run=dry_run,
            )
        except ApiError as exc:
            excluded.append(AppliedOut(exception_id=target, ok=False, detail=exc.detail))
            continue
        applied.append(AppliedOut(exception_id=target, ok=True))
    return applied, excluded


async def _apply_one(
    session: AsyncSession,
    *,
    verb: str,
    payload: Any,
    target: str,
    instruction: str,
    user: AuthenticatedUser,
    cfg: Config,
    dry_run: bool,
) -> None:
    ex = exceptions_router
    if verb == "resolve":
        await ex.resolve_exception(
            target,
            ex.ResolveRequest(reason=instruction, resolution_category=payload.category),
            dry_run=dry_run,
            session=session,
            user=user,
        )
    elif verb == "write_off":
        await ex.write_off_exception(
            target,
            ex.WriteOffRequest(reason=payload.reason),
            dry_run=dry_run,
            session=session,
            user=user,
        )
    elif verb == "escalate":
        note = payload.note or "escalated by instruction"
        await ex.escalate_exception(
            target,
            ex.EscalateRequest(reason=f"{payload.assignee}: {note}"),
            dry_run=dry_run,
            session=session,
            user=user,
        )
    elif verb == "snooze":
        await ex.snooze_exception(
            target,
            ex.SnoozeRequest(until=payload.until, reason=instruction),
            dry_run=dry_run,
            session=session,
            user=user,
        )
    elif verb == "reclassify":
        await ex.reclassify_exception(
            target,
            ex.ReclassifyRequest(category=payload.category, reason=instruction),
            dry_run=dry_run,
            session=session,
            user=user,
        )
    elif verb == "link_to":
        event_id = await _event_for_ref(session, payload.target_ref)
        await ex.link_exception(
            target,
            ex.LinkRequest(event_id=event_id, reason=instruction),
            dry_run=dry_run,
            session=session,
            user=user,
            cfg=cfg,
        )
    elif verb == "create_rule":
        draft = payload.rule_draft
        await rules_router.create_rule(
            rules_router.RuleCreateRequest(
                rule_id=new_ulid("rule_"),
                name=draft.name,
                description=draft.description,
                scope=draft.scope,
                deductions=draft.deductions,
                tolerance=draft.tolerance,
                priority=draft.priority,
                effective_confidence=str(draft.effective_confidence),
            ),
            dry_run=dry_run,
            session=session,
            user=user,
        )
    else:
        raise ApiError(422, "unsupported", f"{verb} has no execution path in this build")


async def _event_for_ref(session: AsyncSession, ref: str) -> str:
    candidates = await _resolve_reference(session, ref)
    if len(candidates) != 1 or candidates[0].event_id is None:
        raise ApiError(422, "unresolved reference", f"{ref} no longer resolves to one event")
    return candidates[0].event_id


# --- POST /agent/ask ---------------------------------------------------------

#: Deterministic tool routing (PRD: "a count query gives '46 then, 44 now';
#: the diff gives which specific items moved"). Not a classification LLM
#: call — that would spend exactly the quota this exists to save, and the
#: phrasing that signals "compare two runs" is narrow enough that a keyword
#: match is the honest tool for the job, not a shortcut around one.
_DIFF_INTENT = re.compile(
    r"\b(what'?s? changed|what changed|since yesterday|since the last run|"
    r"compare|comparison|vs\.?\s+last|versus\s+last|difference between|"
    r"diff between|compared to (the )?(last|previous) run)\b",
    re.IGNORECASE,
)
_YESTERDAY = re.compile(r"\byesterday\b", re.IGNORECASE)

#: A single aggregate ("how much", "how many", "total") needs no more than
#: Flash-Lite; anything with a second clause, a comparison or a breakdown
#: goes to the standard tier first instead. A follow-up always uses the
#: standard tier too — resolving a referent from conversation history is not
#: the "simple" case this exists for.
_SIMPLE_LOOKUP = re.compile(
    r"^(how (much|many)|what('?s| is) the (total|count|sum)|total|count)\b", re.IGNORECASE
)
_COMPLEX_HINT = re.compile(
    r"\b(compare|breakdown|break down|group by|top \d|and (also|which))\b", re.IGNORECASE
)
_LIST_REQUEST = re.compile(
    r"\b(list|show me|which (ones|are)|give me (a|the) list)\b", re.IGNORECASE
)

#: PRD §13.5: auto-resolved items collapse below the fold; a table earns its
#: place only past this many rows or an explicit ask for a list.
_TABLE_ROW_THRESHOLD = 8


def _wants_diff(question: str) -> bool:
    return bool(_DIFF_INTENT.search(question))


def _is_simple_lookup(question: str, history: Sequence[AskTurnIn]) -> bool:
    if history or _COMPLEX_HINT.search(question):
        return False
    return len(question.split()) <= 12 and bool(_SIMPLE_LOOKUP.search(question.strip()))


def _wants_table(question: str, row_count: int) -> bool:
    return row_count > _TABLE_ROW_THRESHOLD or bool(_LIST_REQUEST.search(question))


def _conversational_refusal(reason: str | None) -> str:
    return reason or "I can't answer that from your reconciliation data."


@router.post("/ask", response_model=AskOut)
async def ask(
    body: AskRequest,
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    client: LLMClient = Depends(get_llm_client),
    buffer: LLMCallBuffer = Depends(get_llm_buffer),
) -> AskOut:
    """The conversational Ask tab (§13.7) — a chat, not a query box.

    Two tools, chosen deterministically from the question's own phrasing,
    never by an extra classification call: a guarded SELECT (§7.8, unchanged
    — sqlglot guard, table whitelist, read-only transaction, statement
    timeout, RLS) for anything about the current data, and
    ``fc.audit.replay.diff_exceptions`` for "what changed" / "compare the
    last two runs" — a count query answers "46 then, 44 now"; the diff
    answers which specific items moved and why.

    **No number in the answer comes from the model.** SQL rows and diff
    facts are both computed in Python; the model only phrases them
    (``sql_narrate``), and ``fc.llm.grounding.is_grounded`` discards any
    phrasing that states a number the facts never gave it, falling back to
    the same deterministic rendering the old table-only Ask tab used.

    The last 5 turns travel with the request (no session table — PRD §3.7's
    schema is frozen) so a follow-up like "which of those are over ₹10,000"
    resolves its referent from the conversation, then asks fresh SQL. It
    never answers by filtering the previous turn's numbers in its head —
    there is no path from one turn's rows into the next turn's answer except
    through a new query, which is what makes "the underlying data can have
    changed" true rather than aspirational.
    """
    if not can(user.role, "agent:read"):
        permitted = roles_permitting("agent:read")
        raise ApiError(
            403,
            "forbidden",
            f"Your role ({user.role}) cannot query the data. This needs {permitted[-1]} or above.",
        )

    question = sanitise(body.question, max_chars=1000)
    history = body.history[-5:]

    if _wants_diff(question):
        return await _answer_via_diff(
            question, history, session=session, user=user, client=client, buffer=buffer
        )
    return await _answer_via_sql(
        question,
        history,
        run_id=body.run_id,
        session=session,
        user=user,
        client=client,
        buffer=buffer,
    )


async def _answer_via_sql(
    question: str,
    history: Sequence[AskTurnIn],
    *,
    run_id: str | None,
    session: AsyncSession,
    user: AuthenticatedUser,
    client: LLMClient,
    buffer: LLMCallBuffer,
) -> AskOut:
    refusal = SqlPlan(
        answerable=False,
        reason=(
            "The Ask tab needs a language model and none is reachable right now. "
            "The dashboard, the queue and every metric are unaffected — they are "
            "computed, not generated."
        ),
    )
    purpose = "text_to_sql_light" if _is_simple_lookup(question, history) else "text_to_sql"
    result = await client.call(
        purpose,
        prompt=wrap_untrusted(_sql_prompt(question, history, run_id), source="operator_question"),
        system=load_prompt("sql_system"),
        tenant_id=user.tenant_id,
        run_id=run_id,
        schema=SqlPlan,
        requires=STRUCTURED,
        fallback=refusal.model_dump_json(),
    )
    await persist_llm_calls(session, buffer, tenant_id=user.tenant_id)
    await session.commit()

    plan = SqlPlan.model_validate_json(result.text)
    if not plan.answerable or not plan.sql:
        # Rendered verbatim. A refusal that gets paraphrased into an apology
        # stops being information (hard rule 4) — and §13.7 wants it plain,
        # not styled as an error, because a refusal is a correct outcome.
        return AskOut(
            answerable=False,
            tool="sql",
            refusal_reason=_conversational_refusal(plan.reason),
            model_used=result.model,
            cached=result.cached,
        )

    try:
        safe_sql = guard(plan.sql, tenant_id=user.tenant_id)
    except SqlRejected as exc:
        return AskOut(
            answerable=False,
            tool="sql",
            sql=plan.sql,
            refusal_reason=f"That query wasn't safe to run: {exc}",
            model_used=result.model,
            cached=result.cached,
        )

    async with readonly_session(user.tenant_id, user.role) as ro:
        cursor = await ro.execute(_text(safe_sql))
        columns = list(cursor.keys())
        fetched = cursor.fetchall()

    rows = [dict(zip(columns, _jsonable_row(r), strict=True)) for r in fetched]
    facts = _facts_from_rows(rows, columns)
    answer, narrate_model, narrate_cached = await _narrate(
        question,
        facts,
        deterministic_fallback=_render_answer(rows, columns),
        session=session,
        user=user,
        client=client,
        buffer=buffer,
        run_id=run_id,
    )
    return AskOut(
        answerable=True,
        answer=answer,
        tool="sql",
        sql=safe_sql,
        rows=rows,
        row_count=len(rows),
        show_table=_wants_table(question, len(rows)),
        model_used=narrate_model or result.model,
        cached=narrate_cached or result.cached,
        truncated=len(rows) >= MAX_ROWS,
    )


async def _answer_via_diff(
    question: str,
    history: Sequence[AskTurnIn],
    *,
    session: AsyncSession,
    user: AuthenticatedUser,
    client: LLMClient,
    buffer: LLMCallBuffer,
) -> AskOut:
    runs = (
        await session.scalars(
            select(Run)
            .where(Run.tenant_id == user.tenant_id, Run.status == "complete")
            .order_by(Run.started_at.desc())
            .limit(10)
        )
    ).all()
    if len(runs) < 2:
        return AskOut(
            answerable=False,
            tool="diff",
            refusal_reason="There's only one completed run so far — nothing to compare it to yet.",
        )

    to_run, from_run = _pick_runs_to_compare(question, runs)
    before = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.run_id == from_run.run_id))
    ).all()
    after = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.run_id == to_run.run_id))
    ).all()
    diff = diff_exceptions(
        [exception_from_row(e) for e in before], [exception_from_row(e) for e in after]
    )

    rows = _diff_rows(diff)
    facts = _facts_from_diff(diff, from_run.run_id, to_run.run_id)
    answer, model_used, cached = await _narrate(
        question,
        facts,
        deterministic_fallback=_render_diff_answer(diff),
        session=session,
        user=user,
        client=client,
        buffer=buffer,
        run_id=to_run.run_id,
    )
    return AskOut(
        answerable=True,
        answer=answer,
        tool="diff",
        rows=rows,
        row_count=len(rows),
        show_table=_wants_table(question, len(rows)),
        compared_from_run_id=from_run.run_id,
        compared_to_run_id=to_run.run_id,
        model_used=model_used,
        cached=cached,
    )


def _pick_runs_to_compare(question: str, runs: Sequence[Run]) -> tuple[Run, Run]:
    """``runs`` is newest first. "Since yesterday" picks the newest run from
    a strictly earlier calendar day than the newest run overall; anything
    else — "compare the last two runs", no qualifier at all — compares the
    two most recent runs, which is also what "yesterday" falls back to if
    every run so far happened today (true of most rehearsals)."""
    to_run = runs[0]
    if _YESTERDAY.search(question):
        for candidate in runs[1:]:
            if candidate.started_at.date() < to_run.started_at.date():
                return to_run, candidate
    return to_run, runs[1]


async def _narrate(
    question: str,
    facts: list[str],
    *,
    deterministic_fallback: str,
    session: AsyncSession,
    user: AuthenticatedUser,
    client: LLMClient,
    buffer: LLMCallBuffer,
    run_id: str | None,
) -> tuple[str, str | None, bool]:
    """Phrase ``facts`` as 1-3 conversational sentences answering ``question``.

    ``sql_narrate`` is in ``HAS_DOWNSTREAM_CHECK`` (fc.llm.schemas): its
    output is never auto-cached by ``client.call`` — only ``confirm()``
    writes it, and only once ``is_grounded`` has agreed every number the
    model stated was actually one of the facts it was handed. A narration
    that invents a number is discarded here, not shown, and the same
    deterministic rendering the table-only Ask tab used is returned instead.
    """
    fallback = NarrativeOut(narrative=deterministic_fallback)
    prompt = (
        "Question: "
        + question
        + "\n\nFacts (already computed, use only these numbers):\n"
        + ("\n".join(facts) if facts else "(no rows)")
    )
    result = await client.call(
        "sql_narrate",
        prompt=prompt,
        system=load_prompt("sql_narrate"),
        tenant_id=user.tenant_id,
        run_id=run_id,
        schema=NarrativeOut,
        requires=STRUCTURED,
        fallback=fallback.model_dump_json(),
    )
    narrated = NarrativeOut.model_validate_json(result.text).narrative

    if result.terminal:
        # The terminal's own fallback text — already exactly
        # `deterministic_fallback`, never cached, nothing to verify.
        answer = narrated
    elif is_grounded(narrated, facts):
        result = client.confirm(result, tenant_id=user.tenant_id, run_id=run_id)
        answer = narrated
    else:
        client.reject(result, tenant_id=user.tenant_id, run_id=run_id)
        answer = deterministic_fallback

    await persist_llm_calls(session, buffer, tenant_id=user.tenant_id)
    await session.commit()
    return answer, result.model, result.cached


def _sql_prompt(question: str, history: Sequence[AskTurnIn], run_id: str | None) -> str:
    lines = [f"Run scope: {run_id or 'most recent run'}"]
    if history:
        lines.append("")
        lines.append(
            "Conversation so far (resolve referents like 'those'/'it' from "
            "here, but write a fresh, complete, self-contained query — the "
            "underlying data can have changed since the earlier turn ran):"
        )
        for turn in history:
            lines.append(f"Q: {turn.question}")
            lines.append(f"A: {turn.answer}")
        lines.append("")
        lines.append("Current question:")
        lines.append(question)
    else:
        # No history: normalise so repeated phrasing of the same first
        # question hits the cache (§7.6) — the prompt is part of the cache
        # key, and a fresh conversation's opener is the case worth caching.
        lines.append("")
        lines.append("Current question:")
        lines.append(" ".join(question.strip().lower().split()))
    return "\n".join(lines)


def _facts_from_rows(rows: list[dict[str, Any]], columns: Sequence[str]) -> list[str]:
    """Every row, every column, already formatted the way a reader sees it —
    the only numbers ``sql_narrate`` is allowed to state."""
    return [", ".join(f"{col}: {_display(col, row[col])}" for col in columns) for row in rows]


def _facts_from_diff(diff: ReplayDiff, from_run_id: str, to_run_id: str) -> list[str]:
    facts = [
        f"from_run: {from_run_id}",
        f"to_run: {to_run_id}",
        f"added_count: {len(diff.added)}",
        f"removed_count: {len(diff.removed)}",
        f"changed_count: {len(diff.changed)}",
    ]
    for entry in diff.added:
        exc = entry.after
        facts.append(
            f"added {entry.exception_id}: category {exc.category if exc else 'unknown'}, "
            f"amount {fmt_inr(exc.amount_paise) if exc else 'unknown'} — {entry.why}"
        )
    for entry in diff.removed:
        exc = entry.before
        facts.append(
            f"removed {entry.exception_id}: category {exc.category if exc else 'unknown'}, "
            f"amount {fmt_inr(exc.amount_paise) if exc else 'unknown'} — {entry.why}"
        )
    for entry in diff.changed:
        facts.append(f"changed {entry.exception_id}: {entry.why}")
    return facts


def _diff_rows(diff: ReplayDiff) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    groups = (("added", diff.added), ("removed", diff.removed), ("changed", diff.changed))
    for kind, entries in groups:
        for entry in entries:
            rows.append({"change": kind, "exception_id": entry.exception_id, "why": entry.why})
    return rows


def _render_diff_answer(diff: ReplayDiff) -> str:
    """No model involved — the same "answer built from data, not phrased by
    a model" guarantee ``_render_answer`` gives the SQL path."""
    if diff.is_empty:
        return "No exceptions changed between the two runs."
    parts = []
    if diff.added:
        parts.append(f"{len(diff.added)} new")
    if diff.removed:
        parts.append(f"{len(diff.removed)} resolved")
    if diff.changed:
        parts.append(f"{len(diff.changed)} changed")
    return ", ".join(parts) + "."


def _text(sql: str) -> Any:
    from sqlalchemy import text

    return text(sql)


def _jsonable_row(row: Any) -> list[Any]:
    out: list[Any] = []
    for value in row:
        if isinstance(value, date | datetime):
            out.append(value.isoformat())
        elif isinstance(value, Decimal):
            out.append(str(value))
        else:
            out.append(value)
    return out


def _render_answer(rows: list[dict[str, Any]], columns: Sequence[str]) -> str:
    """The deterministic fallback answer, built from the rows with no model
    involved — used verbatim when no model is reachable, and as the safe
    answer ``_narrate`` falls back to when a narration fails grounding.
    Money columns are formatted through ``fmt_inr`` so paise never reach a
    reader as a bare integer.
    """
    if not rows:
        return "No rows matched."
    if len(rows) == 1:
        parts = [f"{col}: {_display(col, rows[0][col])}" for col in columns]
        return " · ".join(parts)
    return f"{len(rows)} rows. The first is: " + " · ".join(
        f"{col}: {_display(col, rows[0][col])}" for col in columns
    )


def _display(column: str, value: Any) -> str:
    if value is None:
        return "—"
    if column.endswith("_paise") and isinstance(value, int):
        return fmt_inr(value)
    if column.endswith("_paise") and isinstance(value, str) and value.lstrip("-").isdigit():
        return fmt_inr(int(value))
    return str(value)


# --- GET /agent/narrative/{run_id} -------------------------------------------


@router.get("/narrative/{run_id}", response_model=NarrativeOutModel)
async def get_narrative(
    run_id: str,
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
    client: LLMClient = Depends(get_llm_client),
    buffer: LLMCallBuffer = Depends(get_llm_buffer),
) -> NarrativeOutModel:
    """Generated on demand and served from the LLM disk cache.

    There is no ``runs.narrative`` column and the schema is frozen, so the cache
    *is* the storage — which is the right place for it anyway: prose that
    degrades to a template is not state, and a column would imply it was.
    """
    from api.generation import narrative_for_run

    narrative, result = await narrative_for_run(
        session, run_id=run_id, tenant_id=user.tenant_id, client=client
    )
    await persist_llm_calls(session, buffer, tenant_id=user.tenant_id)
    await session.commit()
    return NarrativeOutModel(
        run_id=run_id,
        narrative=narrative,
        generated_at=datetime.now(UTC),
        model_used=result.model,
        cached=result.cached,
    )


# --- GET /agent/health -------------------------------------------------------


@router.get("/health", response_model=HealthOut)
async def agent_health(
    run_id: str | None = None,
    client: LLMClient = Depends(get_llm_client),
) -> HealthOut:
    """§7.11. The header status strip, and the honest answer to "how does this
    scale" — ``health_scope`` says ``process``, because that is where the quota
    counters live."""
    from fc.llm.client import PROMPT_HASHES

    snapshot = client.health_snapshot()
    return HealthOut(
        tiers=snapshot["tiers"],
        budget=snapshot["budget"],
        mode=snapshot["mode"],
        degraded=snapshot["degraded"],
        health_scope=snapshot["health_scope"],
        calls_this_run=client.ledger.calls_for(run_id),
        calls_total=client.ledger.total,
        # A string, not a float: this is a display value, and a ratio rendered
        # to seventeen decimal places in a status strip helps nobody.
        cache_hit_rate=f"{client.ledger.cache_hit_rate:.0%}",
        sql_isolation=sql_isolation_layers(),
        prompts=dict(PROMPT_HASHES),
    )


__all__ = ["COMMAND_DECLARATIONS", "router"]
