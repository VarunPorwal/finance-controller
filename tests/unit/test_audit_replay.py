"""Pure tests for the replay diff: no pipeline run, no corpus, no database.

The corpus-backed demo — change ``blinkit_commission``'s rate, replay, show
exactly which decisions flip — lives in
``tests/eval/test_audit_replay_corpus.py``, since it needs the generated
corpus and runs the full pipeline twice. These tests exercise
``diff_exceptions`` directly against hand-built ``Exception_`` fixtures so the
comparison rules themselves are covered fast and always.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fc.audit.replay import diff_exceptions
from fc.models.exception_ import Exception_, RuleApplicationRef

_AT = datetime(2026, 8, 29, tzinfo=UTC)


def _exc(exception_id: str, event_ids: list[str], **overrides: object) -> Exception_:
    base: dict[str, object] = dict(
        exception_id=exception_id,
        run_id="run_x",
        tenant_id="t_test",
        event_ids=event_ids,
        category="amount_variance",
        amount_paise=100_000,
        residual_paise=32_400,
        confidence=Decimal("0.9000"),
        tier="monitor",
        priority_score=Decimal("50.0000"),
        recommended_action="review",
        signature="sig_a",
        created_at=_AT,
    )
    base.update(overrides)
    return Exception_(**base)  # type: ignore[arg-type]


def test_identical_sets_produce_an_empty_diff() -> None:
    before = [_exc("exc_1", ["evt_a", "evt_b"])]
    after = [_exc("exc_9", ["evt_a", "evt_b"])]  # new run, new exception_id, same decision
    diff = diff_exceptions(before, after)
    assert diff.is_empty
    assert diff.changed == ()
    assert diff.added == ()
    assert diff.removed == ()


def test_a_shrunk_residual_after_a_new_rule_is_reported_as_changed() -> None:
    before = [_exc("exc_1", ["evt_a"], residual_paise=324_000, tier="escalate")]
    after = [
        _exc(
            "exc_2",
            ["evt_a"],
            residual_paise=0,
            tier="auto",
            rules_applied=[
                RuleApplicationRef(
                    rule_id="blinkit_commission",
                    version=4,
                    version_hash="h4",
                    explained_paise=324_000,
                )
            ],
        )
    ]
    diff = diff_exceptions(before, after)
    assert len(diff.changed) == 1
    entry = diff.changed[0]
    assert entry.event_ids == ("evt_a",)
    assert entry.exception_id_before == "exc_1"
    assert entry.exception_id_after == "exc_2"
    assert entry.exception_id == "exc_2"
    assert "tier escalate -> auto" in entry.why
    assert "residual" in entry.why
    assert "now explained by blinkit_commission v4" in entry.why
    assert diff.added == () and diff.removed == ()


def test_only_lifecycle_fields_changing_is_not_reported() -> None:
    """status/resolved_by are workflow state a human applied to the parent run's
    row; a freshly recomputed exception always starts status='open', and that
    alone must not read as the ruleset having changed anything."""
    before = [_exc("exc_1", ["evt_a"], status="resolved", resolved_by="human")]
    after = [_exc("exc_2", ["evt_a"], status="open", resolved_by=None)]
    diff = diff_exceptions(before, after)
    assert diff.is_empty


def test_an_exception_missing_from_after_is_reported_as_removed() -> None:
    before = [_exc("exc_1", ["evt_a", "evt_b"])]
    after: list[Exception_] = []
    diff = diff_exceptions(before, after)
    assert len(diff.removed) == 1
    entry = diff.removed[0]
    assert entry.event_ids == ("evt_a", "evt_b")
    assert entry.exception_id_before == "exc_1"
    assert entry.exception_id_after is None
    assert entry.exception_id == "exc_1"
    assert entry.after is None
    assert "fully explained" in entry.why


def test_an_exception_only_in_after_is_reported_as_added() -> None:
    before: list[Exception_] = []
    after = [_exc("exc_2", ["evt_c"])]
    diff = diff_exceptions(before, after)
    assert len(diff.added) == 1
    entry = diff.added[0]
    assert entry.exception_id_before is None
    assert entry.exception_id_after == "exc_2"
    assert entry.exception_id == "exc_2"
    assert entry.before is None


def test_diff_ordering_is_deterministic_regardless_of_input_order() -> None:
    before = [_exc("exc_3", ["evt_c"]), _exc("exc_1", ["evt_a"]), _exc("exc_2", ["evt_b"])]
    after = [
        _exc("exc_3b", ["evt_c"], residual_paise=1),
        _exc("exc_1b", ["evt_a"], residual_paise=1),
        _exc("exc_2b", ["evt_b"], residual_paise=1),
    ]
    diff_a = diff_exceptions(before, after)
    diff_b = diff_exceptions(list(reversed(before)), list(reversed(after)))
    assert [e.event_ids for e in diff_a.changed] == [e.event_ids for e in diff_b.changed]
    assert [e.event_ids for e in diff_a.changed] == [("evt_a",), ("evt_b",), ("evt_c",)]


def test_multi_event_group_key_is_order_independent() -> None:
    """A many-to-one match's event_ids order must not matter for identity."""
    before = [_exc("exc_1", ["evt_b", "evt_a", "evt_c"])]
    after = [_exc("exc_2", ["evt_a", "evt_c", "evt_b"], residual_paise=0)]
    diff = diff_exceptions(before, after)
    assert len(diff.changed) == 1
    assert diff.changed[0].event_ids == ("evt_a", "evt_b", "evt_c")
