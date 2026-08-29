"""The Deduction Rulebook against the generated corpus.

The unit tests prove the algorithm; this proves the *rates in
``data/rules/deductions.yaml``* are the rates the merchant is actually charged,
which is a different claim and the one a demo rests on.

The gap here is the one the Rulebook is about, and it is not the cascade's. The
cascade reconciles a settlement against its own gateway rows, so it already
absorbs whatever fee was actually charged. The Rulebook answers the question the
books ask: sales were booked at gross, the bank paid the net, and *what happened
to the difference*.

Marked ``eval`` and excluded from the default run because it needs
``data/generated/``, which is gitignored. Regenerate with
``.\\scripts\\dev.ps1 generate -Seed 42 -N 500``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fc.config import load_config
from fc.eval.report import DATA_DIR, load_corpus
from fc.models.transaction import TransactionEvent
from fc.rules.apply import RuleOutcomeResult, apply_rules
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        not (DATA_DIR / "ground_truth.jsonl").exists(),
        reason="no generated corpus; run .\\scripts\\dev.ps1 generate",
    ),
]

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_MARKETPLACE = ("BLINKIT", "ZEPTO")
_SETTLEMENT_REF = re.compile(r"Settlement credit (\S+)")


@dataclass(frozen=True)
class Payout:
    """One marketplace payout as the books see it: gross out, net in."""

    settlement_id: str
    counterparty: str
    receipt: TransactionEvent
    gross_paise: int
    net_paise: int
    n_txns: int
    #: The receipt's generator label. Ground truth, used to pick out the
    #: scenarios under test - never to decide anything.
    gt_label: str | None
    gt_bucket: str

    @property
    def gap_paise(self) -> int:
        return self.gross_paise - self.net_paise

    @property
    def gap_percent(self) -> Decimal:
        return Decimal(self.gap_paise) * 100 / Decimal(self.gross_paise)


@pytest.fixture(scope="module")
def rules() -> tuple[object, ...]:
    return load_rules(DEFAULT_RULES_PATH, tenant_id="t_lumea", created_at=_AT).rules


@pytest.fixture(scope="module")
def payouts() -> tuple[Payout, ...]:
    corpus = load_corpus()
    gateway: dict[str, list[TransactionEvent]] = {}
    for event in corpus.events:
        if event.source == "razorpay" and event.settlement_id:
            gateway.setdefault(event.settlement_id, []).append(event)

    found: list[Payout] = []
    for event in corpus.events:
        if (
            event.source != "ledger"
            or event.voucher_type != "Receipt"
            or event.counterparty_norm not in _MARKETPLACE
        ):
            continue
        reference = _SETTLEMENT_REF.search(event.raw_narration or "")
        if reference is None:
            continue
        rows = [
            row
            for row in gateway.get(reference.group(1), ())
            if row.txn_type == "payment" and row.direction == "credit"
        ]
        if not rows:
            continue
        # The payment row's stored amount is already net of its own fee, so the
        # gross the commission was charged on is amount + fee (§6.1 / stage 2).
        found.append(
            Payout(
                settlement_id=reference.group(1),
                counterparty=event.counterparty_norm or "",
                receipt=event,
                gross_paise=sum(r.amount_paise + (r.fee_paise or 0) for r in rows),
                net_paise=event.amount_paise,
                n_txns=len(rows),
                gt_label=corpus.label.get((event.source, event.source_row_id)),
                gt_bucket=corpus.bucket.get((event.source, event.source_row_id), ""),
            )
        )
    return tuple(sorted(found, key=lambda p: p.settlement_id))


def _apply(rules: tuple[object, ...], payout: Payout) -> RuleOutcomeResult:
    return apply_rules(
        rules,  # type: ignore[arg-type]
        event=payout.receipt,
        on_date=payout.receipt.effective_date,
        gap_paise=payout.gap_paise,
        gross_paise=payout.gross_paise,
        n_txns=payout.n_txns,
        cfg=load_config(env_file=None, environ={}),
    )


def test_the_corpus_actually_contains_marketplace_payouts(payouts: tuple[Payout, ...]) -> None:
    """Guards the guard: an empty fixture would make every assertion below vacuous."""
    assert len(payouts) >= 20
    assert {p.counterparty for p in payouts} == set(_MARKETPLACE)


def test_the_shipped_rates_fully_explain_the_ordinary_payout(
    rules: tuple[object, ...], payouts: tuple[Payout, ...]
) -> None:
    """18% + 18% GST on it + 1% TDS is what Blinkit and Zepto actually charge."""
    outcomes = [_apply(rules, p) for p in payouts]
    fully = [o for o in outcomes if o.outcome == "fully_explained"]
    assert len(fully) >= 20
    assert all(o.may_auto_close for o in fully)
    assert not any(o.outcome == "not_applicable" for o in outcomes)


def test_a_platform_that_overcharged_leaves_a_shrunken_exception(
    rules: tuple[object, ...], payouts: tuple[Payout, ...]
) -> None:
    """Scenario 17: the platform took 20%, the rulebook says 18%.

    The whole feature in one assertion. The rule does not fail — it accounts for
    22.24% of the gross and hands the human the 2.36% it cannot account for, with
    its version hash attached.
    """
    overcharged = [p for p in payouts if p.gt_label == "amount_variance"]
    assert len(overcharged) == 2, "the corpus is expected to carry two scenario-17 payouts"

    for payout in overcharged:
        outcome = _apply(rules, payout)
        assert outcome.outcome == "partially_explained"
        assert not outcome.may_auto_close

        # The residual is the overcharge and nothing else: 2% more commission,
        # plus the 18% GST charged on that extra commission.
        expected_residual = _paise(payout.gross_paise * Decimal("0.0236"))
        assert abs(outcome.residual_paise - expected_residual) <= 2

        assert outcome.residual_paise < payout.gap_paise // 5  # shrunk by >80%
        assert outcome.applications[0].rule_id.endswith("_commission")
        assert len(outcome.applications[0].version_hash) == 64
        assert "unexplained after" in outcome.narrative()


def test_the_rulebook_accounts_for_over_95_per_cent_of_the_marketplace_gap(
    rules: tuple[object, ...], payouts: tuple[Payout, ...]
) -> None:
    """The number a controller cares about: how much is still unaccounted for.

    ₹49,407 of marketplace gap across 26 payouts becomes ₹688 the rulebook
    cannot account for — and that ₹688 is not noise, it is the overcharge and the
    mid-period rate change, which are exactly the things a human should see.
    """
    before = sum(p.gap_paise for p in payouts)
    after = sum(abs(_apply(rules, p).residual_paise) for p in payouts)
    assert before > 0
    assert after * 20 < before  # over 95% of the gap explained


def test_a_mid_period_rate_change_is_only_partly_explained_by_one_flat_rate(
    rules: tuple[object, ...], payouts: tuple[Payout, ...]
) -> None:
    """Scenario 18, reported honestly rather than papered over.

    A settlement whose orders straddle a rate change carries two rates, so its
    aggregate rate sits between them and no single-rate rule closes it. Effective
    dating resolves this correctly only when the rule is applied per order and
    the results summed — which is a pipeline decision, not an engine limitation
    (``fc.rules.scope`` already picks the right version per date; see
    ``test_june_replays_on_junes_rate_after_a_july_change``).

    Until that wiring exists these settlements shrink rather than close, which is
    the correct behaviour for something we cannot yet prove.
    """
    straddling = [p for p in payouts if p.gt_bucket == "rule_resolved"]
    assert straddling, "the corpus is expected to carry scenario-18 payouts"
    for payout in straddling:
        outcome = _apply(rules, payout)
        assert outcome.outcome == "partially_explained"
        assert abs(outcome.residual_paise) < payout.gap_paise // 5


def test_applying_the_rulebook_twice_gives_byte_identical_output(
    rules: tuple[object, ...], payouts: tuple[Payout, ...]
) -> None:
    """Hard rule 9, over the real corpus rather than a fixture."""
    first = [_apply(rules, p).model_dump_json() for p in payouts]
    second = [_apply(rules, p).model_dump_json() for p in payouts]
    assert first == second


def test_no_rule_raises_a_payouts_confidence(
    rules: tuple[object, ...], payouts: tuple[Payout, ...]
) -> None:
    """The ceiling, asserted over every case in the corpus rather than one."""
    prior = Decimal("0.9700")
    assert all(_apply(rules, p).confidence_after(prior) <= prior for p in payouts)


def _paise(value: Decimal) -> int:
    return int(value.quantize(Decimal(1)))
