"""The deterministic command validator — PRD §8.4, §8.5, §9.2.

One test per push-back rule, plus the refusals for cut and unbuilt verbs. All
seven rules are branches in a pure function, so none of this needs a database
or a model — which is the reason the validator was put there.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from fc.agent.permissions import PERMISSIONS, can, roles_permitting
from fc.agent.validator import (
    CommandContext,
    ExceptionFacts,
    Preview,
    RefCandidate,
    validate,
)
from fc.config import Config
from fc.models.command import CommandPayload, ParsedCommand

CFG = Config()
NOW = datetime(2026, 8, 29, tzinfo=UTC)


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: CommandPayload


def _command(instruction: str = "do the thing", **payload: Any) -> ParsedCommand:
    return ParsedCommand(
        command_id="cmd_1",
        instruction_text=instruction,
        payload=_Envelope.model_validate({"payload": payload}).payload,
        confidence=Decimal("0.9"),
        parsed_at=NOW,
    )


def _facts(**overrides: Any) -> ExceptionFacts:
    base: dict[str, Any] = {
        "exception_id": "exc_1",
        "amount_paise": 100_000,
        "residual_paise": 100_000,
        "category": "amount_variance",
        "status": "open",
        "tier": "monitor",
        "state_fingerprint": "v1",
    }
    base.update(overrides)
    return ExceptionFacts(**base)


def _ctx(*facts: ExceptionFacts, **kwargs: Any) -> CommandContext:
    return CommandContext(exceptions={f.exception_id: f for f in facts}, **kwargs)


def _validate(command: ParsedCommand, ctx: CommandContext, role: str = "owner") -> Preview:
    return validate(command, ctx, cfg=CFG, role=role)


# --- §8.5 rule 1: target amount != exception amount --------------------------


def test_a_wrong_amount_target_reports_the_delta_and_offers_a_residual() -> None:
    """Not a refusal. Linking explains the matching part; the rest stays open
    rather than being closed by something that does not account for it."""
    preview = _validate(
        _command(verb="link_to", exception_id="exc_1", target_type="order", target_ref="order_A"),
        _ctx(
            _facts(amount_paise=5_200_000),
            resolved_refs={
                "order_A": RefCandidate(ref="order_A", kind="order", amount_paise=4_876_000)
            },
        ),
    )
    assert preview.ok
    mismatch = next(w for w in preview.warnings if w.code == "amount_mismatch")
    assert mismatch.detail["delta_paise"] == 324_000
    assert "₹3,240.00" in mismatch.message
    residual = next(e for e in preview.effects if e.action == "exception.residual")
    assert residual.detail["residual_paise"] == 324_000


def test_a_matching_amount_produces_no_delta_warning() -> None:
    preview = _validate(
        _command(verb="link_to", exception_id="exc_1", target_type="order", target_ref="order_A"),
        _ctx(
            _facts(amount_paise=100_000),
            resolved_refs={
                "order_A": RefCandidate(ref="order_A", kind="order", amount_paise=100_000)
            },
        ),
    )
    assert not [w for w in preview.warnings if w.code == "amount_mismatch"]
    assert not [e for e in preview.effects if e.action == "exception.residual"]


# --- §8.5 rule 2: referenced ref not found -----------------------------------


def test_a_missing_reference_lists_near_matches_and_never_picks_one() -> None:
    preview = _validate(
        _command(verb="link_to", exception_id="exc_1", target_type="order", target_ref="order_XYZ"),
        _ctx(
            _facts(),
            near_matches={
                "order_XYZ": [
                    RefCandidate(ref="order_XYY", kind="order", amount_paise=100_000),
                    RefCandidate(ref="order_XZY", kind="order", amount_paise=100_000),
                ]
            },
        ),
    )
    assert preview.refusal is not None
    assert preview.refusal.code == "not_found"
    assert len(preview.refusal.candidates) == 2
    assert preview.effects == (), "a refusal must not also propose an effect"


def test_a_missing_exception_is_refused_with_near_matches() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_missing", category="manual_refund", reason="r"),
        CommandContext(
            near_matches={"exc_missing": [RefCandidate(ref="exc_missin", kind="exception")]}
        ),
    )
    assert preview.refusal is not None
    assert preview.refusal.code == "not_found"
    assert preview.refusal.candidates


# --- §8.5 rule 3: ambiguous across two or more candidates --------------------


def test_an_ambiguous_reference_lists_the_candidates_and_asks() -> None:
    """Hard rule 4: when several answers are valid, abstain. Picking one here
    is the exact failure this layer exists to prevent."""
    preview = _validate(
        _command(verb="link_to", exception_id="exc_1", target_type="order", target_ref="order_A"),
        _ctx(
            _facts(),
            ambiguous_refs={
                "order_A": [
                    RefCandidate(ref="order_A", kind="order", amount_paise=100_000),
                    RefCandidate(ref="order_A", kind="payment", amount_paise=100_000),
                ]
            },
        ),
    )
    assert preview.refusal is not None
    assert preview.refusal.code == "ambiguous"
    assert len(preview.refusal.candidates) == 2


# --- §8.5 rule 4: closing a chargeback with no dispute reference -------------


def test_closing_a_chargeback_without_a_dispute_reference_requires_acknowledgement() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(category="chargeback_unrecorded", has_dispute_reference=False)),
    )
    assert preview.requires_acknowledgement
    warning = next(w for w in preview.warnings if w.code == "chargeback_without_dispute_ref")
    assert "contest window" in warning.message


def test_a_chargeback_with_a_dispute_reference_needs_no_acknowledgement() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(category="chargeback_unrecorded", has_dispute_reference=True)),
    )
    assert not preview.requires_acknowledgement


def test_other_never_auto_categories_warn_without_blocking() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(category="ambiguous_multi_candidate")),
    )
    assert preview.ok
    assert any(w.code == "never_auto_category" for w in preview.warnings)


# --- §8.5 rule 5: value above the typed-confirmation threshold ---------------


def test_an_amount_above_the_threshold_requires_the_user_to_type_it() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(amount_paise=CFG.typed_confirm_paise)),
    )
    assert preview.requires_typed_confirmation
    assert preview.typed_confirmation_paise == CFG.typed_confirm_paise


def test_an_amount_below_the_threshold_does_not() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(amount_paise=CFG.typed_confirm_paise - 1)),
    )
    assert not preview.requires_typed_confirmation


def test_a_write_off_totals_across_items_before_applying_the_threshold() -> None:
    """Three items just under the line are still ₹1,50,000 leaving the books."""
    ids = ["exc_1", "exc_2", "exc_3"]
    preview = _validate(
        _command(verb="write_off", exception_ids=ids, reason="not worth chasing"),
        _ctx(*(_facts(exception_id=i, amount_paise=2_000_000) for i in ids)),
    )
    assert preview.requires_typed_confirmation
    assert preview.typed_confirmation_paise == 6_000_000


# --- §8.5 rule 6: role lacks the permission ----------------------------------


@pytest.mark.parametrize("role", ["auditor", "viewer"])
def test_a_role_without_the_permission_is_refused_and_told_which_role_has_it(role: str) -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts()),
        role=role,
    )
    assert preview.refusal is not None
    assert preview.refusal.code == "forbidden"
    assert preview.refusal.detail["required_role"] == "finance_exec"
    assert "finance_exec" in preview.refusal.message


def test_permission_is_checked_before_anything_is_looked_up() -> None:
    """A role that may not act should not learn whether a record exists."""
    preview = _validate(
        _command(verb="resolve", exception_id="exc_does_not_exist", category="x", reason="r"),
        CommandContext(),
        role="viewer",
    )
    assert preview.refusal is not None
    assert preview.refusal.code == "forbidden"


def test_finance_exec_can_draft_a_rule_but_the_draft_is_still_only_a_draft() -> None:
    assert can("finance_exec", "rule:draft")
    assert not can("finance_exec", "rule:activate")


def test_the_permission_table_is_the_one_the_prd_specifies() -> None:
    assert set(PERMISSIONS) == {"owner", "finance_manager", "finance_exec", "auditor", "viewer"}
    assert can("owner", "anything:at_all")
    assert roles_permitting("exception:resolve") == ("owner", "finance_manager", "finance_exec")


# --- §8.5 rule 7: concurrent edit --------------------------------------------


def test_an_exception_that_moved_since_the_preview_is_refused_with_its_new_state() -> None:
    """Only meaningful at execute time, when ``expected_state`` carries what the
    human was actually shown."""
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(
            _facts(state_fingerprint="v2", status="resolved"),
            expected_state={"exc_1": "v1"},
        ),
    )
    assert preview.refusal is not None
    assert preview.refusal.code == "conflict"
    assert preview.refusal.detail["current_status"] == {"exc_1": "resolved"}


def test_an_unchanged_exception_passes_the_lock_check() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(state_fingerprint="v1"), expected_state={"exc_1": "v1"}),
    )
    assert preview.ok


def test_at_parse_time_there_is_no_expected_state_and_no_conflict_check() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(state_fingerprint="anything")),
    )
    assert preview.ok


# --- cut and unbuilt verbs ---------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"verb": "split_cluster", "cluster_id": "cls_1", "exception_ids": ["exc_1"]},
        {"verb": "merge_cluster", "cluster_ids": ["cls_1", "cls_2"]},
    ],
)
def test_cluster_split_and_merge_are_refused_by_name(payload: dict[str, Any]) -> None:
    preview = _validate(_command(**payload), CommandContext())
    assert preview.refusal is not None
    assert preview.refusal.code == "cut"
    assert "grouping key" in preview.refusal.message


def test_post_entries_renders_the_journal_lines_and_says_nothing_posts_them() -> None:
    """More useful than pretending the verb does not parse: the operator can
    take the lines to Tally themselves."""
    preview = _validate(
        _command(
            verb="post_entries",
            exception_id="exc_1",
            dr="Sales Return",
            cr="HDFC Clearing",
            amount_paise=5_200_000,
        ),
        _ctx(_facts()),
    )
    assert preview.refusal is not None
    assert preview.refusal.code == "unsupported"
    assert "Dr Sales Return ₹52,000.00" in preview.summary
    assert preview.refusal.detail["amount_paise"] == 5_200_000


def test_a_backwards_rerun_period_is_refused() -> None:
    preview = _validate(
        _command(verb="rerun", period_start=date(2026, 8, 31), period_end=date(2026, 8, 1)),
        CommandContext(),
    )
    assert preview.refusal is not None
    assert preview.refusal.code == "invalid"


def test_notify_refuses_a_recipient_that_is_not_an_email_rather_than_guessing() -> None:
    preview = _validate(
        _command(verb="notify", recipients=["Priya"], exception_ids=["exc_1"]),
        _ctx(_facts()),
    )
    assert preview.refusal is not None
    assert "will not guess" in preview.refusal.message


def test_an_instruction_naming_nothing_is_refused_rather_than_defaulted() -> None:
    """ "Close it" with no context is not an instruction to close the first
    thing in the queue."""
    preview = _validate(
        _command(verb="resolve", exception_id="", category="manual_refund", reason="r"),
        CommandContext(),
    )
    assert preview.refusal is not None
    assert preview.refusal.code == "invalid"
    assert "which exception" in preview.refusal.message


# --- read-only verbs ---------------------------------------------------------


def test_query_and_explain_need_no_confirmation() -> None:
    for command in (
        _command(verb="query", question="how much is open?"),
        _command(verb="explain", exception_id="exc_1"),
    ):
        preview = _validate(command, CommandContext())
        assert preview.ok
        assert not preview.requires_typed_confirmation
        assert not preview.requires_acknowledgement


def test_an_auditor_may_ask_but_a_viewer_may_not() -> None:
    command = _command(verb="query", question="how much is open?")
    assert _validate(command, CommandContext(), role="auditor").ok
    assert _validate(command, CommandContext(), role="viewer").refusal is not None


# --- §8.6 cluster offer ------------------------------------------------------


def test_a_clustered_exception_offers_the_rest_of_its_cluster() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(cluster_id="cls_1"), cluster_sizes={"cls_1": 14}),
    )
    assert preview.cluster_offer is not None
    assert preview.cluster_offer.member_count == 13, "offered to re-apply to itself"


def test_a_lone_exception_offers_nothing() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(cluster_id="cls_1"), cluster_sizes={"cls_1": 1}),
    )
    assert preview.cluster_offer is None


# --- §10.3 layer 6, surfaced through the preview -----------------------------


def test_a_suspicious_narration_surfaces_as_a_warning_on_the_preview() -> None:
    preview = _validate(
        _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r"),
        _ctx(_facts(suspicious_patterns=("authority_claim", "bulk_directive"))),
    )
    warning = next(w for w in preview.warnings if w.code == "suspicious_narration")
    assert warning.detail["patterns"] == ["authority_claim", "bulk_directive"]
    assert "Nothing acted on it" in warning.message


# --- the preview fingerprint -------------------------------------------------


def test_the_fingerprint_changes_when_an_effect_changes() -> None:
    """What makes "the plan you approved is the plan that runs" checkable."""
    command = _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r")
    before = _validate(command, _ctx(_facts(amount_paise=100_000))).fingerprint()
    after = _validate(command, _ctx(_facts(amount_paise=200_000))).fingerprint()
    assert before != after


def test_the_fingerprint_changes_when_only_a_warning_changes() -> None:
    """A warning is part of what was approved, not decoration around it."""
    command = _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r")
    plain = _validate(command, _ctx(_facts())).fingerprint()
    flagged = _validate(
        command, _ctx(_facts(suspicious_patterns=("authority_claim",)))
    ).fingerprint()
    assert plain != flagged


def test_the_fingerprint_is_stable_across_identical_validations() -> None:
    command = _command(verb="resolve", exception_id="exc_1", category="manual_refund", reason="r")
    assert (
        _validate(command, _ctx(_facts())).fingerprint()
        == _validate(command, _ctx(_facts())).fingerprint()
    )
