"""A rule shrinks an exception. That is the feature, and this is where it is proved.

The headline case is the one PRD §6.7 states: a ₹19,000 gap that the Blinkit
commission rule explains ₹15,760 of becomes "₹3,240 unexplained after
blinkit_commission rule applied", with the rule's version hash attached — not
"₹19,000 mismatch", and not a boolean.

The second thing proved here is the ceiling. A rule confers at most its own
``effective_confidence`` and has no arithmetic path to raising an item's
confidence at all, so it can never carry something over the auto-close threshold
on its own strength.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from fc.config import Config, load_config
from fc.models.money import fmt_inr
from fc.models.rule import Deduction, Rule, RuleApplication, Scope, Tolerance
from fc.models.transaction import TransactionEvent
from fc.rules.apply import RuleOutcomeResult, apply_rules, rule_tolerance_paise
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules, version_hash

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_ON = date(2026, 6, 15)

#: The gross at which the shipped 18% / 18%-on-commission / 1% stack sums to
#: exactly ₹15,760.00 with per-line ROUND_HALF_UP. Chosen so the §6.7 example is
#: reproduced to the paise by the *shipped* rule rather than by a rate invented
#: for the test.
BLINKIT_GROSS_PAISE = 70_863_31
BLINKIT_GAP_PAISE = 19_000_00
BLINKIT_EXPLAINED_PAISE = 15_760_00
BLINKIT_RESIDUAL_PAISE = 3_240_00


def _cfg(**overrides: object) -> Config:
    return load_config(env_file=None, environ={}).model_copy(update=overrides)


def _starter() -> tuple[Rule, ...]:
    return load_rules(DEFAULT_RULES_PATH, tenant_id="t_lumea", created_at=_AT).rules


def _blinkit_event(amount: int = BLINKIT_GROSS_PAISE) -> TransactionEvent:
    return TransactionEvent(
        event_id="e_bank_credit",
        run_id="run",
        tenant_id="t_lumea",
        source="bank",
        source_row_id="e_bank_credit",
        amount_paise=amount,
        direction="credit",
        txn_date=_ON,
        counterparty="BLINKIT",
        counterparty_norm="BLINKIT",
        rail="neft",
        raw_narration="NEFT-BLINKIT COMMERCE PVT LTD-WEEKLY PAYOUT",
        raw={},
        ingested_at=_AT,
    )


def _rule(
    rule_id: str,
    deductions: list[Deduction],
    *,
    priority: int = 100,
    effective_confidence: Decimal = Decimal("0.95"),
    absolute_paise: int = 100,
    **scope_kwargs: object,
) -> Rule:
    scope = Scope(date_from=date(2026, 4, 1), **scope_kwargs)  # type: ignore[arg-type]
    tolerance = Tolerance(absolute_paise=absolute_paise, percent=Decimal("0.05"))
    return Rule(
        rule_id=rule_id,
        version=1,
        tenant_id="t_lumea",
        version_hash=version_hash(scope, deductions, tolerance),
        name=rule_id,
        scope=scope,
        deductions=deductions,
        tolerance=tolerance,
        priority=priority,
        effective_confidence=effective_confidence,
        effective_from=scope.date_from,
        status="active",
        origin="manual",
        created_by="u",
        created_at=_AT,
    )


# --- the headline case ----------------------------------------------------


def test_the_blinkit_rule_shrinks_a_19000_gap_to_3240() -> None:
    result = apply_rules(
        _starter(),
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=BLINKIT_GAP_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        n_txns=1,
        cfg=_cfg(),
    )

    assert result.outcome == "partially_explained"
    assert result.explained_paise == BLINKIT_EXPLAINED_PAISE
    assert result.residual_paise == BLINKIT_RESIDUAL_PAISE
    assert fmt_inr(result.residual_paise) == "₹3,240.00"

    applied = result.applications[0]
    assert applied.rule_id == "blinkit_commission"
    assert applied.version == 3
    assert applied.version_hash  # the provenance stamp travels with the number
    assert len(applied.version_hash) == 64


def test_the_output_reads_as_a_shrunken_exception_not_a_mismatch() -> None:
    result = apply_rules(
        _starter(),
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=BLINKIT_GAP_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        cfg=_cfg(),
    )
    assert result.narrative().startswith(
        "₹3,240.00 unexplained after blinkit_commission rule applied"
    )
    assert "₹19,000.00" not in result.narrative().split("(")[0]


def test_the_shrunken_exception_carries_the_rule_version_hash_for_the_ledger() -> None:
    """``exceptions.rules_applied`` is what an auditor reads a year later."""
    result = apply_rules(
        _starter(),
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=BLINKIT_GAP_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        cfg=_cfg(),
    )
    (ref,) = result.as_exception_refs()
    assert ref.rule_id == "blinkit_commission"
    assert ref.version == 3
    assert ref.explained_paise == BLINKIT_EXPLAINED_PAISE
    assert ref.arithmetic is not None and "commission 18% of gross" in ref.arithmetic


def test_the_stack_is_kept_line_by_line_not_just_the_total() -> None:
    result = apply_rules(
        _starter(),
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=BLINKIT_GAP_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        cfg=_cfg(),
    )
    stack = {item.type: item.amount_paise for item in result.applications[0].stack}
    assert stack == {"commission": 12_755_40, "gst_on_fee": 2_295_97, "tds_194o": 708_63}
    assert sum(stack.values()) == BLINKIT_EXPLAINED_PAISE


# --- the three outcomes ---------------------------------------------------


def test_a_gap_the_stack_matches_within_tolerance_is_fully_explained() -> None:
    result = apply_rules(
        _starter(),
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=BLINKIT_EXPLAINED_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        cfg=_cfg(),
    )
    assert result.outcome == "fully_explained"
    assert result.residual_paise == 0
    assert result.may_auto_close


def test_a_gap_no_rule_speaks_to_is_not_applicable() -> None:
    """Not "unexplained by rule X" — no rule was in scope at all."""
    stranger = _blinkit_event().model_copy(
        update={"counterparty": "SWIGGY", "counterparty_norm": "SWIGGY", "raw_narration": "NEFT"}
    )
    result = apply_rules(
        _starter(),
        event=stranger,
        on_date=_ON,
        gap_paise=BLINKIT_GAP_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        cfg=_cfg(),
    )
    assert result.outcome == "not_applicable"
    assert result.applications == ()
    assert result.residual_paise == BLINKIT_GAP_PAISE
    assert result.narrative() == "₹19,000.00 unexplained; no rule applies"


def test_a_partially_explained_item_never_auto_closes() -> None:
    """Not a threshold anyone can tune: money still unexplained does not close."""
    result = apply_rules(
        _starter(),
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=BLINKIT_GAP_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        cfg=_cfg(),
    )
    assert result.outcome == "partially_explained"
    assert not result.may_auto_close


# --- the loop keeps going -------------------------------------------------


def test_a_second_rule_finishes_what_the_first_started() -> None:
    """The ``continue`` in §6.7 that most implementations turn into a ``return``."""
    commission = _rule(
        "commission_only",
        [Deduction(type="commission", basis="gross", rate=Decimal("18"))],
        priority=200,
        counterparty_matches=["BLINKIT"],
    )
    tds = _rule(
        "tds_only",
        [Deduction(type="tds_194o", basis="gross", rate=Decimal("1"))],
        priority=100,
        counterparty_matches=["BLINKIT"],
    )
    gap = 19_000_00
    result = apply_rules(
        [commission, tds],
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=gap,
        gross_paise=1_00_000_00,
        cfg=_cfg(),
    )
    # Neither rule explains ₹19,000 alone; together they close it exactly.
    assert result.outcome == "fully_explained"
    assert [a.rule_id for a in result.applications] == ["commission_only", "tds_only"]
    assert [a.outcome for a in result.applications] == [
        "partially_explained",
        "fully_explained",
    ]
    assert result.explained_paise == 18_000_00 + 1_000_00
    assert result.residual_paise == 0
    assert "commission_only and tds_only rules" in result.narrative()

    # The first rule alone stops short, which is what makes the second one load-bearing.
    alone = apply_rules(
        [commission],
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=gap,
        gross_paise=1_00_000_00,
        cfg=_cfg(),
    )
    assert alone.outcome == "partially_explained"
    assert alone.residual_paise == 1_000_00


def test_a_rule_that_overshoots_the_remaining_gap_is_skipped() -> None:
    """ "Made it worse" is a skip, and a skip leaves no evidence behind."""
    huge = _rule(
        "huge",
        [Deduction(type="commission", basis="gross", rate=Decimal("50"))],
        counterparty_matches=["BLINKIT"],
    )
    result = apply_rules(
        [huge],
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=1_000_00,
        gross_paise=1_00_000_00,
        cfg=_cfg(),
    )
    assert result.outcome == "not_applicable"
    assert result.considered == 1  # it was tried
    assert result.applications == ()  # and trying is not evidence


def test_a_rule_that_explains_nothing_is_skipped() -> None:
    empty = _rule("empty", [], counterparty_matches=["BLINKIT"])
    result = apply_rules(
        [empty],
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=1_000_00,
        gross_paise=1_00_000_00,
        cfg=_cfg(),
    )
    assert result.outcome == "not_applicable"


def test_a_rule_deducting_more_than_the_gross_is_declined() -> None:
    """A flat fee bigger than a tiny settlement. Real, and not an explanation."""
    flat = _rule(
        "flat_fee",
        [Deduction(type="platform_fee", basis="gross", rate=Decimal("0"), fixed_paise=20_00)],
        counterparty_matches=["BLINKIT"],
    )
    result = apply_rules(
        [flat],
        event=_blinkit_event(amount=5_00),
        on_date=_ON,
        gap_paise=20_00,
        gross_paise=5_00,
        cfg=_cfg(),
    )
    assert result.outcome == "not_applicable"


# --- the confidence ceiling ----------------------------------------------


@given(prior=st.decimals(min_value=0, max_value=1, places=4))
def test_a_rule_can_never_raise_an_items_confidence(prior: Decimal) -> None:
    """The enforcement, stated as a property: the output never exceeds the input."""
    result = apply_rules(
        _starter(),
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=BLINKIT_EXPLAINED_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        cfg=_cfg(),
    )
    assert result.confidence_after(prior) <= prior


def test_a_rule_confers_at_most_its_own_effective_confidence() -> None:
    modest = _rule(
        "modest",
        [Deduction(type="commission", basis="gross", rate=Decimal("18"))],
        effective_confidence=Decimal("0.60"),
        counterparty_matches=["BLINKIT"],
    )
    result = apply_rules(
        [modest],
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=18_000_00,
        gross_paise=1_00_000_00,
        cfg=_cfg(),
    )
    assert result.outcome == "fully_explained"
    assert result.confidence_ceiling == Decimal("0.60")
    assert result.confidence_after(Decimal("0.99")) == Decimal("0.60")
    assert result.confidence_after(None) == Decimal("0.60")


def test_the_ceiling_is_the_weakest_rule_in_the_stack_not_the_first() -> None:
    """A 0.99 rule explaining ₹200 must not vouch for a 0.70 rule's ₹15,000."""
    trusted = _rule(
        "trusted",
        [Deduction(type="tds_194o", basis="gross", rate=Decimal("1"))],
        priority=200,
        effective_confidence=Decimal("0.99"),
        counterparty_matches=["BLINKIT"],
    )
    shaky = _rule(
        "shaky",
        [Deduction(type="commission", basis="gross", rate=Decimal("18"))],
        priority=100,
        effective_confidence=Decimal("0.70"),
        counterparty_matches=["BLINKIT"],
    )
    result = apply_rules(
        [trusted, shaky],
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=19_000_00,
        gross_paise=1_00_000_00,
        cfg=_cfg(),
    )
    assert [a.rule_id for a in result.applications] == ["trusted", "shaky"]
    assert result.confidence_ceiling == Decimal("0.70")


def test_a_ceiling_above_the_weakest_applied_rule_is_rejected_by_the_model() -> None:
    """Enforced by the type, so a future construction site cannot forget it."""
    application = RuleApplication(
        rule_id="r",
        version=1,
        version_hash="h",
        outcome="fully_explained",
        gross_paise=1_00_000_00,
        gap_before_paise=18_000_00,
        explained_paise=18_000_00,
        residual_paise=0,
        tolerance_paise=100,
        effective_confidence=Decimal("0.70"),
        arithmetic="x",
    )
    with pytest.raises(ValidationError, match="exceeds the weakest applied rule"):
        RuleOutcomeResult(
            outcome="fully_explained",
            gross_paise=1_00_000_00,
            gap_before_paise=18_000_00,
            explained_paise=18_000_00,
            residual_paise=0,
            applications=(application,),
            confidence_ceiling=Decimal("0.95"),
        )


def test_an_unapplied_rulebook_caps_nothing() -> None:
    result = apply_rules(
        (),
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=19_000_00,
        gross_paise=1_00_000_00,
        cfg=_cfg(),
    )
    assert result.confidence_ceiling == Decimal(1)
    assert result.confidence_after(Decimal("0.97")) == Decimal("0.97")


# --- arithmetic invariants and determinism --------------------------------


def test_explained_plus_residual_always_equals_the_gap() -> None:
    with pytest.raises(ValidationError, match="!= gap"):
        RuleApplication(
            rule_id="r",
            version=1,
            version_hash="h",
            outcome="partially_explained",
            gross_paise=1_00_000_00,
            gap_before_paise=19_000_00,
            explained_paise=15_760_00,
            residual_paise=1_00_00,  # does not close
            tolerance_paise=100,
            effective_confidence=Decimal("0.95"),
            arithmetic="x",
        )


def test_fully_explained_with_a_residual_beyond_tolerance_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exceeds tolerance"):
        RuleApplication(
            rule_id="r",
            version=1,
            version_hash="h",
            outcome="fully_explained",
            gross_paise=1_00_000_00,
            gap_before_paise=19_000_00,
            explained_paise=15_760_00,
            residual_paise=3_240_00,
            tolerance_paise=100,
            effective_confidence=Decimal("0.95"),
            arithmetic="x",
        )


def test_the_same_rules_and_the_same_gap_give_byte_identical_results() -> None:
    """Hard rule 9. Serialised, not compared field by field."""
    rules = _starter()
    runs = [
        apply_rules(
            rules,
            event=_blinkit_event(),
            on_date=_ON,
            gap_paise=BLINKIT_GAP_PAISE,
            gross_paise=BLINKIT_GROSS_PAISE,
            cfg=_cfg(),
        ).model_dump_json()
        for _ in range(3)
    ]
    assert runs[0] == runs[1] == runs[2]


def test_rule_ordering_does_not_depend_on_how_the_rulebook_was_listed() -> None:
    rules = list(_starter())
    forward = apply_rules(
        rules,
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=BLINKIT_GAP_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        cfg=_cfg(),
    )
    backward = apply_rules(
        list(reversed(rules)),
        event=_blinkit_event(),
        on_date=_ON,
        gap_paise=BLINKIT_GAP_PAISE,
        gross_paise=BLINKIT_GROSS_PAISE,
        cfg=_cfg(),
    )
    assert forward.model_dump_json() == backward.model_dump_json()


# --- tolerance ------------------------------------------------------------


def test_the_rule_tolerance_keeps_the_rounding_drift_term() -> None:
    """A batch's fee is a sum of per-transaction roundings whoever computes it."""
    rule = _rule("r", [], absolute_paise=100)
    assert rule_tolerance_paise(rule, 1_000_00, n_txns=1, cfg=_cfg()) == 100
    assert rule_tolerance_paise(rule, 1_000_00, n_txns=500, cfg=_cfg()) == 500
    assert rule_tolerance_paise(rule, 1_000_00, n_txns=500, cfg=_cfg(rounding_drift_paise=0)) == 100


def test_the_rule_percentage_is_a_percentage_not_a_fraction() -> None:
    """0.05 means 0.05% of gross — 50 paise on ₹1,00,000, not ₹5,000."""
    rule = _rule("r", [], absolute_paise=0)
    assert rule_tolerance_paise(rule, 1_00_000_00) == 5000


def test_the_rules_own_tolerance_overrides_the_run_wide_default() -> None:
    """A marketplace rule knows its settlement's slop better than a constant does."""
    generous = _rule("generous", [], absolute_paise=5_00)
    assert rule_tolerance_paise(generous, 1_000_00, n_txns=1, cfg=_cfg()) == 5_00
