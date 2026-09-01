"""Accuracy suite — ``make eval`` / ``.\\scripts\\dev.ps1 eval``. PRD §12.4.

Loads the generated corpus, ingests it through the real adapters, runs the
full pipeline (cascade -> rules -> classification -> tiering -> clustering ->
cash bridge), and scores the result against ``ground_truth.jsonl``. No
database and no network (PRD §3.7), so it runs anywhere the engine imports.

One number here is load-bearing beyond its size. ``false_auto_resolutions`` is
scored **pairwise**, and ground truth puts a duplicate voucher in the same
``gt_match_group`` as the settlement it duplicates - so pairwise it is a correct
pair, while as a *decision* it is a wrong auto-close. The metric is therefore
structurally blind to the ``NEVER_AUTO`` rule, and reading it as proof of that
rule is reading it as something it does not measure.
``never_auto_inside_auto_closed`` is the counter that does measure it — but it
stops at the cascade, so it reads nonzero for a settlement the pipeline
correctly leaves auto-closed while still raising a smaller, separate,
correctly-tiered exception over the part of it that is genuinely unresolved
(``fc.exceptions.classify``'s order-attribution finding is the real example).
``never_auto_after_pipeline`` is the one that is actually gated: it runs the
full exception pipeline, not just the cascade, and asks the question that
matters — does *some* exception escalate this event, wherever it ended up.

Scoring is **pairwise**. A predicted group of n events asserts C(n,2) "these two
are the same money" claims; a claim is correct when both events carry the same
non-null ``gt_match_group``. Pairwise scoring is used because a group that is
right about six rows and wrong about a seventh should score as mostly right,
which set-equality scoring cannot express.

The §12.4 confusion matrix (:mod:`fc.eval.confusion`) is a different, stricter
cut of the same predictions: it scores only the auto-close *decision*
(``match.auto_closed``), not every predicted pair, so a correct match formed
at low confidence counts as an abstention there even though it counts as a hit
in ``precision``/``recall`` above. Both are printed; neither replaces the
other.
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

from fc.config import Config, load_config
from fc.eval.confusion import ConfusionMatrix, confusion_matrix, ratio
from fc.eval.corpus import DATA_DIR, EPOCH_MS, INGESTED_AT, RUN_ID, TENANT_ID, Corpus, load_corpus
from fc.eval.coverage_curve import CoveragePoint
from fc.eval.coverage_curve import sweep as sweep_coverage
from fc.matching.cascade import CascadeResult
from fc.matching.stages.exact_ref import reference_is_truncated
from fc.models.exception_ import NEVER_AUTO
from fc.models.ids import deterministic_factory
from fc.models.money import fmt_inr
from fc.models.rule import Rule
from fc.pipeline import PipelineResult, run_pipeline
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules

__all__ = [
    "DATA_DIR",
    "Corpus",
    "EvalReport",
    "GateResult",
    "check_gates",
    "evaluate",
    "load_corpus",
    "main",
    "render",
]

_EPOCH_MS = EPOCH_MS
_INGESTED_AT = INGESTED_AT
_RUN_ID = RUN_ID
_TENANT_ID = TENANT_ID

#: Chosen after reading the sweep (see the rationale printed alongside it):
#: coverage keeps climbing past 0.94 but so does the false-positive count on
#: this corpus, and 0.94 is the last point before that trade turns unfavourable.
#: Kept here rather than only in ``Config`` so the report can say *why* the
#: shipped point is the shipped point without re-deriving it from the curve.
SHIPPED_AUTO_THRESHOLD = Decimal("0.94")


@dataclass(frozen=True)
class CategoryStat:
    """Precision/recall of the *classification*, not the matching, for one
    :class:`~fc.models.exception_.ExceptionCategory`.

    ``raised`` is how many events sit inside an exception the pipeline filed
    under this category. ``gt_total`` is how many events ground truth labels
    with it. ``correct`` is how many of those labelled events ended up inside
    an exception the pipeline filed under the same category — the overlap
    that makes both a precision and a recall number meaningful. All three are
    event counts, not exception counts, so they stay comparable.
    """

    category: str
    raised: int
    gt_total: int
    correct: int

    @property
    def precision(self) -> Decimal:
        return ratio(self.correct, self.raised)

    @property
    def recall(self) -> Decimal:
        return ratio(self.correct, self.gt_total)


@dataclass(frozen=True)
class Failure:
    """One entry in the honest slide — PRD §12.4: "publish the categories we
    do badly on", §11.5: "the four things it got wrong or refused to touch,
    and why." Generated from real output, never hand-written.
    """

    kind: str
    event_ids: tuple[str, ...]
    amount_paise: int
    gt_label: str | None
    our_label: str
    why: str


@dataclass(frozen=True)
class EvalReport:
    corpus: Corpus
    cascade: CascadeResult
    pipeline: PipelineResult
    #: The ruleset this run was produced under. Carried so
    #: :func:`check_gates` can replay the run exactly; reloading the default
    #: rulebook there instead would silently compare two different rulesets
    #: whenever ``evaluate`` was given an override.
    rules: tuple[Rule, ...]
    predicted_pairs: int
    correct_pairs: int
    true_pairs: int
    precision: Decimal
    recall: Decimal
    stage_precision: Mapping[str, Decimal]
    #: Of every true pair in the corpus, what fraction did this stage help
    #: recover correctly — same numerator (`hits`) as ``stage_precision``,
    #: but divided by the global ``true_pairs`` rather than the stage's own
    #: predicted total, so it's comparable to the top-level ``recall`` above.
    #: Stages aren't mutually exclusive partitions of the true pairs (a
    #: multi-leg group counts under every stage that touched it, same as
    #: ``stage_precision``), so these do not sum to 100%.
    stage_recall: Mapping[str, Decimal]
    match_rate: Decimal
    false_auto_resolutions: int
    #: Events ground truth labels NEVER_AUTO that are sitting inside an
    #: auto-closed match. ``false_auto_resolutions`` cannot see these.
    never_auto_inside_auto_closed: int
    #: The metric that actually closes the gap: events ground truth labels
    #: NEVER_AUTO that the *finished exception pipeline* (not just the
    #: cascade) fails to escalate. Zero does not mean the cascade never
    #: auto-closes a group containing one of these — it means
    #: ``fc.exceptions.classify`` always raises a separate, correctly-tiered
    #: exception over it regardless, so a human sees it either way.
    never_auto_after_pipeline: int
    refusals: Mapping[str, int]
    ledger_without_reference: int
    ledger_unmatched_with_reference: int
    truncated_references_withheld: int
    #: PRD §12.4's confusion matrix, scored on the auto-close decision alone.
    confusion: ConfusionMatrix
    #: PRD §12.4's coverage-precision curve, 0.70 to 1.00 in 0.01 steps.
    coverage_curve: tuple[CoveragePoint, ...]
    #: Per-category precision/recall of the classification tree (§6.8).
    category_stats: tuple[CategoryStat, ...]
    #: The honest slide: every item scored wrong, amount-sorted, generated
    #: from this run's real output.
    failures: tuple[Failure, ...]
    #: §11.5's headline block.
    records_processed: int
    runtime_seconds: Decimal
    auto_matched_events: int
    rule_resolved_count: int
    exceptions_count: int
    cluster_count: int
    abstention_rate: Decimal
    human_queue_size: int
    workload_reduction: Decimal
    cash_at_risk_paise: int
    gst_input_credit_claimable_paise: int


def evaluate(corpus: Corpus, cfg: Config, *, rules: Sequence[Rule] | None = None) -> EvalReport:
    """Run the full pipeline and score it against ground truth.

    ``rules`` defaults to the shipped starter pack (``data/rules/deductions.yaml``)
    so existing callers that only ever passed ``(corpus, cfg)`` keep working
    unchanged; pass an explicit ruleset to score against a different one.
    """
    pipeline_rules = (
        rules
        if rules is not None
        else load_rules(DEFAULT_RULES_PATH, tenant_id=_TENANT_ID, created_at=_INGESTED_AT).rules
    )
    issue_id = deterministic_factory(seed=7, epoch_ms=_EPOCH_MS)

    started = time.monotonic()
    pipeline_result = run_pipeline(
        corpus.events,
        cfg=cfg,
        rules=pipeline_rules,
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        issue_id=issue_id,
        created_at=_INGESTED_AT,
    )
    runtime_seconds = Decimal(str(round(time.monotonic() - started, 3)))
    result = pipeline_result.cascade

    group_of = {
        event.event_id: corpus.truth.get((event.source, event.source_row_id))
        for event in corpus.events
    }
    event_source_key = {
        event.event_id: (event.source, event.source_row_id) for event in corpus.events
    }
    gt_label_of = {event_id: corpus.label.get(key) for event_id, key in event_source_key.items()}

    true_pairs = _true_pair_count(corpus, group_of)

    predicted = 0
    correct = 0
    by_stage: dict[str, list[int]] = {}
    for match in result.matches:
        hits = 0
        total = 0
        for left, right in combinations(sorted(match.event_ids), 2):
            total += 1
            group = group_of.get(left)
            if group is not None and group == group_of.get(right):
                hits += 1
        predicted += total
        correct += hits
        # Attributed to every stage that contributed a leg, not to
        # ``match.stage``. A group formed by stage 1 and extended by stage 4
        # reports ``stage="exact_ref"`` forever, so keying on it would file every
        # stage-4 and stage-5 error under stage 1 - and send anyone reading the
        # per-stage breakdown to the wrong module. A multi-leg group therefore
        # counts under each of its stages.
        for leg_stage in sorted({leg.stage for leg in match.evidence}):
            tally = by_stage.setdefault(leg_stage, [0, 0])
            tally[0] += hits
            tally[1] += total

    matched_events = len(result.matched_event_ids)

    ledger_barren = set(result.ledger_refs.without_reference)
    unmatched = set(result.unmatched_event_ids)
    ledger_ids = {e.event_id for e in corpus.events if e.source == "ledger"}

    event_ids = [event.event_id for event in corpus.events]
    confusion = confusion_matrix(event_ids, result.matches, group_of)
    coverage_curve = sweep_coverage(
        corpus.events,
        group_of,
        cfg=cfg,
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        issue_id=issue_id,
        created_at=_INGESTED_AT,
    )

    category_stats = _category_stats(pipeline_result, gt_label_of)
    amount_by_event = {event.event_id: abs(event.amount_paise) for event in corpus.events}
    failures = _failures(pipeline_result, group_of, gt_label_of, amount_by_event)

    needs_you = [exc for exc in pipeline_result.exceptions if exc.tier != "auto"]
    clustered_ids = {exc.cluster_id for exc in needs_you if exc.cluster_id is not None}
    human_queue_size = len(clustered_ids) + sum(1 for exc in needs_you if exc.cluster_id is None)
    total_records = len(corpus.events)
    rule_resolved_count = sum(
        1 for gap in pipeline_result.rule_gaps if gap.outcome.outcome == "fully_explained"
    )
    auto_matched_events = sum(len(match.event_ids) for match in result.matches if match.auto_closed)

    return EvalReport(
        corpus=corpus,
        rules=tuple(pipeline_rules),
        cascade=result,
        pipeline=pipeline_result,
        predicted_pairs=predicted,
        correct_pairs=correct,
        true_pairs=true_pairs,
        precision=_ratio(correct, predicted),
        recall=_ratio(correct, true_pairs),
        stage_precision={
            stage: _ratio(hits, total) for stage, (hits, total) in sorted(by_stage.items())
        },
        stage_recall={
            stage: _ratio(hits, true_pairs) for stage, (hits, _total) in sorted(by_stage.items())
        },
        match_rate=_ratio(matched_events, len(corpus.events)),
        false_auto_resolutions=_false_auto_resolutions(result, group_of),
        never_auto_inside_auto_closed=_never_auto_inside_auto_closed(corpus, result),
        never_auto_after_pipeline=_never_auto_after_pipeline_from(pipeline_result, gt_label_of),
        refusals={category: count for category, count in sorted(result.refusal_counts.items())},
        ledger_without_reference=len(ledger_barren),
        ledger_unmatched_with_reference=len((unmatched & ledger_ids) - ledger_barren),
        truncated_references_withheld=sum(
            1 for event in corpus.events if reference_is_truncated(event)
        ),
        confusion=confusion,
        coverage_curve=coverage_curve,
        category_stats=category_stats,
        failures=failures,
        records_processed=total_records,
        runtime_seconds=runtime_seconds,
        auto_matched_events=auto_matched_events,
        rule_resolved_count=rule_resolved_count,
        exceptions_count=len(pipeline_result.exceptions),
        cluster_count=len(pipeline_result.clusters),
        abstention_rate=_ratio(len(result.unmatched_event_ids), total_records),
        human_queue_size=human_queue_size,
        workload_reduction=_ratio(total_records - human_queue_size, total_records),
        cash_at_risk_paise=pipeline_result.cash_bridge.cash_at_risk_paise,
        gst_input_credit_claimable_paise=pipeline_result.cash_bridge.gst_input_credit_claimable_paise,
    )


def _category_stats(
    pipeline_result: PipelineResult, gt_label_of: Mapping[str, str | None]
) -> tuple[CategoryStat, ...]:
    """Event-level precision/recall of the classification tree.

    Counted in events throughout - ``raised`` is every event sitting inside a
    category-c exception, not the number of exceptions - so it stays
    comparable to ``correct`` and ``gt_total``, which are also event counts.
    An exception naming several events (e.g. ``ambiguous_multi_candidate``)
    would otherwise let ``correct`` exceed an exception-counted ``raised``.
    """
    raised_by_category: Counter[str] = Counter()
    for exc in pipeline_result.exceptions:
        raised_by_category[exc.category] += len(exc.event_ids)
    gt_total_by_category: Counter[str] = Counter(
        label for label in gt_label_of.values() if label is not None
    )
    correct_by_category: dict[str, set[str]] = {}
    for exc in pipeline_result.exceptions:
        for event_id in exc.event_ids:
            if gt_label_of.get(event_id) == exc.category:
                correct_by_category.setdefault(exc.category, set()).add(event_id)

    categories = sorted(set(raised_by_category) | set(gt_total_by_category))
    return tuple(
        CategoryStat(
            category=category,
            raised=raised_by_category.get(category, 0),
            gt_total=gt_total_by_category.get(category, 0),
            correct=len(correct_by_category.get(category, set())),
        )
        for category in categories
    )


def _failures(
    pipeline_result: PipelineResult,
    group_of: Mapping[str, str | None],
    gt_label_of: Mapping[str, str | None],
    amount_by_event: Mapping[str, int],
) -> tuple[Failure, ...]:
    failures: list[Failure] = []

    for match in pipeline_result.cascade.matches:
        if not match.auto_closed:
            continue
        bad_pairs = False
        groups_seen: set[str] = set()
        for left, right in combinations(sorted(match.event_ids), 2):
            left_group, right_group = group_of.get(left), group_of.get(right)
            if left_group is None or left_group != right_group:
                bad_pairs = True
            for group in (left_group, right_group):
                if group is not None:
                    groups_seen.add(group)
        if bad_pairs:
            failures.append(
                Failure(
                    kind="false_auto_resolution",
                    event_ids=tuple(sorted(match.event_ids)),
                    amount_paise=sum(amount_by_event.get(e, 0) for e in match.event_ids),
                    gt_label=", ".join(sorted(groups_seen)) or None,
                    our_label="auto-closed as one group",
                    why="ground truth does not agree these events are one settlement",
                )
            )

    for exc in pipeline_result.exceptions:
        labels = {gt_label_of.get(event_id) for event_id in exc.event_ids}
        labels.discard(None)
        if labels and exc.category not in labels:
            failures.append(
                Failure(
                    kind="misclassified",
                    event_ids=tuple(exc.event_ids),
                    amount_paise=exc.amount_paise,
                    gt_label=", ".join(sorted(str(label) for label in labels)),
                    our_label=exc.category,
                    why=(
                        "the classification tree filed this under a different "
                        "category than ground truth"
                    ),
                )
            )

    escalated_events: set[str] = set()
    for exc in pipeline_result.exceptions:
        if exc.tier == "escalate":
            escalated_events.update(exc.event_ids)
    for event_id, label in gt_label_of.items():
        if label in NEVER_AUTO and event_id not in escalated_events:
            failures.append(
                Failure(
                    kind="never_auto_not_escalated",
                    event_ids=(event_id,),
                    amount_paise=0,
                    gt_label=label,
                    our_label="not escalated",
                    why=f"ground truth labels this {label!r}, which must always reach a human",
                )
            )

    failures.sort(key=lambda f: f.amount_paise, reverse=True)
    return tuple(failures)


def _true_pair_count(corpus: Corpus, group_of: Mapping[str, str | None]) -> int:
    """Pairs ground truth says belong together, over events the cascade saw."""
    sizes: dict[str, int] = {}
    for event in corpus.events:
        group = group_of.get(event.event_id)
        if group is None:
            continue
        sizes[group] = sizes.get(group, 0) + 1
    return sum(n * (n - 1) // 2 for n in sizes.values())


def _false_auto_resolutions(result: CascadeResult, group_of: Mapping[str, str | None]) -> int:
    """Auto-closed matches containing a pair ground truth says is not one group.

    The gate that must read zero. A single one of these is worse than any
    amount of missed recall.
    """
    offenders = 0
    for match in result.matches:
        if not match.auto_closed:
            continue
        for left, right in combinations(sorted(match.event_ids), 2):
            left_group, right_group = group_of.get(left), group_of.get(right)
            if left_group is None or left_group != right_group:
                offenders += 1
                break
    return offenders


def _never_auto_inside_auto_closed(corpus: Corpus, result: CascadeResult) -> int:
    """Events labelled NEVER_AUTO that an auto-closed match is holding.

    The gate ``false_auto_resolutions`` is credited with but does not measure.
    Pairwise scoring sees a duplicate voucher as a correct pair, because ground
    truth files it under the settlement it duplicates; only the category rule
    calls it a wrong decision.
    """
    label_of = {
        event.event_id: corpus.label.get((event.source, event.source_row_id))
        for event in corpus.events
    }
    offenders = 0
    for match in result.matches:
        if not match.auto_closed:
            continue
        offenders += sum(1 for e in match.event_ids if label_of.get(e) in NEVER_AUTO)
    return offenders


def _never_auto_after_pipeline_from(
    pipeline_result: PipelineResult, gt_label_of: Mapping[str, str | None]
) -> int:
    """The direct measurement: does the *finished pipeline* escalate every
    NEVER_AUTO-labelled event, not just avoid closing it silently?

    ``never_auto_inside_auto_closed`` counts a real gap but does not name the
    fix, and reads nonzero forever for a settlement whose cash is correctly
    auto-closed while a smaller, separate finding (order-level attribution)
    is what's actually unresolved (CLAUDE.md carry-forward). This metric asks
    the question that actually matters: whichever match an event ends up in,
    does some exception in the human queue name it with ``tier='escalate'``?

    Takes the already-computed ``pipeline_result`` rather than re-running the
    pipeline a second time - ``evaluate`` now runs it exactly once.
    """
    escalated: set[str] = set()
    for exc in pipeline_result.exceptions:
        if exc.tier == "escalate":
            escalated.update(exc.event_ids)
    return sum(
        1
        for event_id, label in gt_label_of.items()
        if label in NEVER_AUTO and event_id not in escalated
    )


def _ratio(numerator: int, denominator: int) -> Decimal:
    return ratio(numerator, denominator)


def _pct(value: Decimal) -> str:
    return f"{value * 100:.2f}%"


def render(report: EvalReport) -> str:
    """The metrics table, printed by ``make eval``."""
    blocking = report.cascade.blocking
    lines: list[str] = []

    def row(label: str, value: object) -> None:
        lines.append(f"  {label:<44} {value}")

    lines.append("")
    lines.append("EXPECTED OUTCOMES (PRD 11.5)")
    row("records processed", report.records_processed)
    row("runtime", f"{report.runtime_seconds}s")
    auto_share = _pct(_ratio(report.auto_matched_events, report.records_processed))
    rule_share = _pct(_ratio(report.rule_resolved_count, report.records_processed))
    exc_share = _pct(_ratio(report.exceptions_count, report.records_processed))
    row("auto-matched", f"{report.auto_matched_events}   ({auto_share})")
    row("rule-resolved", f"{report.rule_resolved_count}   ({rule_share})")
    row("exceptions surfaced", f"{report.exceptions_count}   ({exc_share})")
    row("  -> collapsed into", f"{report.cluster_count} root causes")
    row("precision on auto-close", _pct(report.confusion.precision_auto))
    row("false_auto_resolutions", report.false_auto_resolutions)
    row("recall vs ground truth", _pct(report.recall))
    row("abstention rate", f"{_pct(report.abstention_rate)}   (by design)")
    row("human queue", f"{report.human_queue_size} items, not {report.records_processed}")
    row("workload reduction", _pct(report.workload_reduction))
    row("cash at risk", fmt_inr(report.cash_at_risk_paise))
    row("GST input claimable", fmt_inr(report.gst_input_credit_claimable_paise))

    lines.append("")
    lines.append("MATCHING CASCADE - all five stages (PRD 6.3) + three-way (6.4)")
    lines.append("")
    lines.append("Corpus")
    row("events ingested", len(report.corpus.events))
    row("ingest rejections", report.corpus.rejections)

    lines.append("")
    lines.append("Blocking (PRD 6.2)")
    row("naive comparisons (all pairs)", f"{blocking.naive_comparisons:,}")
    row("naive comparisons (cross-source)", f"{blocking.naive_cross_source:,}")
    row("candidate pairs after blocking", f"{blocking.candidate_pairs:,}")
    row("reduction", f"{blocking.reduction_ratio}x")
    row("blocks / largest block", f"{blocking.blocks:,} / {blocking.largest_block}")
    row("oversize blocks sub-bucketed", blocking.oversize_blocks)
    row(
        "shards produced / still oversize",
        f"{blocking.sub_bucketed_keys} / {blocking.oversize_after_shard}",
    )

    lines.append("")
    lines.append("Cascade")
    for stage, count in report.cascade.stage_counts.items():
        precision = report.stage_precision.get(stage)
        recall = report.stage_recall.get(stage)
        suffix = (
            f"  (pairwise precision {_pct(precision)}, recall {_pct(recall)})"
            if precision is not None and recall is not None
            else ""
        )
        row(f"stage {stage}", f"{count} matches{suffix}")
    for stage, abstained in report.cascade.abstentions.items():
        if abstained:
            row(f"stage {stage} abstained on", f"{len(abstained)} events")
    row("events matched", f"{len(report.cascade.matched_event_ids)} of {len(report.corpus.events)}")
    row("match rate", _pct(report.match_rate))

    lines.append("")
    lines.append("Accuracy vs gt_match_group (pairwise)")
    row("predicted pairs", f"{report.predicted_pairs:,}")
    row("correct pairs", f"{report.correct_pairs:,}")
    row("true pairs in corpus", f"{report.true_pairs:,}")
    row("precision", _pct(report.precision))
    row("recall", _pct(report.recall))
    row("false_auto_resolutions", report.false_auto_resolutions)
    row(
        "never_auto events inside auto-closed matches",
        f"{report.never_auto_inside_auto_closed}   <- false_auto_resolutions cannot see these",
    )
    row(
        "never_auto events NOT escalated by the finished pipeline",
        f"{report.never_auto_after_pipeline}   <- the gate below measures this one directly",
    )

    lines.append("")
    lines.append("Confusion matrix (PRD 12.4) - the auto-close decision only")
    c = report.confusion
    row("TP  (auto-closed, GT agrees)", c.tp)
    row("FP  (auto-closed, GT disagrees)  <- dangerous cell", c.fp)
    row("FN  (abstained, GT says match)", c.fn)
    row("TN  (abstained, GT says no match)", c.tn)
    row("precision_auto", _pct(c.precision_auto))
    row("recall", _pct(c.recall))
    row("f1", _pct(c.f1))

    lines.append("")
    lines.append(
        f"Coverage-precision curve (0.70-1.00, step 0.01)  <- shipped: {SHIPPED_AUTO_THRESHOLD}"
    )
    header = f"  {'threshold':>9}  {'coverage':>8}  {'precision':>9}  {'FP':>5}  {'abstain':>7}"
    lines.append(header)
    for point in report.coverage_curve:
        marker = "  <- shipped" if point.threshold == SHIPPED_AUTO_THRESHOLD else ""
        lines.append(
            f"  {point.threshold:>9}  {point.coverage * 100:>7.2f}%  "
            f"{point.precision * 100:>8.2f}%  {point.false_positives:>5}  "
            f"{point.abstentions:>7}{marker}"
        )
    lines.append("  rationale: coverage keeps climbing past the shipped point, but so does the")
    lines.append("  false-positive count on this corpus - 0.94 is the last point before that")
    lines.append("  trade turns unfavourable (PRD 12.4).")

    lines.append("")
    lines.append("Per-category breakdown (classification tree, PRD 6.8)")
    for stat in report.category_stats:
        row(
            stat.category,
            f"raised {stat.raised:>3}  gt {stat.gt_total:>3}  correct {stat.correct:>3}  "
            f"precision {_pct(stat.precision)}  recall {_pct(stat.recall)}",
        )

    lines.append("")
    lines.append("Refusals (categorised abstentions, PRD 6.8 vocabulary)")
    if report.refusals:
        for category, count in report.refusals.items():
            row(category, count)
    else:
        row("none", 0)

    lines.append("")
    lines.append("Guards")
    row("bank refs withheld as truncated", report.truncated_references_withheld)
    row("ledger rows with no extractable ref", report.ledger_without_reference)
    row("ledger rows with a ref, still unmatched", report.ledger_unmatched_with_reference)
    row("matches moved by source_coverage_bonus", report.cascade.three_way_bonus_applied)

    lines.append("")
    lines.append("Diagnostics")
    for key, value in sorted(report.cascade.diagnostics.items()):
        row(key, value)

    lines.append("")
    lines.append(f"WHAT WE GOT WRONG - {len(report.failures)} item(s), generated from this run")
    if not report.failures:
        row("none", "every scored item agreed with ground truth")
    for f in report.failures:
        lines.append(
            f"  [{f.kind}] {', '.join(f.event_ids[:3])}"
            f"{' ...' if len(f.event_ids) > 3 else ''}  ({f.amount_paise / 100:,.2f})"
        )
        lines.append(f"      gt={f.gt_label!r}  ours={f.our_label!r}  why: {f.why}")
    lines.append("")
    return "\n".join(lines)


#: PRD §12.5. ``false_auto_resolutions`` blocks merge; recall and determinism
#: block release. All three are checked here, because a gate that runs only when
#: somebody remembers to type a command has never blocked anything.
RECALL_GATE = Decimal("0.90")


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    actual: str
    threshold: str


def check_gates(report: EvalReport, cfg: Config) -> tuple[GateResult, ...]:
    """Evaluate the §12.5 gates this suite can measure.

    Determinism is re-run rather than assumed: the whole pipeline runs a second
    time over the same corpus, seed and ruleset, and the resulting matches,
    unmatched ids and refusals are compared. That is §12.4's "same seed twice"
    — an engine whose exceptions vary between runs cannot be audited, so this
    is a correctness gate, not a nicety.

    It re-runs :func:`fc.pipeline.run_pipeline`, not :func:`run_cascade`
    directly, and the difference is the whole point. The pipeline does not
    hand the cascade the raw corpus: it first drops ledger rows whose voucher
    never moves the bank account, so the cascade sees 816 of the corpus's 1,575
    events. A gate that re-ran the cascade over all 1,575 was comparing a
    different input against a different input — 99 matches against the
    pipeline's 95 — and reported MISMATCH on every run since ledger scoping
    was introduced, whether or not anything was actually non-deterministic.
    Replaying the entrypoint the pipeline itself uses is what makes the answer
    mean something, and leaves no filtering rule for the gate to fall behind.
    """
    replay = run_pipeline(
        report.corpus.events,
        cfg=cfg,
        rules=report.rules,
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        issue_id=deterministic_factory(seed=7, epoch_ms=_EPOCH_MS),
        created_at=_INGESTED_AT,
    ).cascade
    same = (
        [m.model_dump_json() for m in report.cascade.matches]
        == [m.model_dump_json() for m in replay.matches]
        and report.cascade.unmatched_event_ids == replay.unmatched_event_ids
        and [(r.category, r.event_ids, r.reason) for r in report.cascade.refusals]
        == [(r.category, r.event_ids, r.reason) for r in replay.refusals]
    )
    return (
        GateResult(
            "false_auto_resolutions",
            report.false_auto_resolutions == 0,
            str(report.false_auto_resolutions),
            "0",
        ),
        GateResult(
            "never_auto_after_pipeline",
            report.never_auto_after_pipeline == 0,
            str(report.never_auto_after_pipeline),
            "0",
        ),
        GateResult(
            "recall",
            report.recall >= RECALL_GATE,
            _pct(report.recall),
            f">= {_pct(RECALL_GATE)}",
        ),
        GateResult(
            "determinism (same seed, same output)",
            same,
            "identical" if same else "MISMATCH between two runs",
            "identical",
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    cfg = load_config()
    if not DATA_DIR.exists():
        print(f"no corpus at {DATA_DIR}; run the generate target first", file=sys.stderr)
        return 1

    report = evaluate(load_corpus(), cfg)
    print(render(report))

    gates = check_gates(report, cfg)
    print("Quality gates (PRD 12.5)")
    for gate in gates:
        mark = "PASS" if gate.passed else "FAIL"
        print(f"  [{mark}] {gate.name:<38} {gate.actual}  (needs {gate.threshold})")
    print("")

    failed = [gate for gate in gates if not gate.passed]
    for gate in failed:
        print(
            f"GATE FAILED: {gate.name} = {gate.actual}, needs {gate.threshold}",
            file=sys.stderr,
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
