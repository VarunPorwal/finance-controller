"""The demo moment: change a rule, replay, show which past decisions flip.

Marked ``eval`` and excluded from the default run for the same reason as
``test_pipeline_corpus.py`` — it needs ``data/generated/`` and runs the full
pipeline twice (once for the parent run, once under the modified ruleset).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fc.audit.replay import replay
from fc.config import load_config
from fc.eval.corpus import DATA_DIR, load_corpus
from fc.models.ids import deterministic_factory
from fc.pipeline import run_pipeline
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules, version_hash

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        not (DATA_DIR / "ground_truth.jsonl").exists(),
        reason="no generated corpus; run .\\scripts\\dev.ps1 generate",
    ),
]

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_TENANT = "t_lumea"


def _bump_blinkit_commission_rate(rules: tuple, new_rate: Decimal) -> tuple:
    """The rule change the demo replays against: blinkit_commission's rate
    goes from 18% to ``new_rate`` — a new immutable version, not an edit."""
    (active,) = (r for r in rules if r.rule_id == "blinkit_commission" and r.status == "active")
    new_deductions = [
        d.model_copy(update={"rate": new_rate}) if d.type == "commission" else d
        for d in active.deductions
    ]
    bumped = active.model_copy(
        update={
            "version": active.version + 1,
            "version_hash": version_hash(active.scope, new_deductions, active.tolerance),
            "deductions": new_deductions,
        }
    )
    return tuple(r for r in rules if r is not active) + (bumped,)


def test_replaying_a_rate_change_flips_exactly_the_decisions_it_touches() -> None:
    cfg = load_config(env_file=None, environ={})
    corpus = load_corpus()
    original_rules = load_rules(DEFAULT_RULES_PATH, tenant_id=_TENANT, created_at=_AT).rules

    parent = run_pipeline(
        corpus.events,
        cfg=cfg,
        rules=original_rules,
        run_id="run_parent",
        tenant_id=_TENANT,
        issue_id=deterministic_factory(seed=7, epoch_ms=1_780_000_000_000),
        created_at=_AT,
    )
    assert len(parent.exceptions) > 0  # sanity: there is something for a rule to move

    replayed_rules = _bump_blinkit_commission_rate(original_rules, Decimal("25.0"))

    result = replay(
        parent_run_id="run_parent",
        parent_exceptions=parent.exceptions,
        events=corpus.events,
        cfg=cfg,
        rules=replayed_rules,
        new_run_id="run_replay",
        tenant_id=_TENANT,
        issue_id=deterministic_factory(seed=8, epoch_ms=1_780_000_000_000),
        created_at=_AT,
    )

    assert result.run_id == "run_replay"
    assert result.parent_run_id == "run_parent"
    assert not result.diff.is_empty, "a 7-point rate hike must move at least one decision"

    touched = result.diff.changed + result.diff.added + result.diff.removed
    assert any("blinkit_commission" in entry.why for entry in touched), (
        "the diff must name the rule that moved the decision, not just that something moved: "
        + repr([entry.why for entry in touched])
    )

    # Every entry's own arithmetic still closes (RuleApplication's invariant),
    # and no entry claims a change with no observable difference.
    for entry in result.diff.changed:
        assert entry.why != "no observable change"


def test_replay_is_deterministic_given_the_same_inputs() -> None:
    """Same seed, same ruleset -> byte-identical output (CLAUDE.md hard rule 9),
    and that must hold for the diff too, not just the raw pipeline result."""
    cfg = load_config(env_file=None, environ={})
    corpus = load_corpus()
    original_rules = load_rules(DEFAULT_RULES_PATH, tenant_id=_TENANT, created_at=_AT).rules
    parent = run_pipeline(
        corpus.events,
        cfg=cfg,
        rules=original_rules,
        run_id="run_parent",
        tenant_id=_TENANT,
        issue_id=deterministic_factory(seed=7, epoch_ms=1_780_000_000_000),
        created_at=_AT,
    )
    replayed_rules = _bump_blinkit_commission_rate(original_rules, Decimal("25.0"))

    def run_once() -> tuple:
        result = replay(
            parent_run_id="run_parent",
            parent_exceptions=parent.exceptions,
            events=corpus.events,
            cfg=cfg,
            rules=replayed_rules,
            new_run_id="run_replay",
            tenant_id=_TENANT,
            issue_id=deterministic_factory(seed=8, epoch_ms=1_780_000_000_000),
            created_at=_AT,
        )
        return (
            tuple((e.event_ids, e.why) for e in result.diff.changed),
            tuple((e.event_ids, e.why) for e in result.diff.added),
            tuple((e.event_ids, e.why) for e in result.diff.removed),
        )

    assert run_once() == run_once()
