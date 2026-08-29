"""Accuracy suite — ``make eval`` / ``.\\scripts\\dev.ps1 eval``.

TODO(prompt-10): **this module is a partial and must be replaced, not extended.**
It was created early in Prompt 4 for one reason: ``dev.ps1 eval`` already ran
``python -m fc.eval.report`` and the module did not exist, so the target failed.
It reports enough to state a match rate and a first precision/recall number and
nothing more. Prompt 10 builds the real harness per PRD §12.4 — confusion
matrix, coverage-precision curve, per-category and per-stage breakdown, and the
generated list of every item we got wrong — alongside ``fc/eval/confusion.py``
and ``fc/eval/coverage_curve.py`` from §3.7. Start from §12.4, not from here.

Loads the generated corpus, ingests it through the real adapters, runs the
cascade, and scores the result against ``ground_truth.jsonl``. No database and
no network (PRD §3.7), so it runs anywhere the engine imports.

One number here is load-bearing beyond its size. ``false_auto_resolutions`` is
scored **pairwise**, and ground truth puts a duplicate voucher in the same
``gt_match_group`` as the settlement it duplicates - so pairwise it is a correct
pair, while as a *decision* it is a wrong auto-close. The metric is therefore
structurally blind to the ``NEVER_AUTO`` rule, and reading it as proof of that
rule is reading it as something it does not measure.
``never_auto_inside_auto_closed`` is the counter that does measure it.

Scoring is **pairwise**. A predicted group of n events asserts C(n,2) "these two
are the same money" claims; a claim is correct when both events carry the same
non-null ``gt_match_group``. Pairwise scoring is used because a group that is
right about six rows and wrong about a seventh should score as mostly right,
which set-equality scoring cannot express.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from itertools import combinations
from pathlib import Path

from fc.config import Config, load_config
from fc.ingest.bank_csv import parse_bank_csv
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.ingest.razorpay import parse_razorpay_recon
from fc.ingest.tally import parse_tally_csv
from fc.matching.cascade import CascadeResult, run_cascade
from fc.matching.stages.exact_ref import reference_is_truncated
from fc.models.exception_ import NEVER_AUTO
from fc.models.ids import deterministic_factory
from fc.models.transaction import TransactionEvent

__all__ = ["EvalReport", "evaluate", "load_corpus", "main"]

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "generated"

#: Fixed so the suite is a pure function of the corpus (hard rule 9).
_EPOCH_MS = 1_780_000_000_000
_INGESTED_AT = datetime(2026, 8, 29, tzinfo=UTC)
_OPENING_BALANCE_PAISE = 1_000_000_00
_RUN_ID = "run_eval"
_TENANT_ID = "t_lumea"


@dataclass(frozen=True)
class Corpus:
    events: tuple[TransactionEvent, ...]
    #: (source, source_row_id) -> gt_match_group
    truth: Mapping[tuple[str, str], str | None]
    #: (source, source_row_id) -> bucket
    bucket: Mapping[tuple[str, str], str]
    rejections: int
    #: (source, source_row_id) -> gt_label, for the NEVER_AUTO gate below.
    label: Mapping[tuple[str, str], str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalReport:
    corpus: Corpus
    cascade: CascadeResult
    predicted_pairs: int
    correct_pairs: int
    true_pairs: int
    precision: Decimal
    recall: Decimal
    stage_precision: Mapping[str, Decimal]
    match_rate: Decimal
    false_auto_resolutions: int
    #: Events ground truth labels NEVER_AUTO that are sitting inside an
    #: auto-closed match. ``false_auto_resolutions`` cannot see these.
    never_auto_inside_auto_closed: int
    refusals: Mapping[str, int]
    ledger_without_reference: int
    ledger_unmatched_with_reference: int
    truncated_references_withheld: int


def load_corpus(data_dir: Path = DATA_DIR) -> Corpus:
    """Ingest the generated files through the production adapters."""
    issue_id = deterministic_factory(seed=42, epoch_ms=_EPOCH_MS)

    razorpay = parse_razorpay_recon(
        json.loads((data_dir / "razorpay_recon.json").read_text(encoding="utf-8")),
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        issue_id=issue_id,
        ingested_at=_INGESTED_AT,
    )
    bank = parse_bank_csv(
        (data_dir / "bank_statement.csv").read_text(encoding="utf-8"),
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=_OPENING_BALANCE_PAISE,
        issue_id=issue_id,
        ingested_at=_INGESTED_AT,
    )
    ledger = parse_tally_csv(
        (data_dir / "tally_daybook.csv").read_text(encoding="utf-8"),
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        issue_id=issue_id,
        ingested_at=_INGESTED_AT,
    )

    truth: dict[tuple[str, str], str | None] = {}
    bucket: dict[tuple[str, str], str] = {}
    label: dict[tuple[str, str], str | None] = {}
    for line in (data_dir / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        key = (entry["source"], entry["key"])
        truth[key] = entry["gt_match_group"]
        bucket[key] = entry["bucket"]
        label[key] = entry.get("gt_label")

    events = (*razorpay.events, *bank.ingest.events, *ledger.events)
    rejections = len(razorpay.rejections) + len(bank.ingest.rejections) + len(ledger.rejections)
    return Corpus(events=events, truth=truth, bucket=bucket, rejections=rejections, label=label)


def evaluate(corpus: Corpus, cfg: Config) -> EvalReport:
    """Run the cascade and score it against ground truth."""
    issue_id = deterministic_factory(seed=7, epoch_ms=_EPOCH_MS)
    result = run_cascade(
        corpus.events,
        cfg=cfg,
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        issue_id=issue_id,
        created_at=_INGESTED_AT,
    )

    group_of = {
        event.event_id: corpus.truth.get((event.source, event.source_row_id))
        for event in corpus.events
    }

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

    true_pairs = _true_pair_count(corpus, group_of)
    matched_events = len(result.matched_event_ids)

    ledger_barren = set(result.ledger_refs.without_reference)
    unmatched = set(result.unmatched_event_ids)
    ledger_ids = {e.event_id for e in corpus.events if e.source == "ledger"}

    return EvalReport(
        corpus=corpus,
        cascade=result,
        predicted_pairs=predicted,
        correct_pairs=correct,
        true_pairs=true_pairs,
        precision=_ratio(correct, predicted),
        recall=_ratio(correct, true_pairs),
        stage_precision={
            stage: _ratio(hits, total) for stage, (hits, total) in sorted(by_stage.items())
        },
        match_rate=_ratio(matched_events, len(corpus.events)),
        false_auto_resolutions=_false_auto_resolutions(result, group_of),
        never_auto_inside_auto_closed=_never_auto_inside_auto_closed(corpus, result),
        refusals={category: count for category, count in sorted(result.refusal_counts.items())},
        ledger_without_reference=len(ledger_barren),
        ledger_unmatched_with_reference=len((unmatched & ledger_ids) - ledger_barren),
        truncated_references_withheld=sum(
            1 for event in corpus.events if reference_is_truncated(event)
        ),
    )


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


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal(0)
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))


def _pct(value: Decimal) -> str:
    return f"{value * 100:.2f}%"


def render(report: EvalReport) -> str:
    """The metrics table, printed by ``make eval``."""
    blocking = report.cascade.blocking
    lines: list[str] = []

    def row(label: str, value: object) -> None:
        lines.append(f"  {label:<44} {value}")

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
        suffix = f"  (pairwise precision {_pct(precision)})" if precision is not None else ""
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
        f"{report.never_auto_inside_auto_closed}   <- the gate above cannot see these",
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

    Determinism is re-run rather than assumed: the cascade runs a second time
    over the same corpus and the serialised matches, unmatched ids and refusals
    are compared. That is §12.4's "same seed twice" - an engine whose exceptions
    vary between runs cannot be audited, so it is a correctness gate, not a
    nicety. It is an in-process comparison; the cross-process version, which is
    what actually catches hash-order dependence, lives in ``tests/eval``.
    """
    again = evaluate(report.corpus, cfg)
    same = (
        [m.model_dump_json() for m in report.cascade.matches]
        == [m.model_dump_json() for m in again.cascade.matches]
        and report.cascade.unmatched_event_ids == again.cascade.unmatched_event_ids
        and [(r.category, r.event_ids, r.reason) for r in report.cascade.refusals]
        == [(r.category, r.event_ids, r.reason) for r in again.cascade.refusals]
    )
    return (
        GateResult(
            "false_auto_resolutions",
            report.false_auto_resolutions == 0,
            str(report.false_auto_resolutions),
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
