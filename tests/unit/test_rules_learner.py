"""Three identical resolutions produce a draft. A draft is never active.

§8.8's loop is the one that turns a human's knowledge into something the system
stops asking about. The safety property is that it stops there: the learner
proposes, a human with the back-test in front of them approves, and nothing in
between can shorten that path.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fc.models.rule import Deduction, Rule, Scope, Tolerance
from fc.models.transaction import TransactionEvent
from fc.rules.apply import apply_rules
from fc.rules.evaluator import evaluate_deductions
from fc.rules.learner import (
    DRAFT_THRESHOLD,
    LEARNED_DRAFT_CONFIDENCE,
    Resolution,
    amount_band,
    detect_drafts,
    gap_shape,
    signature,
)
from fc.rules.loader import version_hash

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_ON = date(2026, 6, 15)


def _event(event_id: str, amount: int, *, counterparty: str = "BLINKIT") -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t_lumea",
        source="bank",
        source_row_id=event_id,
        amount_paise=amount,
        direction="credit",
        txn_date=_ON,
        counterparty=counterparty,
        counterparty_norm=counterparty,
        rail="neft",
        raw_narration=f"NEFT-{counterparty}-PAYOUT",
        raw={},
        ingested_at=_AT,
    )


def _resolution(
    exception_id: str,
    gross: int,
    gap: int,
    *,
    category: str = "amount_variance",
    resolution_category: str = "platform_commission",
    counterparty: str = "BLINKIT",
) -> Resolution:
    return Resolution(
        exception_id=exception_id,
        category=category,  # type: ignore[arg-type]
        resolution_category=resolution_category,
        event=_event(f"e_{exception_id}", gross, counterparty=counterparty),
        on_date=_ON,
        gap_paise=gap,
        gross_paise=gross,
    )


def _three(rate_percent: str = "22.24") -> list[Resolution]:
    """Three settlements of different sizes, each short by the same proportion.

    All three sit inside one ``amount_band``, because §8.8 puts the band in the
    signature: a ₹40,000 payout and a ₹4,00,000 payout are not obviously the same
    problem, and the band is what says so.
    """
    rate = Decimal(rate_percent) / 100
    return [
        _resolution(f"exc_{i}", gross, int(Decimal(gross) * rate))
        for i, gross in enumerate((40_000_00, 71_500_00, 95_000_00))
    ]


def _draft_args() -> dict[str, object]:
    return {"tenant_id": "t_lumea", "created_at": _AT}


# --- the signature --------------------------------------------------------


def test_the_signature_groups_the_same_problem_at_different_sizes() -> None:
    """No two settlements share an exact amount, so the shape has to be banded."""
    shapes = {r.signature for r in _three()}
    assert len(shapes) == 1


def test_a_different_rate_is_a_different_signature() -> None:
    assert _three("22.24")[0].signature != _three("26.80")[0].signature


def test_a_different_counterparty_is_a_different_signature() -> None:
    a = _resolution("x", 40_000_00, 8_896_00)
    b = _resolution("x", 40_000_00, 8_896_00, counterparty="ZEPTO")
    assert a.signature != b.signature


def test_a_different_category_is_a_different_signature() -> None:
    a = _resolution("x", 40_000_00, 8_896_00)
    b = _resolution("x", 40_000_00, 8_896_00, category="partial_refund")
    assert a.signature != b.signature


def test_the_signature_components_cannot_run_into_each_other() -> None:
    """``("AB","C")`` and ``("A","BC")`` must not collide."""
    left = signature(
        category="ab",
        counterparty_norm="c",
        rail="neft",
        amount_paise=1000,
        gap_paise=100,
        gross_paise=1000,
    )
    right = signature(
        category="a",
        counterparty_norm="bc",
        rail="neft",
        amount_paise=1000,
        gap_paise=100,
        gross_paise=1000,
    )
    assert left != right


def test_amount_bands_are_orders_of_magnitude() -> None:
    assert amount_band(500_00) == "<1k"
    assert amount_band(5_000_00) == "1k-10k"
    assert amount_band(50_000_00) == "10k-1L"
    assert amount_band(5_00_000_00) == "1L-10L"
    assert amount_band(50_00_000_00) == ">10L"
    assert amount_band(-5_000_00) == "1k-10k"


def test_the_gap_shape_is_a_proportion_not_an_amount() -> None:
    assert gap_shape(22_240_00, 1_00_000_00) == "22-22.5%"
    assert gap_shape(2_224_00, 10_000_00) == "22-22.5%"
    assert gap_shape(0, 0) == "gross=0"


# --- the 3x rule ----------------------------------------------------------


def test_three_identical_resolutions_produce_a_draft() -> None:
    drafts = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.occurrences == 3
    assert draft.exception_ids == ("exc_0", "exc_1", "exc_2")
    assert draft.resolution_category == "platform_commission"


def test_two_is_not_enough() -> None:
    assert detect_drafts(_three()[:2], **_draft_args()) == ()  # type: ignore[arg-type]
    assert DRAFT_THRESHOLD == 3


def test_three_of_the_same_shape_resolved_differently_are_not_a_pattern() -> None:
    """§8.8 counts on the signature *and* the resolution category."""
    resolutions = _three()
    resolutions[2] = Resolution(**{**resolutions[2].__dict__, "resolution_category": "written_off"})
    assert detect_drafts(resolutions, **_draft_args()) == ()  # type: ignore[arg-type]


def test_a_signature_an_active_rule_already_covers_produces_nothing() -> None:
    covering = _rule_covering_blinkit()
    assert detect_drafts(_three(), active_rules=[covering], **_draft_args()) == ()  # type: ignore[arg-type]


def test_a_rule_covering_only_some_of_the_group_does_not_suppress_the_draft() -> None:
    """The uncovered ones keep recurring, which is what the learner exists to notice."""
    resolutions = _three()
    resolutions[2] = Resolution(
        **{**resolutions[2].__dict__, "event": _event("e_other", 95_000_00, counterparty="ZEPTO")}
    )
    # Now the three no longer share a signature at all, so use a narrower rule instead.
    narrow = _rule_covering_blinkit(amount_max_paise=50_000_00)
    assert len(detect_drafts(_three(), active_rules=[narrow], **_draft_args())) == 1  # type: ignore[arg-type]


def test_never_auto_categories_are_never_learned_from() -> None:
    """Three chargebacks resolved the same way say nothing about a deduction rate."""
    chargebacks = [
        _resolution(f"exc_{i}", gross, gross * 2224 // 10000, category="chargeback_unrecorded")
        for i, gross in enumerate((40_000_00, 71_500_00, 95_000_00))
    ]
    assert detect_drafts(chargebacks, **_draft_args()) == ()  # type: ignore[arg-type]


# --- what the draft is ----------------------------------------------------


def test_a_draft_is_never_active() -> None:
    (draft,) = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    assert draft.rule.status == "draft"
    assert draft.rule.origin == "learned"
    assert draft.rule.activated_by is None
    assert draft.rule.activated_at is None


def test_a_draft_cannot_be_applied_by_the_reconciliation_path() -> None:
    """The safety property, checked at the place that would close something."""
    (draft,) = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    case = _three()[0]
    result = apply_rules(
        [draft.rule],
        event=case.event,
        on_date=_ON,
        gap_paise=case.gap_paise,
        gross_paise=case.gross_paise,
    )
    assert result.outcome == "not_applicable"


def test_a_draft_proposes_a_ceiling_below_the_shipped_auto_threshold() -> None:
    """A rule nobody approved does not carry an item to auto-close on its own."""
    (draft,) = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    assert draft.rule.effective_confidence == LEARNED_DRAFT_CONFIDENCE
    assert LEARNED_DRAFT_CONFIDENCE < Decimal("0.94")


def test_the_draft_learns_the_rate_it_actually_observed() -> None:
    (draft,) = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    assert draft.observed_rate_percent == Decimal("22.24")
    assert draft.rule.deductions == [Deduction(type="custom", basis="gross", rate=Decimal("22.24"))]


def test_the_draft_explains_every_case_it_was_learned_from() -> None:
    """A draft that misses its own evidence would waste the human's approval."""
    (draft,) = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    for case in draft.resolutions:
        stack = evaluate_deductions(draft.rule.deductions, case.gross_paise)
        assert abs(case.gap_paise - stack.total_paise) <= draft.rule.tolerance.absolute_paise


def test_a_noisy_group_produces_a_visibly_wide_tolerance() -> None:
    """Three cases that disagree cannot hide it behind a confident-looking rate.

    The disagreement has to stay inside one ``gap_shape`` band — noise wider than
    half a percentage point is a *different* signature, and the learner would
    correctly decline to call it a pattern at all.
    """
    tight = detect_drafts(_three(), **_draft_args())[0]  # type: ignore[arg-type]
    noisy = [
        _resolution("exc_0", 40_000_00, 8_896_00),  # 22.24%
        _resolution("exc_1", 71_500_00, 15_902_60),  # 22.24%
        _resolution("exc_2", 95_000_00, 21_000_00),  # 22.11%, off the trend
    ]
    assert len({r.signature for r in noisy}) == 1
    assert detect_drafts(noisy, **_draft_args())[0].rule.tolerance.absolute_paise > (  # type: ignore[arg-type]
        tight.rule.tolerance.absolute_paise
    )


def test_the_draft_scopes_itself_to_the_counterparty_it_learned_from() -> None:
    (draft,) = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    assert draft.rule.scope.counterparty_matches == ["BLINKIT"]
    assert draft.rule.scope.rail == "neft"
    assert draft.rule.scope.date_from == _ON


def test_the_draft_yields_to_hand_written_rules_on_priority() -> None:
    (draft,) = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    assert draft.rule.priority < 100


def test_the_draft_names_its_evidence_where_a_human_will_read_it() -> None:
    (draft,) = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    assert draft.rule.description is not None
    assert "exc_0, exc_1, exc_2" in draft.rule.description
    assert "22.24%" in draft.rule.description
    assert "Not applied until a human activates it." in draft.rule.description


def test_the_draft_carries_a_version_hash_over_its_own_semantics() -> None:
    (draft,) = detect_drafts(_three(), **_draft_args())  # type: ignore[arg-type]
    rule = draft.rule
    assert rule.version_hash == version_hash(rule.scope, rule.deductions, rule.tolerance)


def test_learning_the_same_history_twice_gives_the_same_draft() -> None:
    """Hard rule 9: a suggestion that changes between runs cannot be reviewed."""
    first = detect_drafts(_three(), **_draft_args())[0]  # type: ignore[arg-type]
    second = detect_drafts(list(reversed(_three())), **_draft_args())[0]  # type: ignore[arg-type]
    assert first.rule.model_dump_json() == second.rule.model_dump_json()


def _rule_covering_blinkit(**scope_kwargs: object) -> Rule:
    scope = Scope(
        counterparty_matches=["BLINKIT"],
        date_from=date(2026, 4, 1),
        **scope_kwargs,  # type: ignore[arg-type]
    )
    deductions = [Deduction(type="commission", basis="gross", rate=Decimal("18"))]
    tolerance = Tolerance(absolute_paise=500, percent=Decimal("0.05"))
    return Rule(
        rule_id="blinkit_commission",
        version=3,
        tenant_id="t_lumea",
        version_hash=version_hash(scope, deductions, tolerance),
        name="Blinkit commission",
        scope=scope,
        deductions=deductions,
        tolerance=tolerance,
        effective_from=scope.date_from,
        status="active",
        origin="manual",
        created_by="u",
        created_at=_AT,
    )
