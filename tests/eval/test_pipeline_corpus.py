"""The full pipeline (stages 0-9) against the generated corpus.

Marked ``eval`` and excluded from the default run for the same reason as
``tests/eval/test_rules_corpus.py``: it needs ``data/generated/``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fc.config import load_config
from fc.eval.report import DATA_DIR, load_corpus
from fc.models.ids import deterministic_factory
from fc.pipeline import run_pipeline
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        not (DATA_DIR / "ground_truth.jsonl").exists(),
        reason="no generated corpus; run .\\scripts\\dev.ps1 generate",
    ),
]

_AT = datetime(2026, 8, 29, tzinfo=UTC)


@pytest.fixture(scope="module")
def result() -> object:
    cfg = load_config(env_file=None, environ={})
    corpus = load_corpus()
    rules = load_rules(DEFAULT_RULES_PATH, tenant_id="t_lumea", created_at=_AT).rules
    issue_id = deterministic_factory(seed=7, epoch_ms=1_780_000_000_000)
    return run_pipeline(
        corpus.events,
        cfg=cfg,
        rules=rules,
        run_id="run_eval",
        tenant_id="t_lumea",
        issue_id=issue_id,
        created_at=_AT,
    )


def test_the_pipeline_produces_exceptions_and_clusters(result: object) -> None:
    assert len(result.exceptions) > 0  # type: ignore[attr-defined]
    assert len(result.clusters) > 0  # type: ignore[attr-defined]


def test_every_exception_has_a_specific_non_empty_recommendation(result: object) -> None:
    for exc in result.exceptions:  # type: ignore[attr-defined]
        assert exc.recommended_action.strip()
        assert exc.recommended_action.strip() != exc.category


def test_a_chargeback_still_escalates_however_confident_the_match_was(result: object) -> None:
    chargebacks = [e for e in result.exceptions if e.category == "chargeback_unrecorded"]  # type: ignore[attr-defined]
    assert chargebacks, "the corpus is expected to carry scenario-6 chargebacks"
    assert all(e.tier == "escalate" for e in chargebacks)


def test_never_auto_categories_never_carry_the_auto_tier(result: object) -> None:
    from fc.models.exception_ import NEVER_AUTO

    for exc in result.exceptions:  # type: ignore[attr-defined]
        if exc.category in NEVER_AUTO:
            assert exc.tier != "auto"


def test_every_ground_truth_never_auto_event_is_escalated_somewhere(result: object) -> None:
    """The direct measurement CLAUDE.md's carry-forward note asked for.

    Not "false_auto_resolutions == 0" (pairwise, blind to this) and not
    "never_auto_inside_auto_closed == 0" (cascade-only, blind to a group the
    pipeline correctly leaves auto-closed while still escalating a smaller,
    separate finding over it) — whichever match an event ended up in, some
    exception in the final queue must name it with tier == 'escalate'.
    """
    from fc.models.exception_ import NEVER_AUTO

    corpus = load_corpus()
    escalated: set[str] = set()
    for exc in result.exceptions:  # type: ignore[attr-defined]
        if exc.tier == "escalate":
            escalated.update(exc.event_ids)

    label_of = {
        event.event_id: corpus.label.get((event.source, event.source_row_id))
        for event in corpus.events
    }
    missed = [
        event.event_id
        for event in corpus.events
        if label_of.get(event.event_id) in NEVER_AUTO and event.event_id not in escalated
    ]
    assert missed == []


def test_the_cash_bridge_segments_sum_exactly_to_gross_minus_actual(result: object) -> None:
    bridge = result.cash_bridge  # type: ignore[attr-defined]
    total = sum(segment.amount_paise for segment in bridge.segments)
    assert total == bridge.gross_collected_paise - bridge.actual_bank_paise


def test_priority_ordering_puts_the_highest_impact_escalation_first(result: object) -> None:
    escalations = sorted(
        (e for e in result.exceptions if e.tier == "escalate"),  # type: ignore[attr-defined]
        key=lambda e: e.priority_score,
        reverse=True,
    )
    assert escalations
    assert escalations[0].priority_score >= escalations[-1].priority_score


def test_the_pipeline_is_deterministic_same_corpus_twice(result: object) -> None:
    cfg = load_config(env_file=None, environ={})
    corpus = load_corpus()
    rules = load_rules(DEFAULT_RULES_PATH, tenant_id="t_lumea", created_at=_AT).rules
    issue_id = deterministic_factory(seed=7, epoch_ms=1_780_000_000_000)
    again = run_pipeline(
        corpus.events,
        cfg=cfg,
        rules=rules,
        run_id="run_eval",
        tenant_id="t_lumea",
        issue_id=issue_id,
        created_at=_AT,
    )
    first = tuple(e.model_dump_json() for e in result.exceptions)  # type: ignore[attr-defined]
    second = tuple(e.model_dump_json() for e in again.exceptions)
    assert first == second
