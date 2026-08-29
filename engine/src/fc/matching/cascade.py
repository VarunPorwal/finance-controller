"""The matching cascade — PRD §6.3.

Stages run in order, cheapest and most certain first, and a row matched at one
stage never reaches the next. That ordering is the design, not an optimisation:
collapsing the stages into one scoring function would lose the reason a match
was made, which is the only thing that makes the evidence pack meaningful.

Stages 4 (``many_to_one``) and 5 (``fuzzy``) are not built yet. They append to
:data:`CASCADE_ORDER` without restructuring anything here, so the match rate
this module reports today is **partial by construction** and should be read as
such.

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
from fc.matching.blocking import BlockIndex, BlockingStats, build_blocks
from fc.matching.confidence import ConfidenceInputs, cap_for_stage, derive
from fc.matching.ledger_refs import LedgerRefIndex, index_ledger_refs
from fc.matching.stages import AUTO_CLOSABLE_STAGES, StageMatch, StageOutput
from fc.matching.stages import date_shift as date_shift_stage
from fc.matching.stages import exact_ref as exact_ref_stage
from fc.matching.stages import fee_adjusted as fee_adjusted_stage
from fc.models.match import MatchEvidence, MatchResult, MatchStage
from fc.models.transaction import Source, TransactionEvent

__all__ = ["CASCADE_ORDER", "CascadeResult", "run_cascade"]

#: The §6.3 order. ``many_to_one`` and ``fuzzy`` slot in after ``date_shift``.
CASCADE_ORDER: tuple[MatchStage, ...] = ("exact_ref", "fee_adjusted", "date_shift")


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
    #: How many matches the §6.6 three-way bonus actually moved. Zero means the
    #: bonus is decoration and should be removed rather than left in.
    three_way_bonus_applied: int = 0
    matched_event_ids: frozenset[str] = field(default_factory=frozenset)


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
    bonus_applied = 0

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

            context = [e for e in found.event_ids if e not in decided]
            hosts = {owner[e] for e in context if e in owner}
            if len(hosts) > 1:
                # The stage reconciled against rows that already belong to two
                # different groups. Merging them on this evidence would assert
                # something no stage proved, so decline.
                continue

            if hosts:
                index_of_host = hosts.pop()
                results[index_of_host] = _extend(
                    results[index_of_host], found, by_id=by_id, cfg=cfg
                )
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

            claimed.update(decided)
            accepted += 1

        stage_counts[stage] = accepted
        abstentions[stage] = output.abstained
        for key, value in output.diagnostics.items():
            diagnostics[f"{stage}.{key}"] = value

    # The cascade's central invariant: one event, at most one group.
    assigned = [event_id for result in results for event_id in result.event_ids]
    assert len(assigned) == len(set(assigned)), "an event landed in two match groups"

    diagnostics["ledger_rows_without_reference"] = len(ledger_refs.without_reference)

    return CascadeResult(
        matches=tuple(results),
        unmatched_event_ids=tuple(sorted(e.event_id for e in events if e.event_id not in claimed)),
        blocking=index.stats,
        ledger_refs=ledger_refs,
        stage_counts=stage_counts,
        abstentions=abstentions,
        diagnostics=diagnostics,
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
    raise ValueError(f"stage not implemented in this cascade: {stage!r}")


def _extend(
    host: MatchResult,
    found: StageMatch,
    *,
    by_id: Mapping[str, TransactionEvent],
    cfg: Config,
) -> MatchResult:
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
    confidence = min(host.confidence, cap_for_stage(found.stage, outcome.derivation.result))
    evidence = MatchEvidence(
        stage=found.stage,
        fields_agreed=list(found.fields_agreed),
        fields_disagreed=list(found.fields_disagreed),
        arithmetic=found.arithmetic,
        delta_paise=found.delta_paise,
        date_shift_days=found.date_shift_days,
        candidates_considered=found.candidates_considered,
        confidence_derivation=outcome.derivation,
    )
    return host.model_copy(
        update={
            "event_ids": list(members),
            "sources_covered": sources,
            "confidence": confidence,
            "residual_paise": host.residual_paise + abs(found.delta_paise),
            "evidence": [*host.evidence, evidence],
            "auto_closed": _auto_closable(host.stage, confidence, cfg),
        }
    )


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
    confidence = cap_for_stage(found.stage, outcome.derivation.result)

    evidence = MatchEvidence(
        stage=found.stage,
        fields_agreed=list(found.fields_agreed),
        fields_disagreed=list(found.fields_disagreed),
        arithmetic=found.arithmetic,
        delta_paise=found.delta_paise,
        date_shift_days=found.date_shift_days,
        candidates_considered=found.candidates_considered,
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
            auto_closed=_auto_closable(found.stage, confidence, cfg),
            created_at=created_at,
        ),
        outcome.bonus_was_load_bearing,
    )


def _auto_closable(stage: MatchStage, confidence: Decimal, cfg: Config) -> bool:
    """Threshold plus the per-stage rule.

    This is NOT the whole gate. The ``NEVER_AUTO`` category check lives in
    ``fc/exceptions/tier.py``, which does not exist yet, so a confident match
    covering a chargeback would currently be marked auto-closable here. See the
    closing note in the prompt-4 plan.
    """
    return stage in AUTO_CLOSABLE_STAGES and confidence >= cfg.auto_threshold
