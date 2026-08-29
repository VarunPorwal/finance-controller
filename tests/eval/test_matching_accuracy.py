"""The accuracy gates, measured against the generated corpus.

Marked ``eval`` and excluded from the default run because it needs
``data/generated/``, which is gitignored. Regenerate with
``.\\scripts\\dev.ps1 generate -Seed 42 -N 500``.

``false_auto_resolutions == 0`` is the gate that matters. Recall is deliberately
not asserted: stages 4 and 5 are not built, so the number here is a floor and
pinning it would only invite tuning stages 1-3 to flatter it.
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
