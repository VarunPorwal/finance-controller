"""``would_wrongly_close`` is the point of the whole feature.

A wrong rule is worse than no rule: no rule leaves an exception in the queue
where a human eventually looks at it, and a wrong rule closes it with a
plausible arithmetic story attached. The back-test exists to put that number in
front of a person before they click activate, so the number has to be right when
the rule looks good — which is exactly the chargeback case below.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fc.config import load_config
from fc.models.rule import Deduction, Rule, Scope, Tolerance
from fc.models.transaction import TransactionEvent
from fc.rules.backtest import CaseTruth, HistoricalCase, backtest, render
from fc.rules.loader import version_hash

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_ON = date(2026, 6, 15)
_CFG = load_config(env_file=None, environ={})

_DEDUCTIONS = [
    Deduction(type="commission", basis="gross", rate=Decimal("18")),
    Deduction(type="gst_on_fee", basis="commission", rate=Decimal("18")),
    Deduction(type="tds_194o", basis="gross", rate=Decimal("1")),
]


def _rule(rate: Decimal = Decimal("18")) -> Rule:
    deductions = [
        Deduction(type="commission", basis="gross", rate=rate),
        Deduction(type="gst_on_fee", basis="commission", rate=Decimal("18")),
        Deduction(type="tds_194o", basis="gross", rate=Decimal("1")),
    ]
    scope = Scope(counterparty_matches=["BLINKIT"], date_from=date(2026, 4, 1))
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
        priority=200,
        effective_from=scope.date_from,
        status="draft",
        origin="manual",
        created_by="u",
        created_at=_AT,
    )


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


def _case(
    exception_id: str,
    gross: int,
    gap: int,
    *,
    category: str = "amount_variance",
    truth: CaseTruth | None = None,
    counterparty: str = "BLINKIT",
) -> HistoricalCase:
    return HistoricalCase(
        exception_id=exception_id,
        event=_event(f"e_{exception_id}", gross, counterparty=counterparty),
        on_date=_ON,
        gap_paise=gap,
        gross_paise=gross,
        category=category,  # type: ignore[arg-type]
        truth=truth,
    )


def _explained_case(exception_id: str, gross: int) -> HistoricalCase:
    """A case the 18% stack explains exactly: gap == 22.24% of gross."""
    gap = (
        (gross * 18 + 50) // 100
        + ((gross * 18 + 50) // 100 * 18 + 50) // 100
        + (gross * 1 + 50) // 100
    )
    return _case(
        exception_id,
        gross,
        gap,
        truth=CaseTruth(
            source="ground_truth",
            closable_by_rule=True,
            reason="platform commission on a weekly payout",
        ),
    )


# --- the number that matters ---------------------------------------------


def test_a_rule_that_would_close_a_chargeback_is_caught_with_its_reason() -> None:
    """The D4 headline. The arithmetic fits; the category says it must not close."""
    chargeback = _case(
        "exc_chargeback",
        gross=37_769_78,
        gap=8_400_00,
        category="chargeback_unrecorded",
    )
    # The rule genuinely explains this gap: 22.24% of ₹37,769.78 is ₹8,400.00.
    result = backtest(_rule(), [chargeback], cfg=_CFG)

    assert result.would_wrongly_close.count == 1
    assert result.would_wrongly_close.total_paise == 8_400_00
    assert result.would_wrongly_close.exception_ids == ("exc_chargeback",)
    assert result.net_recommendation == "discard"

    (why,) = result.wrong_closes
    assert why.category == "chargeback_unrecorded"
    assert why.evidence == "category"
    assert "disputed debit the ledger never recorded" in why.why
    assert "the rule accounts for ₹8,400.00 in full" in why.why


def test_one_wrong_close_discards_a_rule_that_would_explain_fourteen() -> None:
    """ "Closes 14 correctly, closes 1 chargeback wrongly" is not a trade we make."""
    cases = [_explained_case(f"exc_{i:02d}", 50_000_00 + i * 137_11) for i in range(14)]
    cases.append(_case("exc_bad", 37_769_78, 8_400_00, category="chargeback_unrecorded"))

    result = backtest(_rule(), cases, cfg=_CFG)
    assert result.would_explain.count == 14
    assert result.would_wrongly_close.count == 1
    assert result.net_recommendation == "discard"


def test_the_category_outranks_a_prior_human_resolution() -> None:
    """A human writing off one chargeback does not licence a rule to close the next."""
    case = _case(
        "exc_cb",
        37_769_78,
        8_400_00,
        category="chargeback_unrecorded",
        truth=CaseTruth(
            source="human_resolution",
            closable_by_rule=True,
            reason="written off last quarter",
        ),
    )
    result = backtest(_rule(), [case], cfg=_CFG)
    assert result.would_wrongly_close.count == 1
    assert result.wrong_closes[0].evidence == "category"


def test_a_prior_human_resolution_can_condemn_a_rule_on_its_own() -> None:
    """Ground truth is not always available; the merchant's own history is."""
    case = _case(
        "exc_h",
        50_000_00,
        11_120_00,
        truth=CaseTruth(
            source="human_resolution",
            closable_by_rule=False,
            reason="the platform reversed this in the next payout; it was never a fee",
            resolution_category="timing",
        ),
    )
    result = backtest(_rule(), [case], cfg=_CFG)
    assert result.would_wrongly_close.count == 1
    assert result.wrong_closes[0].evidence == "human_resolution"
    assert "reversed this in the next payout" in result.wrong_closes[0].why


# --- the other buckets ----------------------------------------------------


def test_a_clean_rule_is_recommended_for_activation() -> None:
    cases = [_explained_case(f"exc_{i:02d}", 40_000_00 + i * 999_37) for i in range(5)]
    result = backtest(_rule(), cases, cfg=_CFG)
    assert result.would_explain.count == 5
    assert result.would_wrongly_close.count == 0
    assert result.unverified == 0
    assert result.net_recommendation == "activate"


def test_a_partial_explanation_is_never_a_wrong_close() -> None:
    """It shrinks the exception; it does not close it, so it cannot close it wrongly."""
    partial = _case("exc_partial", 70_863_31, 19_000_00, category="chargeback_unrecorded")
    result = backtest(_rule(), [partial], cfg=_CFG)
    assert result.would_partially_explain.count == 1
    assert result.would_wrongly_close.count == 0
    assert result.net_recommendation == "adjust"


def test_a_rule_that_only_shrinks_is_recommended_for_adjustment() -> None:
    cases = [_case(f"exc_{i}", 70_863_31, 19_000_00) for i in range(3)]
    result = backtest(_rule(), cases, cfg=_CFG)
    assert result.would_explain.count == 0
    assert result.would_partially_explain.count == 3
    assert result.net_recommendation == "adjust"


def test_a_rule_nothing_is_in_scope_for_is_discarded() -> None:
    result = backtest(
        _rule(), [_case("exc_z", 50_000_00, 11_120_00, counterparty="ZEPTO")], cfg=_CFG
    )
    assert result.cases_considered == 1
    assert result.would_explain.count == 0
    assert result.would_partially_explain.count == 0
    assert result.net_recommendation == "discard"


def test_explanations_nothing_corroborates_are_counted_as_unverified() -> None:
    """ "14 explained" reads differently when 14 of them are unverified."""
    cases = [
        _case(f"exc_{i}", gross := 40_000_00 + i * 111_11, _stack_total(gross)) for i in range(3)
    ]
    result = backtest(_rule(), cases, cfg=_CFG)
    assert result.would_explain.count == 3
    assert result.unverified == 3
    assert result.net_recommendation == "activate"


def _stack_total(gross: int) -> int:
    commission = (gross * 18 + 50) // 100
    return commission + (commission * 18 + 50) // 100 + (gross * 1 + 50) // 100


# --- determinism and serialisation ---------------------------------------


def test_the_result_does_not_depend_on_the_order_cases_arrive_in() -> None:
    cases = [_explained_case(f"exc_{i:02d}", 40_000_00 + i * 999_37) for i in range(6)]
    forward = backtest(_rule(), cases, cfg=_CFG)
    backward = backtest(_rule(), list(reversed(cases)), cfg=_CFG)
    assert forward.to_json() == backward.to_json()


def test_the_result_serialises_for_the_backtest_result_column() -> None:
    cases = [_case("exc_cb", 37_769_78, 8_400_00, category="chargeback_unrecorded")]
    payload = backtest(_rule(), cases, cfg=_CFG).to_json()
    assert payload["net_recommendation"] == "discard"
    assert payload["would_wrongly_close"]["count"] == 1
    assert payload["would_wrongly_close"]["why"][0]["exception_id"] == "exc_cb"
    assert set(payload) == {
        "rule_id",
        "version",
        "version_hash",
        "would_explain",
        "would_wrongly_close",
        "would_partially_explain",
        "net_recommendation",
        "cases_considered",
        "unverified",
    }


def test_the_panel_renders_the_d4_shape() -> None:
    cases = [_explained_case(f"exc_{i:02d}", 40_000_00 + i * 999_37) for i in range(4)]
    cases.append(_case("exc_cb", 37_769_78, 8_400_00, category="chargeback_unrecorded"))
    text = render(backtest(_rule(), cases, cfg=_CFG))
    assert "Would have explained" in text
    assert "Would have wrongly closed" in text
    assert "exc_cb (chargeback_unrecorded, ₹8,400.00)" in text
    assert text.rstrip().endswith("-> DISCARD")
