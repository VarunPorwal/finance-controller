"""Scope matching, effective dating, and the order candidates are tried in.

Effective dating is the one a demo skips and an accountant does not. A June
reconciliation replays against June's rates after a July rate change, and a rule
effective from 1 April has nothing to say about a 15 March transaction — however
well its arithmetic happens to fit.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fc.ingest.aliases import load_aliases
from fc.models.rule import Deduction, Rule, Scope, Tolerance
from fc.models.transaction import Source, TransactionEvent
from fc.rules.loader import version_hash
from fc.rules.scope import candidates, effective_on, scope_matches

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_TOLERANCE = Tolerance(absolute_paise=100, percent=Decimal("0.05"))
_DEDUCTIONS = [Deduction(type="commission", basis="gross", rate=Decimal("18"))]


def _rule(
    rule_id: str = "r",
    *,
    version: int = 1,
    priority: int = 100,
    status: str = "active",
    effective_to: date | None = None,
    **scope_kwargs: object,
) -> Rule:
    # date_to mirrors effective_to, which is the invariant the loader enforces:
    # a rule has one effective window, written in two places.
    scope = Scope(date_from=date(2026, 4, 1), date_to=effective_to, **scope_kwargs)  # type: ignore[arg-type]
    return Rule(
        rule_id=rule_id,
        version=version,
        tenant_id="t",
        version_hash=version_hash(scope, _DEDUCTIONS, _TOLERANCE),
        name=rule_id,
        scope=scope,
        deductions=_DEDUCTIONS,
        tolerance=_TOLERANCE,
        priority=priority,
        effective_from=scope.date_from,
        effective_to=effective_to,
        status=status,  # type: ignore[arg-type]
        origin="manual",
        created_by="u",
        created_at=_AT,
    )


def _event(
    *,
    source: Source = "bank",
    amount: int = 1_00_000_00,
    txn_date: date = date(2026, 6, 15),
    value_date: date | None = None,
    counterparty: str | None = None,
    counterparty_norm: str | None = None,
    method: str | None = None,
    rail: str | None = None,
    narration: str | None = None,
) -> TransactionEvent:
    return TransactionEvent(
        event_id="e1",
        run_id="run",
        tenant_id="t",
        source=source,
        source_row_id="e1",
        amount_paise=amount,
        direction="credit",
        txn_date=txn_date,
        value_date=value_date,
        counterparty=counterparty,
        counterparty_norm=counterparty_norm,
        method=method,
        rail=rail,
        raw_narration=narration,
        raw={},
        ingested_at=_AT,
    )


# --- effective dating -----------------------------------------------------


def test_a_rule_effective_from_1_april_does_not_apply_on_15_march() -> None:
    rule = _rule()
    assert not effective_on(rule, date(2026, 3, 15))
    assert not scope_matches(rule, _event(txn_date=date(2026, 3, 15)), date(2026, 3, 15))


def test_a_rule_applies_on_its_own_first_day() -> None:
    assert effective_on(_rule(), date(2026, 4, 1))


def test_a_retired_window_closes_on_its_last_day_inclusive() -> None:
    rule = _rule(effective_to=date(2026, 6, 30))
    assert effective_on(rule, date(2026, 6, 30))
    assert not effective_on(rule, date(2026, 7, 1))


def test_june_replays_on_junes_rate_after_a_july_change() -> None:
    """The whole point of versioning rather than editing."""
    june = _rule("commission", version=1, effective_to=date(2026, 6, 30))
    july = _rule("commission", version=2)
    july = july.model_copy(update={"effective_from": date(2026, 7, 1)})
    event = _event(counterparty_norm="BLINKIT")

    on_june = candidates([june, july], event, date(2026, 6, 15))
    on_july = candidates([june, july], event, date(2026, 7, 15))
    assert [r.version for r in on_june] == [1]
    assert [r.version for r in on_july] == [2]


def test_the_as_at_date_is_the_callers_not_the_events() -> None:
    """A replay of June run in August still closes June's books."""
    rule = _rule(effective_to=date(2026, 6, 30))
    event = _event(txn_date=date(2026, 6, 15))
    assert scope_matches(rule, event, date(2026, 6, 20))
    assert not scope_matches(rule, event, date(2026, 8, 29))


# --- clauses --------------------------------------------------------------


def test_an_empty_scope_matches_anything_inside_its_window() -> None:
    assert scope_matches(_rule(), _event(), date(2026, 6, 15))


def test_counterparty_matching_is_case_insensitive_and_normalised() -> None:
    rule = _rule(counterparty_matches=["blinkit"])
    assert scope_matches(rule, _event(counterparty_norm="BLINKIT"), date(2026, 6, 15))
    assert not scope_matches(rule, _event(counterparty_norm="ZEPTO"), date(2026, 6, 15))


def test_counterparty_matching_goes_through_the_alias_table() -> None:
    """A rule saying Blinkit must match a row ingested as BLNKT/SETTL."""
    aliases = load_aliases()
    rule = _rule(counterparty_matches=["Blinkit"])
    event = _event(counterparty="BLNKT/SETTL")
    assert scope_matches(rule, event, date(2026, 6, 15), aliases=aliases)
    assert not scope_matches(rule, event, date(2026, 6, 15))


def test_an_event_with_no_counterparty_never_matches_a_counterparty_clause() -> None:
    rule = _rule(counterparty_matches=["BLINKIT"])
    assert not scope_matches(rule, _event(), date(2026, 6, 15))


def test_narration_matching_is_a_case_insensitive_substring() -> None:
    rule = _rule(narration_contains=["rolling reserve"])
    assert scope_matches(
        rule, _event(narration="NEFT-ROLLING RESERVE RELEASE-SETL"), date(2026, 6, 15)
    )
    assert not scope_matches(rule, _event(narration="NEFT-SETTLEMENT"), date(2026, 6, 15))


def test_source_method_and_rail_each_constrain() -> None:
    on_date = date(2026, 6, 15)
    assert not scope_matches(_rule(source="razorpay"), _event(source="bank"), on_date)
    assert not scope_matches(_rule(method="card"), _event(method="upi"), on_date)
    assert not scope_matches(_rule(rail="neft"), _event(rail="upi"), on_date)
    assert scope_matches(
        _rule(source="razorpay", method="card", rail="neft"),
        _event(source="razorpay", method="card", rail="neft"),
        on_date,
    )


def test_a_method_clause_never_matches_a_row_that_has_no_method() -> None:
    """A bank credit carries no method; a per-method MDR rule is not about it."""
    assert not scope_matches(_rule(method="card"), _event(method=None), date(2026, 6, 15))


def test_the_amount_range_is_inclusive_at_both_ends() -> None:
    rule = _rule(amount_min_paise=1_000_00, amount_max_paise=10_000_00)
    on_date = date(2026, 6, 15)
    assert scope_matches(rule, _event(amount=1_000_00), on_date)
    assert scope_matches(rule, _event(amount=10_000_00), on_date)
    assert not scope_matches(rule, _event(amount=999_99), on_date)
    assert not scope_matches(rule, _event(amount=10_000_01), on_date)


def test_the_amount_range_reads_a_debit_as_a_magnitude() -> None:
    rule = _rule(amount_min_paise=1_000_00)
    assert scope_matches(rule, _event(amount=-5_000_00), date(2026, 6, 15))


def test_the_scope_window_is_checked_against_the_events_effective_date() -> None:
    """Value date is what matching blocks on, so it is what scoping reads too."""
    rule = _rule(effective_to=date(2026, 6, 30))
    late = _event(txn_date=date(2026, 6, 29), value_date=date(2026, 7, 2))
    assert not scope_matches(rule, late, date(2026, 6, 30))


# --- candidate ordering ---------------------------------------------------


def test_drafts_are_not_candidates() -> None:
    """A learned draft has no path to closing anything until a human activates it."""
    draft = _rule("draft_rule", status="draft")
    assert candidates([draft], _event(), date(2026, 6, 15)) == ()
    assert candidates([draft], _event(), date(2026, 6, 15), include_inactive=True) == (draft,)


def test_retired_rules_are_not_candidates() -> None:
    assert candidates([_rule(status="retired")], _event(), date(2026, 6, 15)) == ()


def test_priority_beats_specificity() -> None:
    generic = _rule("generic", priority=200)
    specific = _rule("specific", priority=100, counterparty_matches=["BLINKIT"], method=None)
    ordered = candidates(
        [specific, generic], _event(counterparty_norm="BLINKIT"), date(2026, 6, 15)
    )
    assert [r.rule_id for r in ordered] == ["generic", "specific"]


def test_specificity_breaks_a_priority_tie() -> None:
    generic = _rule("generic")
    specific = _rule("specific", counterparty_matches=["BLINKIT"])
    ordered = candidates(
        [generic, specific], _event(counterparty_norm="BLINKIT"), date(2026, 6, 15)
    )
    assert [r.rule_id for r in ordered] == ["specific", "generic"]


def test_a_higher_version_wins_a_specificity_tie() -> None:
    ordered = candidates(
        [_rule("r", version=1), _rule("r", version=4)], _event(), date(2026, 6, 15)
    )
    assert [r.version for r in ordered] == [4, 1]


def test_candidate_order_does_not_depend_on_the_callers_iteration_order() -> None:
    """Determinism: same rules, any order in, one order out (hard rule 9)."""
    rules = [_rule(f"r{i}") for i in range(6)]
    forward = candidates(rules, _event(), date(2026, 6, 15))
    backward = candidates(list(reversed(rules)), _event(), date(2026, 6, 15))
    assert [r.rule_id for r in forward] == [r.rule_id for r in backward]
