"""PRD §12.4's additions to the eval harness: the confusion matrix, the
coverage-precision curve, the per-category breakdown, and the honest-slide
failures list. ``test_matching_accuracy.py`` already covers the pairwise
precision/recall this module reuses; this file is about the new cuts of the
same data, not a re-test of the cascade itself.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fc.config import load_config
from fc.eval.report import DATA_DIR, evaluate, load_corpus

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


def test_confusion_matrix_partitions_every_pair(report: object) -> None:
    """TP + FP + FN + TN must equal C(n, 2) exactly - the four cells are a
    partition of every pair in the corpus, not an approximation."""
    n = len(report.corpus.events)
    c = report.confusion
    assert c.tp + c.fp + c.fn + c.tn == n * (n - 1) // 2


def test_confusion_fp_matches_the_gated_metric_in_spirit(report: object) -> None:
    """The confusion matrix's FP (a pair count) is zero exactly when the
    gated ``false_auto_resolutions`` (a match count) is zero - both are
    reading the same underlying fact (does an auto-closed match disagree
    with ground truth), just at different granularity."""
    if report.false_auto_resolutions == 0:
        assert report.confusion.fp == 0
    else:
        assert report.confusion.fp > 0


def test_confusion_tp_never_exceeds_true_pairs(report: object) -> None:
    """TP only counts auto-closed pairs, a subset of every correct pair the
    cascade found - it cannot exceed the total the corpus actually contains."""
    assert report.confusion.tp <= report.true_pairs


def test_coverage_curve_covers_the_full_sweep(report: object) -> None:
    thresholds = [point.threshold for point in report.coverage_curve]
    assert thresholds[0] == Decimal("0.70")
    assert thresholds[-1] == Decimal("1.00")
    assert len(thresholds) == 31
    assert thresholds == sorted(thresholds)


def test_coverage_curve_is_monotonic_non_increasing(report: object) -> None:
    """Raising the bar for auto-close can only shrink (or hold) the
    auto-closed set - never grow it."""
    coverages = [point.coverage for point in report.coverage_curve]
    for index in range(len(coverages) - 1):
        assert coverages[index + 1] <= coverages[index]


def test_coverage_curve_false_positives_never_exceed_the_lowest_threshold(
    report: object,
) -> None:
    """The most permissive threshold (0.70) auto-closes the largest set, so
    it is the only point that can hold the sweep's maximum FP count."""
    fps = [point.false_positives for point in report.coverage_curve]
    assert max(fps) == fps[0]


def test_per_category_correct_never_exceeds_raised_or_ground_truth(report: object) -> None:
    for stat in report.category_stats:
        assert stat.correct <= stat.raised
        assert stat.correct <= stat.gt_total


def test_failures_list_is_sorted_by_amount_descending(report: object) -> None:
    amounts = [f.amount_paise for f in report.failures]
    assert amounts == sorted(amounts, reverse=True)


def test_every_failure_carries_a_reason(report: object) -> None:
    for f in report.failures:
        assert f.why.strip()
        assert f.event_ids


def test_workload_reduction_and_queue_size_agree_with_records_processed(report: object) -> None:
    assert 0 <= report.human_queue_size <= report.records_processed
    expected = Decimal(report.records_processed - report.human_queue_size) / Decimal(
        report.records_processed
    )
    assert report.workload_reduction == expected.quantize(Decimal("0.0001"))
