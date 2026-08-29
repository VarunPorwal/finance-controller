"""The accuracy gates, measured against the generated corpus.

Marked ``eval`` and excluded from the default run because it needs
``data/generated/``, which is gitignored. Regenerate with
``.\\scripts\\dev.ps1 generate -Seed 42 -N 500``.

``false_auto_resolutions == 0`` is the gate that matters - but it does not
measure what it is often credited with. Scoring is pairwise, and ground truth
files a duplicate voucher under the same ``gt_match_group`` as the settlement it
duplicates, so pairwise it is a correct pair while as a decision it is a wrong
auto-close. ``never_auto_inside_auto_closed`` is the counter that sees those, and
it is ratcheted below rather than left to drift.

Recall is still not pinned to a number. All five stages exist now, but stage 5
has almost nothing to score on this corpus, so a pinned recall figure would
mostly invite tuning the earlier stages to flatter it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fc.config import load_config
from fc.eval.report import DATA_DIR, evaluate, load_corpus
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.matching.stages import reference_is_truncated

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        not (DATA_DIR / "ground_truth.jsonl").exists(),
        reason="no generated corpus; run .\\scripts\\dev.ps1 generate",
    ),
]


@pytest.fixture(scope="module")
def report() -> object:
    return evaluate(load_corpus(Path(DATA_DIR)), load_config())


def test_stage_one_precision_is_perfect(report: object) -> None:
    """Stage 1 is the one stage allowed no false positives at all."""
    assert report.stage_precision["exact_ref"] == Decimal("1.0000")


def test_no_false_auto_resolutions(report: object) -> None:
    assert report.false_auto_resolutions == 0


def test_overall_precision_does_not_regress(report: object) -> None:
    """Stage 5 is the only thing in the cascade that can lower this."""
    assert report.precision == Decimal("1.0000")


def test_never_auto_labels_inside_auto_closed_matches_do_not_increase(report: object) -> None:
    """A ratchet, not a pass mark.

    Fourteen remain: four ``chargeback_unrecorded`` and ten
    ``ambiguous_multi_candidate``, neither of which matching evidence alone can
    prove - they need ``fc/exceptions/classify.py``. Three-way closed the three
    ``duplicate_ledger_entry`` cases, which it can prove. Lower this number as
    each prompt earns it; never raise it.
    """
    assert report.never_auto_inside_auto_closed <= 14


def test_every_refusal_carries_a_reason(report: object) -> None:
    """An exception with no stated reason is not an abstention, it is a shrug."""
    for refusal in report.cascade.refusals:
        assert refusal.reason.strip()
        assert refusal.event_ids


def test_no_auto_closed_match_contains_a_leg_that_may_not_auto_close(report: object) -> None:
    """The weakest-leg rule, over the real corpus.

    A group is only as provable as its weakest member. This is the permanent
    gate: it is invisible to the pairwise metric, because ground truth scores
    such a group as correctly matched.
    """
    from fc.models.match import stage_may_auto_close

    for match in report.cascade.matches:
        if not match.auto_closed:
            continue
        for leg in match.evidence:
            assert stage_may_auto_close(leg.stage, grouped_by=leg.grouped_by), (
                f"{match.match_id} auto-closed with a {leg.stage} leg"
            )


def test_the_wall_clock_backstop_never_fired(report: object) -> None:
    """If it did, the step budget is mis-calibrated and the run is no longer
    deterministic - which is a bug in the budget, not the clock doing its job."""
    tripped = report.cascade.diagnostics.get("many_to_one.subset_sum_wall_clock_tripped", 0)
    assert tripped == 0


def test_the_corpus_ingests_without_rejections(report: object) -> None:
    assert report.corpus.rejections == 0


def test_blocking_actually_reduces_the_comparison_count(report: object) -> None:
    blocking = report.cascade.blocking
    assert blocking.candidate_pairs < blocking.naive_cross_source
    assert blocking.reduction_ratio > 1


def test_no_event_lands_in_two_groups(report: object) -> None:
    assigned = [e for m in report.cascade.matches for e in m.event_ids]
    assert len(assigned) == len(set(assigned))


def test_every_match_carries_evidence_and_a_derivation(report: object) -> None:
    for match in report.cascade.matches:
        assert match.evidence
        for entry in match.evidence:
            assert entry.confidence_derivation is not None


def test_the_run_is_reproducible(report: object) -> None:
    again = evaluate(load_corpus(Path(DATA_DIR)), load_config())
    assert [m.model_dump_json() for m in report.cascade.matches] == [
        m.model_dump_json() for m in again.cascade.matches
    ]


def test_truncation_rederivation_agrees_with_the_ingest_parser(report: object) -> None:
    """The rail length table in ``fc/matching/stages`` duplicates ingest's.

    This is the drift guard: if a bank parser's expected length changes and the
    matching table does not, a truncated reference reaches stage 1.
    """
    parser = HdfcNarrationParser()
    checked = 0
    for event in report.corpus.events:
        if event.source != "bank" or event.raw_narration is None:
            continue
        parsed = parser.parse(event.raw_narration)
        if parsed.rail == "nach":
            continue  # never evaluated for truncation, by design
        assert reference_is_truncated(event) == parsed.truncated, event.raw_narration
        checked += 1
    assert checked > 0


def test_no_truncated_reference_was_used_by_stage_one(report: object) -> None:
    truncated = {
        e.event_id for e in report.corpus.events if e.source == "bank" and reference_is_truncated(e)
    }
    assert truncated, "the corpus should contain truncated narrations"
    for match in report.cascade.matches:
        if match.stage != "exact_ref":
            continue
        joined_on_reference = any(
            entry.stage == "exact_ref" and entry.fields_agreed for entry in match.evidence
        )
        if joined_on_reference:
            assert not (truncated & set(match.event_ids)) or any(
                entry.stage != "exact_ref" for entry in match.evidence
            )


def test_the_run_is_byte_identical_across_processes() -> None:
    """Determinism that an in-process re-run cannot demonstrate.

    ``test_the_run_is_reproducible`` runs twice inside one interpreter, so a
    dependence on set or dict iteration order - which varies with
    ``PYTHONHASHSEED`` between processes, not within one - would pass it every
    time. PRD §12.4 asks for "the same seed twice, byte-identical"; this is the
    version of that claim which can actually fail.
    """
    import os
    import subprocess
    import sys

    script = (
        "import json;"
        "from pathlib import Path;"
        "from datetime import datetime, timezone;"
        "from fc.config import load_config;"
        "from fc.eval.report import load_corpus, DATA_DIR;"
        "from fc.matching.cascade import run_cascade;"
        "from fc.models.ids import deterministic_factory;"
        "r=run_cascade(load_corpus(Path(DATA_DIR)).events, cfg=load_config(),"
        " run_id='r', tenant_id='t',"
        " issue_id=deterministic_factory(seed=7, epoch_ms=1_780_000_000_000),"
        " created_at=datetime(2026,8,29,tzinfo=timezone.utc));"
        "print(json.dumps({'m':[m.model_dump_json() for m in r.matches],"
        "'u':list(r.unmatched_event_ids),"
        "'x':[[f.category,list(f.event_ids),f.reason] for f in r.refusals],"
        "'d':dict(sorted(r.diagnostics.items()))}))"
    )

    def run(hash_seed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        done = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
        )
        return done.stdout

    assert run("0") == run("999")
