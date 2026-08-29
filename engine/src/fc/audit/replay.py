"""Deterministic replay — PRD §16, Appendix E's ``superseded`` transition.

The demo moment: a rule's rate changes, a prior run replays against the new
ruleset over the exact same input, and the diff names precisely which past
decisions flip and why. Nothing about a rule change is trusted by assertion —
it is proven against every exception that rule could have touched.

Replay changes the ruleset, never the input: it runs the same already-ingested
events (the parent run's own ``event_ids``, not a re-ingestion) through
:func:`fc.pipeline.run_pipeline` with a *specified* ruleset — resolved by the
caller from a version or hash *before* calling this, since reaching for
"today's active rules" here would make replay non-deterministic against its
own stated purpose. Reading the parent run's stored ``config`` and
``input_hashes`` and resolving a ruleset version are both database reads, so
they happen in ``api/`` or ``db/``; this module only computes.

Two exception sets are compared by their ``event_ids``, not their
``exception_id`` — a fresh ULID every run can never be a join key across two
runs, while ``event_ids`` is stable: matching runs independently of the
ruleset (:func:`fc.pipeline.run_pipeline` calls ``run_cascade`` without
``rules`` at all), so the same underlying transactions group under the same
key in every run over the same input, and only classification can differ.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from fc.config import Config
from fc.ingest.aliases import AliasTable
from fc.models.exception_ import Exception_
from fc.models.money import fmt_inr
from fc.models.rule import Rule
from fc.models.transaction import TransactionEvent
from fc.pipeline import PipelineResult, run_pipeline

__all__ = ["DecisionDiff", "ReplayDiff", "ReplayResult", "diff_exceptions", "replay"]


#: The fields that make up "the decision" a rule change can move. Deliberately
#: excludes lifecycle fields (``status``, ``resolved_by``, ``resolved_at``,
#: ...): a freshly recomputed exception always starts ``status="open"``
#: (`fc.pipeline.run_pipeline` never applies a human's resolution), so
#: comparing status against a parent exception a human already resolved would
#: report "changed" on every single row regardless of the ruleset.
def _fingerprint(exc: Exception_) -> tuple[object, ...]:
    return (
        exc.category,
        exc.tier,
        exc.residual_paise,
        exc.confidence,
        exc.recommended_action,
        tuple(sorted((r.rule_id, r.version, r.explained_paise) for r in exc.rules_applied)),
    )


def _describe_change(before: Exception_, after: Exception_) -> str:
    parts: list[str] = []
    if before.category != after.category:
        parts.append(f"category {before.category} -> {after.category}")
    if before.tier != after.tier:
        parts.append(f"tier {before.tier} -> {after.tier}")
    if before.residual_paise != after.residual_paise:
        parts.append(
            f"residual {fmt_inr(before.residual_paise)} -> {fmt_inr(after.residual_paise)}"
        )
    if before.confidence != after.confidence:
        parts.append(f"confidence {before.confidence} -> {after.confidence}")
    if before.recommended_action != after.recommended_action:
        parts.append("recommended action changed")

    before_rules = {(r.rule_id, r.version) for r in before.rules_applied}
    after_rules = {(r.rule_id, r.version) for r in after.rules_applied}
    if before_rules != after_rules:
        newly_explained = after_rules - before_rules
        no_longer_explained = before_rules - after_rules
        if newly_explained:
            named = ", ".join(f"{rid} v{v}" for rid, v in sorted(newly_explained))
            parts.append(f"now explained by {named}")
        if no_longer_explained:
            named = ", ".join(f"{rid} v{v}" for rid, v in sorted(no_longer_explained))
            parts.append(f"no longer explained by {named}")

    return "; ".join(parts) if parts else "no observable change"


@dataclass(frozen=True)
class DecisionDiff:
    """One line of a replay diff: what a single underlying decision looked like
    before and after, keyed by the transactions it covers rather than an id
    that is never stable across two runs."""

    event_ids: tuple[str, ...]
    exception_id_before: str | None
    exception_id_after: str | None
    before: Exception_ | None
    after: Exception_ | None
    why: str

    @property
    def exception_id(self) -> str:
        """The PRD's single ``exception_id`` field: the newer run's id when it
        has one, otherwise the parent run's (a ``removed`` entry)."""
        result = self.exception_id_after or self.exception_id_before
        assert result is not None, "a DecisionDiff always has at least one exception_id"
        return result


@dataclass(frozen=True)
class ReplayDiff:
    """``changed``: present in both runs with a different fingerprint.
    ``added``: an exception in the newer run with no counterpart in the older one.
    ``removed``: an exception in the older run with no counterpart in the newer one —
    typically its gap became fully explained under the newer ruleset.

    Every list is sorted by ``event_ids`` so the diff is byte-identical for the
    same two inputs regardless of dict iteration order (CLAUDE.md hard rule 9).
    """

    changed: tuple[DecisionDiff, ...]
    added: tuple[DecisionDiff, ...]
    removed: tuple[DecisionDiff, ...]

    @property
    def is_empty(self) -> bool:
        return not (self.changed or self.added or self.removed)


def diff_exceptions(before: Sequence[Exception_], after: Sequence[Exception_]) -> ReplayDiff:
    """Compare two exception sets. General-purpose: also backs
    ``GET /runs/{run_id}/diff/{other_run_id}`` for any two materialised runs,
    not only a replay's parent and child.
    """
    before_by_key = {frozenset(exc.event_ids): exc for exc in before}
    after_by_key = {frozenset(exc.event_ids): exc for exc in after}

    changed: list[DecisionDiff] = []
    removed: list[DecisionDiff] = []
    added: list[DecisionDiff] = []

    for key in sorted(before_by_key, key=sorted):
        old = before_by_key[key]
        new = after_by_key.get(key)
        event_ids = tuple(sorted(key))
        if new is None:
            removed.append(
                DecisionDiff(
                    event_ids=event_ids,
                    exception_id_before=old.exception_id,
                    exception_id_after=None,
                    before=old,
                    after=None,
                    why="no longer an exception under the specified ruleset — "
                    "its gap is now fully explained",
                )
            )
        elif _fingerprint(old) != _fingerprint(new):
            changed.append(
                DecisionDiff(
                    event_ids=event_ids,
                    exception_id_before=old.exception_id,
                    exception_id_after=new.exception_id,
                    before=old,
                    after=new,
                    why=_describe_change(old, new),
                )
            )

    for key in sorted(after_by_key, key=sorted):
        if key in before_by_key:
            continue
        new = after_by_key[key]
        added.append(
            DecisionDiff(
                event_ids=tuple(sorted(key)),
                exception_id_before=None,
                exception_id_after=new.exception_id,
                before=None,
                after=new,
                why="new exception under the specified ruleset — no residual gap in the parent run",
            )
        )

    return ReplayDiff(changed=tuple(changed), added=tuple(added), removed=tuple(removed))


@dataclass(frozen=True)
class ReplayResult:
    run_id: str
    parent_run_id: str
    pipeline: PipelineResult
    diff: ReplayDiff


def replay(
    *,
    parent_run_id: str,
    parent_exceptions: Sequence[Exception_],
    events: Sequence[TransactionEvent],
    cfg: Config,
    rules: Sequence[Rule],
    new_run_id: str,
    tenant_id: str,
    issue_id: Callable[[str], str],
    created_at: datetime,
    aliases: AliasTable | None = None,
) -> ReplayResult:
    """Recompute ``parent_run_id``'s decisions under ``rules`` and diff the result.

    ``events`` must be the parent run's own already-ingested events (same
    ``event_id`` values it stored) — replay changes the ruleset, not the
    input. ``rules`` is the specified ruleset the caller already resolved;
    this function never reaches for "today's" active rules on its own, which
    is what makes a June reconciliation replay correctly against June's rate
    months after a July rate change (PRD §16.1).
    """
    pipeline = run_pipeline(
        events,
        cfg=cfg,
        rules=rules,
        run_id=new_run_id,
        tenant_id=tenant_id,
        issue_id=issue_id,
        created_at=created_at,
        aliases=aliases,
    )
    diff = diff_exceptions(parent_exceptions, pipeline.exceptions)
    return ReplayResult(
        run_id=new_run_id, parent_run_id=parent_run_id, pipeline=pipeline, diff=diff
    )
