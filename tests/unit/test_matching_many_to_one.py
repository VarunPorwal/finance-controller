"""Stage 4 decomposes a lumped credit, and refuses when it cannot tell.

The properties defended here are the two §6.3 calls out as the ones that matter:
the ``MAX_SUBSET_N`` cap stops the search exploding, and **several valid subsets
produce an exception rather than a coin flip**. A matcher that picks one is
guessing while appearing certain, which is the failure this project exists to
avoid.

Also pinned: the grouped/ungrouped auto-close split, which until this prompt was
held in place only by ``auto_threshold`` (0.94) happening to sit above the DP
path's base confidence (0.88). ``test_the_dp_path_never_auto_closes_even_at_a_zero_threshold``
is what turns that from an arithmetic coincidence into a rule.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from decimal import Decimal

from fc.config import Config, load_config
from fc.matching.cascade import run_cascade
from fc.matching.stages.many_to_one import (
    SUBSET_STEP_BUDGET,
    bounded_subset_sum,
    find_matches,
    settlement_net_paise,
    signed_net_paise,
)
from fc.models.ids import deterministic_factory
from fc.models.transaction import Direction, Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)
_SETL = "setl_01KT07NVH5KTVYN9PVWMBFQW16"
_OTHER_SETL = "setl_01KT07NVH5KTVYN9PVWMBFQW17"
_UTR = "HDFC261560000000"


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
    settlement_id: str | None = None,
    narration: str | None = None,
    fee: int | None = None,
    tax: int | None = None,
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
        rail="neft" if source == "bank" else None,
        settlement_id=settlement_id,
        txn_type="payment" if source == "razorpay" else None,
        raw_narration=narration,
        fee_paise=fee,
        tax_paise=tax,
        raw={},
        ingested_at=_AT,
    )


def _batch(n: int, *, settlement_id: str = _SETL, each: int = 10_000) -> list[TransactionEvent]:
    return [
        _event(f"g{i}", source="razorpay", amount=each, settlement_id=settlement_id, utr=_UTR)
        for i in range(n)
    ]


def _run(events: list[TransactionEvent], cfg: Config | None = None) -> object:
    return run_cascade(
        events,
        cfg=cfg or _cfg(),
        run_id="run",
        tenant_id="t",
        issue_id=deterministic_factory(seed=1, epoch_ms=1_780_000_000_000),
        created_at=_AT,
    )


def test_the_net_leg_is_the_stored_amount_not_gross_minus_fee() -> None:
    """``fc/ingest/razorpay.py`` already stored ``amount - fee``.

    Subtracting fee or tax again is the double-deduction
    ``seed._check_settlement_arithmetic`` exists to catch, and it silently pushes
    every batch out of tolerance.
    """
    payment = _event("g", source="razorpay", amount=97_695, fee=2_305, tax=305)
    assert signed_net_paise(payment) == 97_695

    refund = _event("r", source="razorpay", amount=5_000, direction="debit")
    assert signed_net_paise(refund) == -5_000
    assert settlement_net_paise([payment, refund]) == 92_695


def test_fourteen_orders_and_one_credit_group_on_settlement_id() -> None:
    """PRD §12.2 #4: a single match over 14 events at confidence 0.99.

    The bank narration names the settlement but carries no usable UTR, which is
    what leaves the batch for stage 4 - given a shared UTR, stage 1 claims it
    first and more cheaply, as it should.
    """
    rows = _batch(14)
    credit = _event(
        "bank",
        source="bank",
        amount=140_000,
        narration=f"NEFT CR RAZORPAY {_SETL} BATCH",
    )
    output = find_matches([credit, *rows], unmatched=frozenset({"bank"}), cfg=_cfg())

    assert len(output.matches) == 1
    match = output.matches[0]
    assert len(match.event_ids) == 15
    assert match.base_confidence == Decimal("0.99")
    assert match.grouped_by == "settlement_id"
    assert match.anchors == ("bank",)


def test_a_narration_citing_two_settlements_claims_neither() -> None:
    """Extraction is not attribution: two ids of one kind identify nothing."""
    rows = _batch(3)
    credit = _event(
        "bank",
        source="bank",
        amount=30_000,
        narration=f"Rolling reserve release settlement {_OTHER_SETL} for {_SETL}",
    )
    output = find_matches([credit, *rows], unmatched=frozenset({"bank"}), cfg=_cfg())
    assert output.matches == ()


def test_a_transposed_utr_still_groups_but_does_not_auto_close() -> None:
    """Scenario 15. The settlement id says these rows belong together; the
    contradicting reference is recorded and §6.6 takes the confidence down for
    it, so the batch is matched, evidenced, and left for a human."""
    rows = _batch(4)
    credit = _event(
        "bank",
        source="bank",
        amount=40_000,
        utr="HDFC261560000009",
        narration=f"NEFT CR:HDFC261560000009/RAZORPAY/{_SETL}",
    )
    output = find_matches([credit, *rows], unmatched=frozenset({"bank"}), cfg=_cfg())
    assert output.matches[0].fields_disagreed == ("utr",)

    match = next(m for m in _run([credit, *rows]).matches if "bank" in m.event_ids)
    assert match.confidence < _cfg().auto_threshold
    assert not match.auto_closed


def test_two_valid_subsets_abstain_with_ambiguous_multi_candidate() -> None:
    """PRD §12.2 #5, and the whole point of the stage.

    Two rows of 10,000 and one of 20,000: the target of 20,000 is reachable as
    the pair or as the single. Both are valid, so neither is the answer.
    """
    outcome = bounded_subset_sum(
        [("a", 10_000), ("b", 10_000), ("c", 20_000)],
        target=20_000,
        tolerance=0,
    )
    assert outcome.subset is None
    assert outcome.ambiguous

    credit = _event("bank", source="bank", amount=20_000, narration="NEFT CR RAZORPAY")
    rows = [
        _event("a", source="razorpay", amount=10_000),
        _event("b", source="razorpay", amount=10_000),
        _event("c", source="razorpay", amount=20_000),
    ]
    output = find_matches([credit, *rows], unmatched=frozenset({"bank", "a", "b", "c"}), cfg=_cfg())
    assert output.matches == ()
    assert [r.category for r in output.refusals] == ["ambiguous_multi_candidate"]
    assert output.abstained == ("bank",)


def test_exactly_one_subset_matches_at_the_ungrouped_confidence() -> None:
    outcome = bounded_subset_sum(
        [("a", 10_000), ("b", 25_000), ("c", 40_000)],
        target=35_000,
        tolerance=0,
    )
    assert outcome.subset == ("a", "b")
    assert not outcome.ambiguous


def test_no_valid_subset_is_not_a_refusal() -> None:
    """Nothing fits, so the row falls through to stage 5 rather than becoming an
    exception here. Only ambiguity is this stage's finding."""
    outcome = bounded_subset_sum([("a", 10_000)], target=99_999, tolerance=0)
    assert outcome.subset is None
    assert outcome.answers == 0


def test_more_candidates_than_max_subset_n_falls_through_without_searching() -> None:
    """§6.3: above the cap, return None and let stage 5 have it. Scenario 3's
    largest batch is sized one above ``max_subset_n`` precisely for this."""
    cfg = _cfg()
    rows = _batch(cfg.max_subset_n + 1)
    credit = _event("bank", source="bank", amount=410_000, narration="NEFT CR RAZORPAY")
    output = find_matches(
        [credit, *rows],
        unmatched=frozenset({"bank", *(r.event_id for r in rows)}),
        cfg=cfg,
    )
    assert output.matches == ()
    assert output.refusals == ()
    assert output.diagnostics["subset_sum_over_max_n"] == 1
    assert output.diagnostics["subset_sum_invocations"] == 0


def test_two_hundred_identical_amounts_terminate_inside_the_step_budget() -> None:
    """The pathological case, and the reason the DP is keyed on sums.

    With 200 equal values the reachable set is ``{0, v, 2v, ...}`` bounded by the
    target, so its size does not grow with the row count. Subset *counts* explode
    - C(200,3) ways to reach 3v - but they saturate at 2 and are never
    enumerated, so this is ambiguous almost immediately rather than slow.
    """
    values = [(f"e{i}", 10_000) for i in range(200)]
    started = time.monotonic()
    outcome = bounded_subset_sum(values, target=30_000, tolerance=0)
    elapsed_ms = (time.monotonic() - started) * 1000

    assert outcome.ambiguous
    assert outcome.subset is None
    assert not outcome.budget_exhausted
    assert outcome.steps_used < SUBSET_STEP_BUDGET
    assert elapsed_ms < _cfg().subset_timeout_ms


def test_the_step_budget_is_calibrated_against_the_largest_legal_batch() -> None:
    """``max_subset_n`` rows of distinct amounts: the worst input the cap admits.

    The clock appears here and nowhere in the decision path. This is a
    calibration assertion - one-sided, and non-determinism in it is harmless -
    whereas a clock inside the matcher would make the same corpus produce
    different exceptions on different machines.
    """
    cfg = _cfg()
    values = [(f"e{i}", 10_000 + i * 7) for i in range(cfg.max_subset_n)]
    target = sum(v for _, v in values[:14])

    started = time.monotonic()
    outcome = bounded_subset_sum(values, target=target, tolerance=0)
    elapsed_ms = (time.monotonic() - started) * 1000

    assert not outcome.wall_clock_tripped
    assert outcome.steps_used <= SUBSET_STEP_BUDGET
    assert elapsed_ms < cfg.subset_timeout_ms


def test_the_answer_does_not_depend_on_candidate_order() -> None:
    """Hard rule 9. Permuting the input must not change which subset is found."""
    values = [("a", 10_000), ("b", 25_000), ("c", 40_000), ("d", 3_000)]
    first = bounded_subset_sum(values, target=35_000, tolerance=0)
    second = bounded_subset_sum(list(reversed(values)), target=35_000, tolerance=0)
    assert first.subset is not None
    assert sorted(first.subset) == sorted(second.subset or ())


def test_the_dp_path_never_auto_closes_even_at_a_zero_threshold() -> None:
    """§6.3 grants auto-close to the grouped path only.

    Dropping ``auto_threshold`` to zero removes the arithmetic coincidence that
    used to be the only thing stopping an ungrouped subset from closing itself.
    What remains is the rule.
    """
    from fc.models.match import stage_may_auto_close

    assert not stage_may_auto_close("many_to_one", grouped_by=None)
    assert stage_may_auto_close("many_to_one", grouped_by="settlement_id")

    rows = [
        _event("a", source="razorpay", amount=10_000, settlement_id=_SETL),
        _event("b", source="razorpay", amount=25_000, settlement_id=_SETL),
    ]
    credit = _event("bank", source="bank", amount=35_000, narration="NEFT CR RAZORPAY")
    result = _run([credit, *rows], _cfg(auto_threshold=Decimal(0)))
    for match in result.matches:
        if any(e.stage == "many_to_one" and e.grouped_by is None for e in match.evidence):
            assert not match.auto_closed
