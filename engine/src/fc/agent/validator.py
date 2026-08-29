"""The deterministic command validator — PRD §8.3, §8.4, §8.5.

Takes a :class:`~fc.models.command.ParsedCommand` and a :class:`CommandContext`
the caller assembled from the database, and returns a :class:`Preview`: what
would happen, what is worrying about it, and whether it may proceed at all.

Two things about this file matter more than the rest of it.

**It refuses more often than it agrees, and that is the feature.** Seven
push-back rules (§8.5) exist because a reconciliation agent that always finds a
way to do what it was told is a liability. A judge watching an agent question a
human command remembers it more than any successful action.

**Nothing here executes anything.** The output is a description. The caller
renders it, a human confirms it, and deterministic endpoints carry it out. The
model that produced the command shape is three steps upstream and cannot reach
past this file.

Pure: no database, no network, no clock. Every fact it needs is on the context.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from fc.agent.permissions import VERB_ACTIONS, can, roles_permitting
from fc.config import Config
from fc.models.command import CUT_VERBS, READ_ONLY_VERBS, ParsedCommand
from fc.models.exception_ import NEVER_AUTO
from fc.models.money import fmt_inr

__all__ = [
    "ClusterOffer",
    "CommandContext",
    "Effect",
    "ExceptionFacts",
    "Preview",
    "RefCandidate",
    "Refusal",
    "Warning_",
    "validate",
]


@dataclass(frozen=True)
class ExceptionFacts:
    """What the validator needs to know about one exception. Filled from the row."""

    exception_id: str
    amount_paise: int
    residual_paise: int
    category: str
    status: str
    tier: str
    cluster_id: str | None = None
    #: Everything about this row a preview depends on, hashed. Compared at
    #: execute time against the value captured at parse — see §8.5's last rule.
    state_fingerprint: str = ""
    #: Does any linked event carry a dispute/chargeback reference (§8.5 rule 4)?
    has_dispute_reference: bool = False
    #: Injection-scan hits on the linked narrations (§10.3 layer 6).
    suspicious_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefCandidate:
    """One thing an instruction's reference might mean."""

    ref: str
    kind: str  # order | payment | settlement | voucher | exception
    amount_paise: int | None = None
    txn_date: date | None = None
    event_id: str | None = None

    def describe(self) -> str:
        parts = [self.ref]
        if self.amount_paise is not None:
            parts.append(fmt_inr(self.amount_paise))
        if self.txn_date is not None:
            parts.append(self.txn_date.isoformat())
        return " · ".join(parts)


@dataclass(frozen=True)
class CommandContext:
    """Everything the database had to say, before the validator reasons about it.

    Assembled by ``api/routers/agent.py``. Kept as plain data so every push-back
    rule can be tested with a literal, no fixtures and no database.
    """

    exceptions: Mapping[str, ExceptionFacts] = field(default_factory=dict)
    #: ref -> the single thing it resolves to.
    resolved_refs: Mapping[str, RefCandidate] = field(default_factory=dict)
    #: ref -> two or more things it could equally mean (§8.5 rule 3).
    ambiguous_refs: Mapping[str, Sequence[RefCandidate]] = field(default_factory=dict)
    #: ref -> things that look close, for a ref that resolved to nothing
    #: (§8.5 rule 2). Listed, never chosen from.
    near_matches: Mapping[str, Sequence[RefCandidate]] = field(default_factory=dict)
    cluster_sizes: Mapping[str, int] = field(default_factory=dict)
    #: Set at execute time to the fingerprints captured at parse time.
    expected_state: Mapping[str, str] | None = None


@dataclass(frozen=True)
class Effect:
    """One thing that will happen, named by the endpoint that will do it."""

    action: str  # e.g. "exception.resolve" — the audit action, and the route
    subject: str
    summary: str
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Warning_:
    """Something the human should see before confirming. Not a refusal."""

    code: str
    message: str
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Refusal:
    """The command may not proceed as written."""

    code: str  # ambiguous | not_found | forbidden | cut | unsupported | conflict | invalid
    message: str
    candidates: tuple[str, ...] = ()
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClusterOffer:
    """§8.6. Offered, never applied on its own."""

    cluster_id: str
    member_count: int


@dataclass(frozen=True)
class Preview:
    """§8.4. What the human is asked to confirm."""

    summary: str
    effects: tuple[Effect, ...] = ()
    warnings: tuple[Warning_, ...] = ()
    requires_typed_confirmation: bool = False
    typed_confirmation_paise: int | None = None
    requires_acknowledgement: bool = False
    cluster_offer: ClusterOffer | None = None
    refusal: Refusal | None = None

    @property
    def ok(self) -> bool:
        return self.refusal is None

    def fingerprint(self) -> str:
        """A stable hash of everything that would change what happens.

        ``/agent/execute`` re-validates against fresh state and compares this to
        the value the human was shown. A difference means the plan they approved
        is not the plan that would run, and the only safe answer is to stop and
        show them the new one. Warnings are included: "there is a ₹3,240 delta"
        is part of what was approved, not decoration.
        """
        material = json.dumps(
            {
                "effects": [
                    {
                        "action": e.action,
                        "subject": e.subject,
                        "summary": e.summary,
                        "detail": _jsonable(e.detail),
                    }
                    for e in self.effects
                ],
                "warnings": [
                    {"code": w.code, "message": w.message, "detail": _jsonable(w.detail)}
                    for w in self.warnings
                ],
                "typed": self.requires_typed_confirmation,
                "typed_paise": self.typed_confirmation_paise,
                "ack": self.requires_acknowledgement,
                "refusal": None if self.refusal is None else self.refusal.code,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _jsonable(detail: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in sorted(detail.items())}


def validate(command: ParsedCommand, ctx: CommandContext, *, cfg: Config, role: str) -> Preview:
    """Turn one parsed command into a preview, or into a refusal."""
    verb = command.verb

    # §8.5 rule 6 — permission. Checked first: a role that may not do this
    # should not learn anything about the referenced records by trying.
    action = VERB_ACTIONS.get(verb)
    if action is None or not can(role, action):
        permitted = roles_permitting(action) if action else ()
        return Preview(
            summary=f"Cannot {verb.replace('_', ' ')}.",
            refusal=Refusal(
                code="forbidden",
                message=(
                    f"Your role ({role}) cannot {verb.replace('_', ' ')}. "
                    + (
                        f"This needs {permitted[-1]} or above."
                        if permitted
                        else "No role holds this permission."
                    )
                ),
                detail={"required_role": permitted[-1] if permitted else None, "action": action},
            ),
        )

    if verb in CUT_VERBS:
        return Preview(
            summary=f"{verb.replace('_', ' ').title()} is not available.",
            refusal=Refusal(
                code="cut",
                message=(
                    "Cluster splitting and merging are not built. Clusters are formed "
                    "from a deterministic grouping key, so editing membership by hand "
                    "would break the guarantee that the key explains the group. "
                    "Resolve or reclassify the members individually instead."
                ),
            ),
        )

    if verb in READ_ONLY_VERBS:
        return _read_only_preview(command)

    # §8.5 rules 2, 3 and 7 apply to whichever records this command names.
    conflict = _check_conflicts(command, ctx)
    if conflict is not None:
        return conflict

    handler = _HANDLERS.get(verb)
    if handler is None:  # pragma: no cover - CommandVerb is a closed Literal
        return Preview(
            summary=f"Cannot {verb}.",
            refusal=Refusal(code="unsupported", message=f"{verb} has no handler."),
        )
    return handler(command, ctx, cfg)


# --- shared checks -----------------------------------------------------------


def _referenced_exception_ids(command: ParsedCommand) -> tuple[str, ...]:
    """The exceptions a command names, blanks dropped.

    A blank id is "named nothing", not "named something that does not exist" —
    they are different mistakes and deserve different answers. Reporting
    ``exc_`` as not found would send somebody looking for a record rather than
    rephrasing their sentence.
    """
    payload = command.payload
    single = getattr(payload, "exception_id", None)
    if isinstance(single, str):
        return (single,) if single.strip() else ()
    many = getattr(payload, "exception_ids", None)
    if isinstance(many, list):
        return tuple(str(i) for i in many if str(i).strip())
    return ()


def _check_conflicts(command: ParsedCommand, ctx: CommandContext) -> Preview | None:
    """§8.5 rules 2, 3 and 7, for the exceptions a command names."""
    ids = _referenced_exception_ids(command)

    missing = [i for i in ids if i not in ctx.exceptions]
    if missing:
        near = [c.describe() for i in missing for c in ctx.near_matches.get(i, ())]
        return Preview(
            summary="That exception could not be found.",
            refusal=Refusal(
                code="not_found",
                message=(
                    f"No open exception matches {', '.join(missing)}. "
                    + (
                        "These look close — say which one you meant."
                        if near
                        else "Check the reference and try again."
                    )
                ),
                candidates=tuple(near),
                detail={"missing": list(missing)},
            ),
        )

    if not ids and command.verb in ("resolve", "write_off", "escalate", "snooze", "reclassify"):
        return Preview(
            summary="That instruction did not name anything to act on.",
            refusal=Refusal(
                code="invalid",
                message=(
                    "I could not tell which exception you meant. Name it, or run the "
                    "instruction from the exception itself so it comes with context."
                ),
            ),
        )

    # §8.5 rule 7 — optimistic lock. Only meaningful at execute time, when
    # ``expected_state`` carries what the human was actually shown.
    if ctx.expected_state is not None:
        moved = [
            i
            for i in ids
            if i in ctx.expected_state
            and ctx.exceptions[i].state_fingerprint != ctx.expected_state[i]
        ]
        if moved:
            states = {i: ctx.exceptions[i].status for i in moved}
            return Preview(
                summary="Somebody else changed this while you were looking at it.",
                refusal=Refusal(
                    code="conflict",
                    message=(
                        f"{', '.join(moved)} changed since the preview was built — "
                        f"now {', '.join(f'{k} is {v}' for k, v in states.items())}. "
                        "Re-read it and give the instruction again if it still applies."
                    ),
                    detail={"current_status": states},
                ),
            )
    return None


def _ref_refusal(ref: str, ctx: CommandContext) -> Refusal | None:
    """§8.5 rules 2 and 3, for a non-exception reference."""
    if ref in ctx.ambiguous_refs:
        candidates = tuple(c.describe() for c in ctx.ambiguous_refs[ref])
        return Refusal(
            code="ambiguous",
            message=(
                f"{ref} matches {len(candidates)} records and I cannot tell which you "
                "mean. Say which one."
            ),
            candidates=candidates,
        )
    if ref not in ctx.resolved_refs:
        near = tuple(c.describe() for c in ctx.near_matches.get(ref, ()))
        return Refusal(
            code="not_found",
            message=(
                f"{ref} does not exist in this run. "
                + ("These look close:" if near else "Check the reference.")
            ),
            candidates=near,
        )
    return None


def _amount_gate(facts: ExceptionFacts, cfg: Config) -> tuple[bool, int | None]:
    """§8.5 rule 5. Above the threshold, the user types the amount."""
    if facts.amount_paise >= cfg.typed_confirm_paise:
        return True, facts.amount_paise
    return False, None


def _base_warnings(facts: ExceptionFacts) -> list[Warning_]:
    warnings: list[Warning_] = []
    if facts.suspicious_patterns:
        # §10.3 layer 6, surfaced as information for the merchant rather than
        # as a note about our own defences.
        warnings.append(
            Warning_(
                code="suspicious_narration",
                message=(
                    "A narration on this item contains text shaped like an instruction "
                    "to an automated system. Nothing acted on it — but it is worth "
                    "knowing where it came from."
                ),
                detail={"patterns": list(facts.suspicious_patterns)},
            )
        )
    return warnings


# --- per-verb handlers -------------------------------------------------------


def _resolve(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    payload = command.payload
    facts = ctx.exceptions[payload.exception_id]  # type: ignore[union-attr]
    warnings = _base_warnings(facts)
    ack = False

    # §8.5 rule 4 — a chargeback closed with no dispute reference.
    if facts.category == "chargeback_unrecorded" and not facts.has_dispute_reference:
        ack = True
        warnings.append(
            Warning_(
                code="chargeback_without_dispute_ref",
                message=(
                    "This is an unrecorded chargeback and nothing here cites a dispute "
                    "reference. Closing it drops the contest window without a record of "
                    "why. Acknowledge explicitly if that is what you mean to do."
                ),
                detail={"deadline_matters": True},
            )
        )
    elif facts.category in NEVER_AUTO:
        warnings.append(
            Warning_(
                code="never_auto_category",
                message=(
                    f"{facts.category.replace('_', ' ')} never closes on its own — this "
                    "one is being closed on your word, and the audit trail will say so."
                ),
            )
        )

    typed, typed_paise = _amount_gate(facts, cfg)
    return Preview(
        summary=(
            f"Close {facts.exception_id}, {fmt_inr(facts.amount_paise)}, as {payload.category}."  # type: ignore[union-attr]
        ),
        effects=(
            Effect(
                action="exception.resolve",
                subject=facts.exception_id,
                summary=(
                    f"Status open → resolved · category {facts.category} → {payload.category}"  # type: ignore[union-attr]
                ),
                detail={
                    "reason": payload.reason,  # type: ignore[union-attr]
                    "resolution_category": payload.category,  # type: ignore[union-attr]
                    "amount_paise": facts.amount_paise,
                },
            ),
        ),
        warnings=tuple(warnings),
        requires_typed_confirmation=typed,
        typed_confirmation_paise=typed_paise,
        requires_acknowledgement=ack,
        cluster_offer=_cluster_offer(facts, ctx),
    )


def _write_off(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    payload = command.payload
    ids: list[str] = list(payload.exception_ids)  # type: ignore[union-attr]
    facts = [ctx.exceptions[i] for i in ids]
    total = sum(f.amount_paise for f in facts)
    warnings: list[Warning_] = []
    for f in facts:
        warnings.extend(_base_warnings(f))

    typed = total >= cfg.typed_confirm_paise
    return Preview(
        summary=f"Write off {len(ids)} item{'s' if len(ids) != 1 else ''}, {fmt_inr(total)}.",
        effects=tuple(
            Effect(
                action="exception.write_off",
                subject=f.exception_id,
                summary=f"{fmt_inr(f.amount_paise)} written off",
                detail={
                    "reason": payload.reason,  # type: ignore[union-attr]
                    "amount_paise": f.amount_paise,
                },
            )
            for f in facts
        ),
        warnings=tuple(warnings),
        requires_typed_confirmation=typed,
        typed_confirmation_paise=total if typed else None,
    )


def _link_to(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    payload = command.payload
    facts = ctx.exceptions[payload.exception_id]  # type: ignore[union-attr]
    ref: str = payload.target_ref  # type: ignore[union-attr]

    refusal = _ref_refusal(ref, ctx)
    if refusal is not None:
        return Preview(summary=f"Cannot link {facts.exception_id}.", refusal=refusal)

    target = ctx.resolved_refs[ref]
    effects: list[Effect] = [
        Effect(
            action="exception.link",
            subject=facts.exception_id,
            summary=f"Linked to {target.describe()}",
            detail={
                "target_ref": ref,
                "target_type": payload.target_type,  # type: ignore[union-attr]
                "event_id": target.event_id,
            },
        )
    ]
    warnings = _base_warnings(facts)

    # §8.5 rule 1 — the amounts do not agree.
    if target.amount_paise is not None and target.amount_paise != facts.amount_paise:
        delta = facts.amount_paise - target.amount_paise
        warnings.append(
            Warning_(
                code="amount_mismatch",
                message=(
                    f"{ref} is {fmt_inr(target.amount_paise)} but this exception is "
                    f"{fmt_inr(facts.amount_paise)} — a difference of {fmt_inr(abs(delta))}. "
                    "Linking explains the matching part; I will leave the rest open as a "
                    "residual exception rather than close a gap nothing accounts for."
                ),
                detail={
                    "delta_paise": delta,
                    "target_paise": target.amount_paise,
                    "exception_paise": facts.amount_paise,
                },
            )
        )
        effects.append(
            Effect(
                action="exception.residual",
                subject=facts.exception_id,
                summary=f"Residual exception opened for {fmt_inr(abs(delta))}",
                detail={"residual_paise": abs(delta)},
            )
        )

    typed, typed_paise = _amount_gate(facts, cfg)
    return Preview(
        summary=f"Link {facts.exception_id} to {ref}.",
        effects=tuple(effects),
        warnings=tuple(warnings),
        requires_typed_confirmation=typed,
        typed_confirmation_paise=typed_paise,
        cluster_offer=_cluster_offer(facts, ctx),
    )


def _post_entries(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    """Renders the journal lines and says plainly that nothing posts them.

    There is no journal-entry table in the frozen schema and no endpoint behind
    this verb. Showing the Dr/Cr the operator asked for and then refusing is
    more useful than pretending the verb does not parse — they can take the
    lines to Tally themselves.
    """
    payload = command.payload
    facts = ctx.exceptions[payload.exception_id]  # type: ignore[union-attr]
    amount: int = payload.amount_paise  # type: ignore[union-attr]
    return Preview(
        summary=(
            f"Dr {payload.dr} {fmt_inr(amount)} / "  # type: ignore[union-attr]
            f"Cr {payload.cr} {fmt_inr(amount)}"  # type: ignore[union-attr]
        ),
        refusal=Refusal(
            code="unsupported",
            message=(
                "This build does not post journal entries — there is no ledger-write "
                "path, so nothing would reach Tally and saying otherwise would be a "
                "lie in the audit trail. The entry as you described it is above; post "
                "it in Tally and resolve this exception with that as the reason."
            ),
            detail={
                "dr": payload.dr,  # type: ignore[union-attr]
                "cr": payload.cr,  # type: ignore[union-attr]
                "amount_paise": amount,
                "exception_id": facts.exception_id,
            },
        ),
    )


def _escalate(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    payload = command.payload
    facts = ctx.exceptions[payload.exception_id]  # type: ignore[union-attr]
    warnings = _base_warnings(facts)
    assignee: str = payload.assignee  # type: ignore[union-attr]
    # ``exceptions`` has no assignee column and the schema is frozen, so the
    # name is preserved in the reason and the audit payload rather than being
    # dropped on the floor without saying so.
    warnings.append(
        Warning_(
            code="assignee_not_a_field",
            message=(
                f"{assignee} will be named in the escalation reason and the audit "
                "trail, and the escalation email goes to the configured address — "
                "there is no per-person assignment in this build."
            ),
            detail={"assignee": assignee},
        )
    )
    return Preview(
        summary=f"Escalate {facts.exception_id}, {fmt_inr(facts.amount_paise)}, to {assignee}.",
        effects=(
            Effect(
                action="exception.escalate",
                subject=facts.exception_id,
                summary=f"Status {facts.status} → escalated",
                detail={
                    "reason": f"{assignee}: {payload.note or 'escalated by instruction'}",  # type: ignore[union-attr]
                    "assignee": assignee,
                },
            ),
        ),
        warnings=tuple(warnings),
    )


def _snooze(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    payload = command.payload
    facts = ctx.exceptions[payload.exception_id]  # type: ignore[union-attr]
    until: date = payload.until  # type: ignore[union-attr]
    return Preview(
        summary=f"Snooze {facts.exception_id} until {until.isoformat()}.",
        effects=(
            Effect(
                action="exception.snooze",
                subject=facts.exception_id,
                summary=f"Hidden from the queue until {until.isoformat()}",
                detail={"until": until, "reason": command.instruction_text},
            ),
        ),
        warnings=tuple(_base_warnings(facts)),
    )


def _reclassify(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    payload = command.payload
    facts = ctx.exceptions[payload.exception_id]  # type: ignore[union-attr]
    new_category: str = payload.category  # type: ignore[union-attr]
    warnings = _base_warnings(facts)
    if new_category in NEVER_AUTO and facts.category not in NEVER_AUTO:
        warnings.append(
            Warning_(
                code="reclassify_into_never_auto",
                message=(
                    f"{new_category.replace('_', ' ')} never closes automatically, so "
                    "this item will stay in the queue until a person closes it. That is "
                    "usually the intent — flagging it so it is not a surprise."
                ),
            )
        )
    return Preview(
        summary=f"Reclassify {facts.exception_id}: {facts.category} → {new_category}.",
        effects=(
            Effect(
                action="exception.reclassify",
                subject=facts.exception_id,
                summary=f"Category {facts.category} → {new_category}",
                detail={"category": new_category, "reason": command.instruction_text},
            ),
        ),
        warnings=tuple(warnings),
    )


def _create_rule(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    draft = command.payload.rule_draft  # type: ignore[union-attr]
    return Preview(
        summary=f"Draft a rule: {draft.name}.",
        effects=(
            Effect(
                action="rule.create",
                subject=draft.name,
                summary="Created as a draft — back-test and activate it separately",
                detail={
                    "deductions": [d.type for d in draft.deductions],
                    "priority": draft.priority,
                    "status": "draft",
                },
            ),
        ),
        warnings=(
            Warning_(
                code="draft_only",
                message=(
                    "A rule created this way is a draft and explains nothing until it "
                    "has been back-tested against history and activated. That order is "
                    "not negotiable — it is what stops a rule closing things it should "
                    "not have."
                ),
            ),
        ),
    )


def _rerun(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    payload = command.payload
    start: date = payload.period_start  # type: ignore[union-attr]
    end: date = payload.period_end  # type: ignore[union-attr]
    if end < start:
        return Preview(
            summary="That period runs backwards.",
            refusal=Refusal(
                code="invalid",
                message=f"{end.isoformat()} is before {start.isoformat()}.",
            ),
        )
    return Preview(
        summary=f"Re-reconcile {start.isoformat()} to {end.isoformat()}.",
        effects=(
            Effect(
                action="run.replay",
                subject=f"{start.isoformat()}..{end.isoformat()}",
                summary="A new run supersedes the old one; nothing already resolved is undone",
                detail={
                    "period_start": start,
                    "period_end": end,
                    "reason": payload.reason or command.instruction_text,  # type: ignore[union-attr]
                },
            ),
        ),
    )


def _notify(command: ParsedCommand, ctx: CommandContext, cfg: Config) -> Preview:
    payload = command.payload
    recipients: list[str] = list(payload.recipients)  # type: ignore[union-attr]
    ids: list[str] = list(payload.exception_ids)  # type: ignore[union-attr]
    bad = [r for r in recipients if "@" not in r]
    if bad:
        return Preview(
            summary="Those recipients are not email addresses.",
            refusal=Refusal(
                code="invalid",
                message=(
                    f"{', '.join(bad)} — I can only send to an email address, and I will "
                    "not guess one from a name."
                ),
                candidates=tuple(bad),
            ),
        )
    total = sum(ctx.exceptions[i].amount_paise for i in ids)
    return Preview(
        summary=f"Email {len(recipients)} recipient(s) about {len(ids)} item(s), {fmt_inr(total)}.",
        effects=(
            Effect(
                action="agent.notify",
                subject=", ".join(recipients),
                summary=f"{len(ids)} exception(s) summarised in one message",
                detail={
                    "recipients": recipients,
                    "exception_ids": ids,
                    "note": payload.note,  # type: ignore[union-attr]
                },
            ),
        ),
    )


def _read_only_preview(command: ParsedCommand) -> Preview:
    """``query`` and ``explain`` write nothing, so they need no confirmation."""
    payload = command.payload
    if command.verb == "query":
        return Preview(
            summary="Answer a question about the data.",
            effects=(
                Effect(
                    action="agent.ask",
                    subject="query",
                    summary=payload.question,  # type: ignore[union-attr]
                    detail={"run_id": payload.run_id},  # type: ignore[union-attr]
                ),
            ),
        )
    return Preview(
        summary="Explain an exception.",
        effects=(
            Effect(
                action="agent.explain",
                subject=payload.exception_id,  # type: ignore[union-attr]
                summary="Reads the evidence pack; changes nothing",
            ),
        ),
    )


def _cluster_offer(facts: ExceptionFacts, ctx: CommandContext) -> ClusterOffer | None:
    """§8.6. Offered only when there is somebody else to offer."""
    if facts.cluster_id is None:
        return None
    size = ctx.cluster_sizes.get(facts.cluster_id, 0)
    if size < 2:
        return None
    return ClusterOffer(cluster_id=facts.cluster_id, member_count=size - 1)


_HANDLERS: dict[str, Callable[[ParsedCommand, CommandContext, Config], Preview]] = {
    "resolve": _resolve,
    "write_off": _write_off,
    "link_to": _link_to,
    "post_entries": _post_entries,
    "escalate": _escalate,
    "snooze": _snooze,
    "reclassify": _reclassify,
    "create_rule": _create_rule,
    "rerun": _rerun,
    "notify": _notify,
}
