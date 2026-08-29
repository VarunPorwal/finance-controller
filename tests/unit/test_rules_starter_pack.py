"""The shipped ``data/rules/deductions.yaml`` says what PRD §0.3 and §4.1.7 say.

The rates in this file are the merchant's real commercial terms. A typo here is
not a failing test somewhere, it is money silently mis-explained, so the rates
are asserted against the specification rather than against themselves.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from fc.models.rule import Rule
from fc.rules.evaluator import evaluate_deductions
from fc.rules.loader import DEFAULT_RULES_PATH, RuleSet, load_rules, version_hash

_AT = datetime(2026, 8, 29, tzinfo=UTC)

#: PRD §0.3: "MDR: UPI 0%, card 2%, netbanking 0.9%, wallet 1.8%, EMI 2.4%."
MDR_RATES = {
    "upi": Decimal("0"),
    "card": Decimal("2"),
    "netbanking": Decimal("0.9"),
    "wallet": Decimal("1.8"),
    "emi": Decimal("2.4"),
}


@pytest.fixture(scope="module")
def pack() -> RuleSet:
    return load_rules(DEFAULT_RULES_PATH, tenant_id="t_lumea", created_at=_AT)


def test_the_starter_pack_loads(pack: RuleSet) -> None:
    """13 rows: 5 razorpay_mdr_* rules x 2 versions (a retired v1 that bundled
    TDS into a per-transaction stack, and the corrected v2), one batch-level
    TDS rule, and the two marketplace commission rules."""
    assert len(pack.rules) == 13
    assert all(rule.origin == "manual" for rule in pack.rules)
    active = [r for r in pack.rules if r.status == "active"]
    retired = [r for r in pack.rules if r.status == "retired"]
    assert len(retired) == 5
    assert {r.rule_id for r in retired} == {f"razorpay_mdr_{m}" for m in MDR_RATES}
    assert all(r.version == 1 for r in retired)
    assert len(active) == 8


def _active_mdr_rule(pack: RuleSet, method: str) -> Rule:
    """The live version of one method's MDR rule — never the retired v1,
    which a plain ``rule_id`` lookup would also return now that both
    versions ship in the same file."""
    (rule,) = [
        r for r in pack.rules if r.rule_id == f"razorpay_mdr_{method}" and r.status == "active"
    ]
    return rule


@pytest.mark.parametrize("method,rate", sorted(MDR_RATES.items()))
def test_mdr_by_method_matches_the_merchant_profile(
    pack: RuleSet, method: str, rate: Decimal
) -> None:
    rule = _active_mdr_rule(pack, method)
    assert rule.version == 2
    assert rule.scope.method == method
    assert rule.scope.source == "razorpay"
    stack = {d.type: d for d in rule.deductions}
    assert stack["mdr"].rate == rate
    assert stack["mdr"].basis == "gross"
    assert stack["gst_on_fee"].rate == Decimal("18")
    assert stack["gst_on_fee"].basis == "mdr"  # on the MDR, not on the sale
    # TDS 194-O is not here: it is batch-level, not per-transaction (see
    # razorpay_tds_batch) — bundling it into a per-row rule is exactly what
    # made version 1 wrong.
    assert "tds_194o" not in stack


@pytest.mark.parametrize("method", sorted(MDR_RATES))
def test_the_retired_mdr_version_is_the_one_that_bundled_tds(pack: RuleSet, method: str) -> None:
    (retired,) = [
        r for r in pack.rules if r.rule_id == f"razorpay_mdr_{method}" and r.status == "retired"
    ]
    assert retired.version == 1
    assert {d.type for d in retired.deductions} == {"mdr", "gst_on_fee", "tds_194o"}
    assert retired.effective_to is not None
    active = _active_mdr_rule(pack, method)
    assert retired.effective_to < active.effective_from


def test_the_batch_tds_rule_is_statutory_and_settlement_scoped(pack: RuleSet) -> None:
    (rule,) = pack.by_id("razorpay_tds_batch")
    assert rule.status == "active"
    assert rule.scope.method is None  # applies regardless of how the batch was paid
    assert rule.scope.counterparty_matches is None  # caller excludes marketplace, not scope
    assert [(d.type, d.basis, d.rate) for d in rule.deductions] == [
        ("tds_194o", "gross", Decimal("1")),
    ]


@pytest.mark.parametrize("rule_id", ["blinkit_commission", "zepto_commission"])
def test_the_marketplace_rules_carry_the_quick_commerce_terms(pack: RuleSet, rule_id: str) -> None:
    """§0.3: platform commission 18%, GST 18% on commission, TDS 194-O 1%."""
    (rule,) = pack.by_id(rule_id)
    assert [(d.type, d.basis, d.rate) for d in rule.deductions] == [
        ("commission", "gross", Decimal("18")),
        ("gst_on_fee", "commission", Decimal("18")),
        ("tds_194o", "gross", Decimal("1")),
    ]
    assert rule.scope.counterparty_matches == [rule_id.split("_")[0].upper()]
    assert rule.priority > 100  # a platform's own terms beat the generic MDR rules


def test_the_marketplace_rules_absorb_per_order_rounding(pack: RuleSet) -> None:
    """The platform rounds per order; a rate on the batch total misses by paise."""
    (blinkit,) = pack.by_id("blinkit_commission")
    card = _active_mdr_rule(pack, "card")
    assert blinkit.tolerance.absolute_paise > card.tolerance.absolute_paise


def test_the_blinkit_stack_reproduces_the_prd_example_to_the_paise(pack: RuleSet) -> None:
    """§6.7: a ₹19,000 gap, ₹15,760 explained, ₹3,240 left.

    The gross is chosen so the shipped rates land on the PRD's own figures
    exactly. Nothing here is rounded to make it fit — 18% of ₹70,863.31 is
    ₹12,755.40, 18% of that is ₹2,295.97, 1% of the gross is ₹708.63, and those
    three sum to ₹15,760.00.
    """
    (blinkit,) = pack.by_id("blinkit_commission")
    stack = evaluate_deductions(blinkit.deductions, 70_863_31)
    assert stack.total_paise == 15_760_00
    assert [item.amount_paise for item in stack.items] == [12_755_40, 2_295_97, 708_63]
    assert 19_000_00 - stack.total_paise == 3_240_00


def test_the_marketplace_and_tds_batch_rules_are_effective_from_the_fiscal_year(
    pack: RuleSet,
) -> None:
    """Which is also what makes a 15 March transaction out of scope for them.

    The ``razorpay_mdr_*`` rules are excluded here on purpose: their retired
    v1 and corrected v2 straddle a mid-year cutover (the TDS-bundling fix),
    so "everything starts 1 April" is no longer true of the whole pack — see
    ``test_the_retired_mdr_version_is_the_one_that_bundled_tds`` for their
    actual windows.
    """
    undated_rules = [r for r in pack.rules if not r.rule_id.startswith("razorpay_mdr_")]
    assert undated_rules  # guards the guard
    assert {rule.effective_from for rule in undated_rules} == {date(2026, 4, 1)}
    assert all(rule.effective_to is None for rule in undated_rules)


def test_no_rule_deducts_more_than_the_gross(pack: RuleSet) -> None:
    for rule in pack.rules:
        assert not evaluate_deductions(rule.deductions, 1_00_000_00).exceeds_gross


def test_every_shipped_hash_is_reproducible_from_the_rule(pack: RuleSet) -> None:
    for rule in pack.rules:
        assert rule.version_hash == version_hash(rule.scope, rule.deductions, rule.tolerance)


def test_the_shipped_hashes_are_stable(pack: RuleSet) -> None:
    """A ratchet. If one of these moves, a rate moved — say so in the commit.

    Pinned because the hash is the provenance stamp on every exception the rule
    closes, and a hash that drifts silently makes the audit trail unreadable
    across runs.
    """
    # Keyed by (rule_id, version): rule_id alone is no longer unique now that
    # razorpay_mdr_* ships a retired v1 alongside its corrected v2.
    assert {(rule.rule_id, rule.version): rule.version_hash[:16] for rule in pack.rules} == {
        ("razorpay_mdr_card", 1): "e6b6860c5a42b412",
        ("razorpay_mdr_card", 2): "b696a60038fd509f",
        ("razorpay_mdr_netbanking", 1): "f7c1243071ebbbbd",
        ("razorpay_mdr_netbanking", 2): "6b0bdcf71a739209",
        ("razorpay_mdr_upi", 1): "159d8aa59984d518",
        ("razorpay_mdr_upi", 2): "d81ce2ccba4b6744",
        ("razorpay_mdr_wallet", 1): "96b0fb7300e6c09b",
        ("razorpay_mdr_wallet", 2): "21570e26f6688c4f",
        ("razorpay_mdr_emi", 1): "5dca07cf84d7cb2d",
        ("razorpay_mdr_emi", 2): "50a560be6d6aa91f",
        ("razorpay_tds_batch", 1): "ee905986f025650b",
        ("blinkit_commission", 3): "5a4fc8c4b8e9005a",
        ("zepto_commission", 1): "a6760c36c87c6e6c",
    }
    assert pack.ruleset_hash.startswith("1cb86391f7a1b7d5")


def test_the_pack_is_free_of_duplicate_ids(pack: RuleSet) -> None:
    keys = [(rule.rule_id, rule.version) for rule in pack.rules]
    assert len(keys) == len(set(keys))


def test_loading_the_pack_twice_gives_identical_rules(pack: RuleSet) -> None:
    again = load_rules(DEFAULT_RULES_PATH, tenant_id="t_lumea", created_at=_AT)
    assert _dump(pack.rules) == _dump(again.rules)


def _dump(rules: tuple[Rule, ...]) -> list[str]:
    return [rule.model_dump_json() for rule in rules]
