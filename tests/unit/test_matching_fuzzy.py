"""Stage 5 scores resemblance, caps at 0.75, and never closes anything.

The cap is the point. Everything above stage 5 matched on something it could
prove; this stage matches on similarity, so its output is a ranked suggestion for
a human and never a decision. The tests here pin that structurally rather than by
convention: a fuzzy match above the cap cannot be constructed, and an auto-closed
group carrying a fuzzy leg cannot be constructed either.

The renormalisation is the other thing worth defending. Two of §6.3's five
features are undefined for whole classes of pair because of how the sources are
shaped, not because the data is bad, and scoring them as zero would punish a pair
for a schema fact.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fc.config import Config, load_config
from fc.matching.cascade import _extend, run_cascade
from fc.matching.stages import StageMatch
from fc.matching.stages.fuzzy import (
    IDENTIFYING_FEATURES,
    MIN_DEFINED_WEIGHT,
    WEIGHTS,
    jaro_winkler,
    score_pair,
)
from fc.models.ids import deterministic_factory
from fc.models.match import (
    FUZZY_CONFIDENCE_CAP,
    MatchEvidence,
    MatchResult,
    group_confidence_cap,
)
from fc.models.transaction import Direction, Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)


def _cfg(**overrides: object) -> Config:
    return load_config(env_file=None, environ={}).model_copy(update=overrides)


def _event(
    event_id: str,
    *,
    source: Source,
    amount: int,
    day: int = 5,
    direction: Direction = "credit",
    utr: str | None = None,
    order_id: str | None = None,
    counterparty_norm: str | None = None,
    method: str | None = None,
    rail: str | None = None,
    narration: str | None = None,
) -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t",
        source=source,
        source_row_id=event_id,
        amount_paise=amount,
        direction=direction,
        txn_date=date(2026, 6, day),
        utr=utr,
        order_id=order_id,
        counterparty_norm=counterparty_norm,
        method=method,
        rail=rail,
        raw_narration=narration,
        raw={},
        ingested_at=_AT,
    )


def test_the_weights_are_the_prd_weights_and_sum_to_one() -> None:
    assert WEIGHTS == {
        "amount_proximity": Decimal("0.35"),
        "date_proximity": Decimal("0.20"),
        "reference_similarity": Decimal("0.25"),
        "counterparty_similarity": Decimal("0.15"),
        "method_agreement": Decimal("0.05"),
    }
    assert sum(WEIGHTS.values()) == Decimal("1.00")


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ("MARTHA", "MARHTA", Decimal("0.9611")),
        ("DIXON", "DICKSONX", Decimal("0.8133")),
        ("JELLYFISH", "SMELLYFISH", Decimal("0.8963")),
    ],
)
def test_jaro_winkler_matches_the_published_values(
    left: str, right: str, expected: Decimal
) -> None:
    """Hand-written because the stack is fixed; pinned against known values so a
    subtle transposition bug cannot hide behind plausible-looking numbers."""
    assert jaro_winkler(left, right) == expected


def test_jaro_winkler_edges() -> None:
    assert jaro_winkler("ABC", "ABC") == Decimal(1)
    assert jaro_winkler("", "") == Decimal(0)
    assert jaro_winkler("ABC", "") == Decimal(0)
    assert jaro_winkler("ABC", "XYZ") == Decimal(0)


def test_every_feature_and_the_score_are_decimal() -> None:
    """Hard rule 1 reaches the score too: a float here would make "same seed,
    byte-identical output" false in the fourth decimal."""
    scored = score_pair(
        _event("g", source="razorpay", amount=10_000, method="card", order_id="HDFC261560000000"),
        _event("b", source="bank", amount=10_000, rail="neft", utr="HDFC261560000000"),
    )
    assert scored is not None
    assert isinstance(scored.score, Decimal)
    for feature in scored.features:
        assert feature.value is None or isinstance(feature.value, Decimal)


def test_the_score_renormalises_over_defined_features_only() -> None:
    """A gateway row carries no counterparty, so that feature is undefined for
    every gateway-bank pair. Scoring it zero would cap the pair at 0.85 of the
    weight before any evidence was read."""
    scored = score_pair(
        _event("g", source="razorpay", amount=10_000, method="card", order_id="order_A"),
        _event("b", source="bank", amount=10_000, rail="neft", utr="order_A"),
    )
    assert scored is not None
    undefined = {f.name for f in scored.features if f.value is None}
    assert undefined == {"counterparty_similarity"}
    assert scored.defined_weight == Decimal("0.85")
    # Every defined feature is perfect here, so renormalisation must give 1.0
    # rather than 0.85.
    assert scored.score == Decimal("1.0000")


def test_amount_and_date_alone_are_not_enough_to_score_on() -> None:
    """The scenario 16 shape: same amount, same day, different orders.

    Both features are perfect, so a plain weighted sum would renormalise them to
    1.0 and match two unrelated rows on a coincidence of size and timing - which
    is exactly what blocking selected these two for in the first place. An
    identifying feature has to be present before the number means anything.
    """
    scored = score_pair(
        _event("l", source="ledger", amount=10_000),
        _event("g", source="razorpay", amount=10_000),
    )
    assert scored is None
    assert MIN_DEFINED_WEIGHT == Decimal("0.55")
    assert IDENTIFYING_FEATURES == {"reference_similarity", "counterparty_similarity"}


def test_incompatible_rails_score_zero_rather_than_undefined() -> None:
    """A UPI payment cannot settle over NACH. That is evidence against the pair,
    not absence of evidence, so it scores 0 and drags the total down."""
    agree = score_pair(
        _event("g", source="razorpay", amount=10_000, method="upi", order_id="X"),
        _event("b", source="bank", amount=10_000, rail="upi", utr="X"),
    )
    disagree = score_pair(
        _event("g", source="razorpay", amount=10_000, method="upi", order_id="X"),
        _event("b", source="bank", amount=10_000, rail="nach", utr="X"),
    )
    assert agree is not None and disagree is not None
    method_of = lambda s: next(f.value for f in s.features if f.name == "method_agreement")  # noqa: E731
    assert method_of(agree) == Decimal(1)
    assert method_of(disagree) == Decimal(0)
    assert disagree.score < agree.score


def test_date_proximity_reaches_zero_at_seven_days() -> None:
    near = score_pair(
        _event("g", source="razorpay", amount=10_000, day=5, method="card", order_id="X"),
        _event("b", source="bank", amount=10_000, day=5, rail="neft", utr="X"),
    )
    far = score_pair(
        _event("g", source="razorpay", amount=10_000, day=5, method="card", order_id="X"),
        _event("b", source="bank", amount=10_000, day=12, rail="neft", utr="X"),
    )
    assert near is not None and far is not None
    date_of = lambda s: next(f.value for f in s.features if f.name == "date_proximity")  # noqa: E731
    assert date_of(near) == Decimal(1)
    assert date_of(far) == Decimal(0)


def test_a_fuzzy_match_above_the_cap_cannot_be_constructed() -> None:
    """The cap is a property of the type, not a discipline at the call site.

    ``fc/matching/`` is not the only place a ``MatchResult`` can be built, and a
    hard cap that depends on every future construction site remembering to call a
    helper is not a hard cap.
    """
    evidence = MatchEvidence(stage="fuzzy")
    with pytest.raises(ValueError, match="exceeds the .6.3 cap"):
        MatchResult(
            match_id="m",
            run_id="r",
            tenant_id="t",
            group_key="g",
            event_ids=["a", "b"],
            sources_covered=["bank", "razorpay"],
            stage="fuzzy",
            confidence=Decimal("0.90"),
            evidence=[evidence],
            created_at=_AT,
        )


def test_an_auto_closed_group_cannot_carry_a_fuzzy_leg() -> None:
    """The weakest-leg rule, enforced by the model.

    This is the hole that the old ``_extend`` left open: a fuzzy row attaching to
    an ``exact_ref`` group inherited the host's auto-closability and closed at
    high confidence with an unproven member inside.
    """
    # Confidence is already at the group cap, so this isolates the auto-close
    # rule rather than tripping the ceiling on the way past it.
    with pytest.raises(ValueError, match="may not"):
        MatchResult(
            match_id="m",
            run_id="r",
            tenant_id="t",
            group_key="g",
            event_ids=["a", "b"],
            sources_covered=["bank", "razorpay"],
            stage="exact_ref",
            confidence=FUZZY_CONFIDENCE_CAP,
            evidence=[MatchEvidence(stage="exact_ref"), MatchEvidence(stage="fuzzy")],
            auto_closed=True,
            created_at=_AT,
        )


def test_a_group_holding_a_fuzzy_leg_cannot_exceed_the_fuzzy_cap() -> None:
    """The cap is a group-level property, so it reads every leg.

    Enforcing it against ``self.stage`` alone would let an ``exact_ref`` group
    that a fuzzy leg extended be capped at 1.0 instead of 0.75 - and a group that
    closes at 1.0 with an unproven leg inside it is a false auto-resolution the
    pairwise metric scores as correct.
    """
    legs = [MatchEvidence(stage="exact_ref"), MatchEvidence(stage="fuzzy")]
    assert group_confidence_cap(legs) == FUZZY_CONFIDENCE_CAP
    assert group_confidence_cap([MatchEvidence(stage="exact_ref")]) == Decimal(1)

    with pytest.raises(ValueError, match="weakest leg"):
        MatchResult(
            match_id="m",
            run_id="r",
            tenant_id="t",
            group_key="g",
            event_ids=["a", "b"],
            sources_covered=["bank", "razorpay"],
            stage="exact_ref",
            confidence=Decimal("1.0"),
            evidence=legs,
            created_at=_AT,
        )


def _exact_ref_group_extended_by_a_fuzzy_leg() -> object:
    """An ``exact_ref`` group that a fuzzy leg is attached to.

    Gateway and bank join on a shared UTR at stage 1, so the group forms at
    confidence 1.0. The ledger row carries no reference at all, so the only thing
    that can attach it is three-way's amount-and-date path - which is a *fuzzy*
    attribution and is stamped as one. That is the multi-leg group the cap and
    the auto-close rule both have to survive.
    """
    utr = "HDFC261560000000"
    return run_cascade(
        [
            _event("bank", source="bank", amount=100_000, utr=utr, narration=f"NEFT CR:{utr}"),
            _event("pay", source="razorpay", amount=100_000, utr=utr, method="card"),
            _event("led", source="ledger", amount=100_000, direction="debit"),
        ],
        cfg=_cfg(),
        run_id="run",
        tenant_id="t",
        issue_id=deterministic_factory(seed=1, epoch_ms=1_780_000_000_000),
        created_at=_AT,
    )


def test_a_fuzzy_leg_caps_and_opens_the_exact_ref_group_it_joins() -> None:
    """The bug this file is named after, built explicitly.

    A single-stage group cannot exercise it: the cap and the auto-close rule only
    diverge from the host's stage when a *second*, weaker leg is present. Both
    properties are asserted, because getting one right and the other wrong is
    exactly how this went unnoticed the first time - the group would still refuse
    to close while quietly reporting confidence 1.0.
    """
    result = _exact_ref_group_extended_by_a_fuzzy_leg()
    group = next(m for m in result.matches if "led" in m.event_ids)

    assert [leg.stage for leg in group.evidence] == ["exact_ref", "fuzzy"]
    assert group.stage == "exact_ref"  # the host label; deliberately not the rule
    assert group.confidence == FUZZY_CONFIDENCE_CAP
    assert not group.auto_closed


def test_that_group_stays_capped_and_open_at_a_zero_threshold() -> None:
    """Removes the confidence threshold, leaving only the weakest-leg rule.

    Without this, the assertions above would still pass on a build where the cap
    was wrong, because 1.0 also clears 0.94 and the *auto-close* half happens to
    be enforced separately.
    """
    utr = "HDFC261560000000"
    result = run_cascade(
        [
            _event("bank", source="bank", amount=100_000, utr=utr, narration=f"NEFT CR:{utr}"),
            _event("pay", source="razorpay", amount=100_000, utr=utr, method="card"),
            _event("led", source="ledger", amount=100_000, direction="debit"),
        ],
        cfg=_cfg(auto_threshold=Decimal(0)),
        run_id="run",
        tenant_id="t",
        issue_id=deterministic_factory(seed=1, epoch_ms=1_780_000_000_000),
        created_at=_AT,
    )
    group = next(m for m in result.matches if "led" in m.event_ids)
    assert group.confidence == FUZZY_CONFIDENCE_CAP
    assert not group.auto_closed


def test_extending_a_group_with_a_fuzzy_leg_caps_and_opens_it() -> None:
    """The ``_extend`` path, pinned directly.

    Stage 5 cannot currently reach this: it names no anchors, so every member of
    a fuzzy match is "newly decided" and the cascade skips the match outright if
    any of them is already claimed. Today only three-way attaches a fuzzy leg to
    an existing group. The rule is asserted at the function anyway, because
    "unreachable" is a property of this month's stage list, not of ``_extend`` -
    the moment a stage sets anchors and scores fuzzily, this is live.
    """
    host = MatchResult(
        match_id="m",
        run_id="r",
        tenant_id="t",
        group_key="g",
        event_ids=["bank", "pay"],
        sources_covered=["bank", "razorpay"],
        stage="exact_ref",
        confidence=Decimal("1.0"),
        evidence=[MatchEvidence(stage="exact_ref")],
        auto_closed=True,
        created_at=_AT,
    )
    members = {
        "bank": _event("bank", source="bank", amount=100_000),
        "pay": _event("pay", source="razorpay", amount=100_000),
        "led": _event("led", source="ledger", amount=100_000, direction="debit"),
    }
    leg = StageMatch(
        stage="fuzzy",
        group_key="fuzzy:led",
        event_ids=("bank", "pay", "led"),
        base_confidence=Decimal("1.0"),
        anchors=("led",),
    )

    extended, _ = _extend(host, leg, by_id=members, cfg=_cfg(auto_threshold=Decimal(0)))
    assert [e.stage for e in extended.evidence] == ["exact_ref", "fuzzy"]
    assert extended.confidence == FUZZY_CONFIDENCE_CAP
    assert not extended.auto_closed


@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
@given(
    amounts=st.lists(st.integers(min_value=1, max_value=5_00_000), min_size=0, max_size=8),
    days=st.lists(st.integers(min_value=1, max_value=20), min_size=0, max_size=8),
)
def test_no_group_holding_a_fuzzy_leg_ever_closes_or_exceeds_the_cap(
    amounts: list[int], days: list[int]
) -> None:
    """PRD §12.3, strengthened twice over.

    The PRD's version filters ``m.stage == "fuzzy"``, which cannot see a fuzzy
    leg inside a group another stage formed - ``MatchResult.stage`` stays the
    host's. This asks the *evidence*, and checks the cap as well as the close.

    Breadth only: the explicit multi-leg cases above are what actually pin the
    rule, because this strategy mostly generates single-stage groups.
    """
    events: list[TransactionEvent] = []
    for i, amount in enumerate(amounts):
        day = 1 + (days[i] if i < len(days) else 1) % 20
        utr = f"HDFC2615600000{i:02d}"
        events.append(
            _event(f"g{i}", source="razorpay", amount=amount, day=day, utr=utr, method="card")
        )
        events.append(_event(f"b{i}", source="bank", amount=amount, day=day, utr=utr, rail="neft"))
        events.append(_event(f"l{i}", source="ledger", amount=amount, day=day, direction="debit"))

    result = run_cascade(
        events,
        cfg=_cfg(),
        run_id="run",
        tenant_id="t",
        issue_id=deterministic_factory(seed=1, epoch_ms=1_780_000_000_000),
        created_at=_AT,
    )
    for match in result.matches:
        assert 0 <= match.confidence <= 1
        assert match.confidence <= group_confidence_cap(match.evidence)
        if any(leg.stage == "fuzzy" for leg in match.evidence):
            assert not match.auto_closed
            assert match.confidence <= FUZZY_CONFIDENCE_CAP
