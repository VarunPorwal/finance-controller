"""The matching cascade — PRD §6.3.

Stages run in order, cheapest and most certain first, and a row matched at one
stage never reaches the next. That ordering is the design, not an optimisation:
collapsing the stages into one scoring function would lose the reason a match
was made, which is the only thing that makes the evidence pack meaningful.

All five §6.3 stages run, followed by §6.4 three-way resolution, which is a
resolution pass over the groups the cascade formed rather than a sixth stage.

A group is only as provable as its weakest leg. ``auto_closed`` is therefore
computed across *every* evidence entry, never taken from the stage that happened
to form the group: a fuzzy leg extended into an ``exact_ref`` group must stop
that group closing on its own, and asking only the host stage would let it
through at confidence 1.0 with an unproven row inside.

Nothing in this package imports ``fc.llm`` - the LLM never decides whether
something is reconciled (CLAUDE.md hard rule 2). ``tests/unit/test_architecture.py``
enforces it by AST scan.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from fc.config import Config
from fc.matching import three_way
from fc.matching.blocking import BlockIndex, BlockingStats, build_blocks
from fc.matching.confidence import ConfidenceInputs, derive
from fc.matching.ledger_refs import LedgerRefIndex, index_ledger_refs
from fc.matching.stages import StageMatch, StageOutput, StageRefusal, stage_may_auto_close
from fc.matching.stages import date_shift as date_shift_stage
from fc.matching.stages import exact_ref as exact_ref_stage
from fc.matching.stages import fee_adjusted as fee_adjusted_stage
from fc.matching.stages import fuzzy as fuzzy_stage
from fc.matching.stages import many_to_one as many_to_one_stage
from fc.models.exception_ import ExceptionCategory
from fc.models.match import (
    MatchEvidence,
    MatchResult,
    MatchStage,
    group_confidence_cap,
)
from fc.models.transaction import Source, TransactionEvent

__all__ = ["CASCADE_ORDER", "CascadeResult", "run_cascade"]

#: The §6.3 order: cheapest and most certain first.
CASCADE_ORDER: tuple[MatchStage, ...] = (
    "exact_ref",
    "fee_adjusted",
    "date_shift",
    "many_to_one",
    "fuzzy",
)


@dataclass(frozen=True)
class CascadeResult:
    """Everything one cascade run decided, refused, and measured."""

    matches: tuple[MatchResult, ...]
    unmatched_event_ids: tuple[str, ...]
    blocking: BlockingStats
    ledger_refs: LedgerRefIndex
    stage_counts: Mapping[MatchStage, int]
    abstentions: Mapping[MatchStage, tuple[str, ...]]
    diagnostics: Mapping[str, int]
    #: Every categorised refusal, from the stages and from three-way resolution.
    #: An exception the pipeline will later rank starts life here.
    refusals: tuple[StageRefusal, ...] = ()
    #: How many matches the §6.6 three-way bonus actually moved. Zero means the
    #: bonus is decoration and should be removed rather than left in.
    three_way_bonus_applied: int = 0
    matched_event_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def refusal_counts(self) -> Mapping[ExceptionCategory, int]:
        counts: dict[ExceptionCategory, int] = {}
        for refusal in self.refusals:
            counts[refusal.category] = counts.get(refusal.category, 0) + 1
        return dict(sorted(counts.items()))


def run_cascade(
    events: Sequence[TransactionEvent],
    *,
    cfg: Config,
    run_id: str,
    tenant_id: str,
    issue_id: Callable[[str], str],
    created_at: datetime,
) -> CascadeResult:
    """Run the stages in order over ``events``.

    ``issue_id`` and ``created_at`` are injected exactly as in ``fc/ingest/*``:
    decision code never reads the wall clock, so a seeded run is byte-identical
    (CLAUDE.md hard rule 9).
    """
    by_id = {event.event_id: event for event in events}
    ledger_refs = index_ledger_refs(events)
    index = build_blocks(events, cfg=cfg)

    claimed: set[str] = set()
    results: list[MatchResult] = []
    stage_counts: dict[MatchStage, int] = {}
    abstentions: dict[MatchStage, tuple[str, ...]] = {}
    diagnostics: dict[str, int] = {}
    refusals: list[StageRefusal] = []
    bonus_applied = 0
    dropped_spanning_two_groups = 0

    #: event id -> index into ``results``, so a later stage can extend a group.
    owner: dict[str, int] = {}

    for stage in CASCADE_ORDER:
        remaining = [e for e in events if e.event_id not in claimed]
        output = _run_stage(
            stage,
            remaining,
            all_events=events,
            unmatched=frozenset(e.event_id for e in remaining),
            index=index,
            ledger_refs=ledger_refs,
            cfg=cfg,
        )

        accepted = 0
        for found in output.matches:
            decided = found.decided
            # Nothing already settled may be re-decided: that is what "a row
            # matched at one stage never reaches the next" means.
            if any(event_id in claimed for event_id in decided):
                continue

            # Asked over every member, not just the context rows. A stage that
            # forms an N:1 group sets ``owner`` for all of them while claiming
            # only its anchor, so a later stage naming one of those members would
            # otherwise see no host and build a rival group around it - tripping
            # the one-event-one-group assertion at the end of the run.
            hosts = {owner[e] for e in found.event_ids if e in owner}
            if len(hosts) > 1:
                # The stage reconciled against rows that already belong to two
                # different groups. Merging them on this evidence would assert
                # something no stage proved, so decline - and count it, because a
                # silently dropped match is indistinguishable from one that was
                # never found.
                dropped_spanning_two_groups += 1
                continue

            if hosts:
                index_of_host = hosts.pop()
                results[index_of_host], was_bonused = _extend(
                    results[index_of_host], found, by_id=by_id, cfg=cfg
                )
                # Counted on this path too. Leaving it to the new-group branch
                # alone under-measured the bonus by every extended group, which
                # today is every fee_adjusted and many_to_one match there is.
                bonus_applied += int(was_bonused)
                for event_id in decided:
                    owner[event_id] = index_of_host
            else:
                result, was_bonused = _to_match_result(
                    found,
                    by_id=by_id,
                    cfg=cfg,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    issue_id=issue_id,
                    created_at=created_at,
                )
                results.append(result)
                bonus_applied += int(was_bonused)
                for event_id in found.event_ids:
                    owner[event_id] = len(results) - 1

            # Membership and the claimed set must not diverge: a row inside a
            # group that is still reported unmatched would be raised as an
            # exception for something already reconciled.
            claimed.update(found.event_ids)
            accepted += 1

        stage_counts[stage] = accepted
        abstentions[stage] = output.abstained
        refusals.extend(output.refusals)
        for key, value in output.diagnostics.items():
            diagnostics[f"{stage}.{key}"] = value

    # §6.4 runs after two-way matching, over the groups it produced - not instead
    # of it. It may attach a ledger leg, and it may refuse a group that turns out
    # to hold two indistinguishable ones.
    outcome = three_way.resolve(
        results,
        events,
        claimed=frozenset(claimed),
        ledger_refs=ledger_refs,
        cfg=cfg,
    )
    results = list(outcome.matches)
    refusals.extend(outcome.refusals)
    bonus_applied += outcome.bonus_applied
    claimed.update(outcome.attached_event_ids)
    for key, value in outcome.diagnostics.items():
        diagnostics[f"three_way.{key}"] = value

    # Auto-close is settled here, once, over the finished groups: every leg must
    # permit it, the confidence must clear the threshold, and no NEVER_AUTO
    # refusal may name a row inside the group. Deciding it earlier would mean
    # deciding it before three-way had said whether the books record this money
    # once or twice.
    blocked = {e for refusal in refusals if refusal.never_auto for e in refusal.event_ids}
    results = [
        result.model_copy(
            update={
                "auto_closed": (
                    not blocked & set(result.event_ids)
                    and group_auto_closable(result.evidence, result.confidence, cfg)
                )
            }
        )
        for result in results
    ]

    # The cascade's central invariant: one event, at most one group.
    assigned = [event_id for result in results for event_id in result.event_ids]
    assert len(assigned) == len(set(assigned)), "an event landed in two match groups"

    diagnostics["ledger_rows_without_reference"] = len(ledger_refs.without_reference)
    diagnostics["matches_dropped_spanning_two_groups"] = dropped_spanning_two_groups
    diagnostics["auto_close_blocked_by_never_auto"] = sum(
        1 for result in results if blocked & set(result.event_ids)
    )

    return CascadeResult(
        matches=tuple(results),
        unmatched_event_ids=tuple(sorted(e.event_id for e in events if e.event_id not in claimed)),
        blocking=index.stats,
        ledger_refs=ledger_refs,
        stage_counts=stage_counts,
        abstentions=abstentions,
        diagnostics=diagnostics,
        refusals=tuple(refusals),
        three_way_bonus_applied=bonus_applied,
        matched_event_ids=frozenset(claimed),
    )


def _run_stage(
    stage: MatchStage,
    events: Sequence[TransactionEvent],
    *,
    all_events: Sequence[TransactionEvent],
    unmatched: frozenset[str],
    index: BlockIndex,
    ledger_refs: LedgerRefIndex,
    cfg: Config,
) -> StageOutput:
    if stage == "exact_ref":
        return exact_ref_stage.find_matches(events, ledger_refs=ledger_refs)
    if stage == "fee_adjusted":
        return fee_adjusted_stage.find_matches(all_events, unmatched=unmatched, cfg=cfg)
    if stage == "date_shift":
        return date_shift_stage.find_matches(events, index=index, cfg=cfg)
    if stage == "many_to_one":
        return many_to_one_stage.find_matches(all_events, unmatched=unmatched, cfg=cfg)
    if stage == "fuzzy":
        return fuzzy_stage.find_matches(events, index=index, ledger_refs=ledger_refs, cfg=cfg)
    raise ValueError(f"stage not implemented in this cascade: {stage!r}")


def _extend(
    host: MatchResult,
    found: StageMatch,
    *,
    by_id: Mapping[str, TransactionEvent],
    cfg: Config,
) -> tuple[MatchResult, bool]:
    """Add a stage's newly decided rows to a group an earlier stage formed.

    The group gains an evidence entry rather than replacing the one it had, so
    the pack shows both proofs: the reference agreement that formed it and the
    arithmetic that attached the bank leg. Confidence takes the weaker of the
    two - a group is only as strong as the weakest link holding it together.
    """
    members = tuple(sorted({*host.event_ids, *found.decided}))
    sources: list[Source] = sorted({by_id[e].source for e in members})
    outcome = derive(
        ConfidenceInputs(
            stage=found.stage,
            base=found.base_confidence,
            fields_agreed=len(found.fields_agreed),
            fields_disagreed=len(found.fields_disagreed),
            amount_delta_paise=found.delta_paise,
            amount_basis_paise=found.amount_basis_paise,
            days_shift=found.date_shift_days,
            n_candidates=found.candidates_considered,
            distinct_sources=len(sources),
        )
    )
    confidence = min(host.confidence, outcome.derivation.result)
    evidence = MatchEvidence(
        stage=found.stage,
        fields_agreed=list(found.fields_agreed),
        fields_disagreed=list(found.fields_disagreed),
        arithmetic=found.arithmetic,
        delta_paise=found.delta_paise,
        date_shift_days=found.date_shift_days,
        candidates_considered=found.candidates_considered,
        grouped_by=found.grouped_by,
        confidence_derivation=outcome.derivation,
    )
    legs = [*host.evidence, evidence]
    # Stated, not inferred. ``derive`` already capped this leg by its own stage,
    # so the min above happens to give the right answer today - but the rule is
    # that the *group* is capped by its weakest leg, and a rule that only holds
    # because two other things line up is not being enforced.
    confidence = min(confidence, group_confidence_cap(legs))
    return host.model_copy(
        update={
            "event_ids": list(members),
            "sources_covered": sources,
            "confidence": confidence,
            "residual_paise": host.residual_paise + abs(found.delta_paise),
            "evidence": legs,
            "auto_closed": group_auto_closable(legs, confidence, cfg),
        }
    ), outcome.bonus_was_load_bearing


def _to_match_result(
    found: StageMatch,
    *,
    by_id: Mapping[str, TransactionEvent],
    cfg: Config,
    run_id: str,
    tenant_id: str,
    issue_id: Callable[[str], str],
    created_at: datetime,
) -> tuple[MatchResult, bool]:
    members = [by_id[event_id] for event_id in found.event_ids]
    sources: list[Source] = sorted({member.source for member in members})

    outcome = derive(
        ConfidenceInputs(
            stage=found.stage,
            base=found.base_confidence,
            fields_agreed=len(found.fields_agreed),
            fields_disagreed=len(found.fields_disagreed),
            amount_delta_paise=found.delta_paise,
            amount_basis_paise=found.amount_basis_paise,
            days_shift=found.date_shift_days,
            n_candidates=found.candidates_considered,
            distinct_sources=len(sources),
        )
    )
    confidence = outcome.derivation.result

    evidence = MatchEvidence(
        stage=found.stage,
        fields_agreed=list(found.fields_agreed),
        fields_disagreed=list(found.fields_disagreed),
        arithmetic=found.arithmetic,
        delta_paise=found.delta_paise,
        date_shift_days=found.date_shift_days,
        candidates_considered=found.candidates_considered,
        grouped_by=found.grouped_by,
        confidence_derivation=outcome.derivation,
    )

    return (
        MatchResult(
            match_id=issue_id("mch_"),
            run_id=run_id,
            tenant_id=tenant_id,
            group_key=found.group_key,
            event_ids=list(found.event_ids),
            sources_covered=sources,
            stage=found.stage,
            confidence=confidence,
            residual_paise=abs(found.delta_paise),
            evidence=[evidence],
            auto_closed=group_auto_closable([evidence], confidence, cfg),
            created_at=created_at,
        ),
        outcome.bonus_was_load_bearing,
    )


def group_auto_closable(legs: Sequence[MatchEvidence], confidence: Decimal, cfg: Config) -> bool:
    """Threshold, plus the per-stage rule applied to **every** leg.

    A group is only as provable as its weakest member, so this asks each evidence
    entry in turn rather than the stage that formed the group. Taking the host's
    stage instead would let a fuzzy leg ride into an ``exact_ref`` group and close
    at confidence 1.0 with an unproven row inside it - a false auto-resolution
    that the pairwise eval metric cannot see, because ground truth scores the
    group as correctly matched.

    The remaining half of the gate is the ``NEVER_AUTO`` category check, which
    needs the refusals and so is applied by :func:`run_cascade` once every stage
    and three-way resolution have reported.
    """
    if confidence < cfg.auto_threshold:
        return False
    return all(stage_may_auto_close(leg.stage, grouped_by=leg.grouped_by) for leg in legs)
