"""The cascade's invariants: one event one group, evidence always, same in same out.

These are the properties the rest of the system relies on. A row matched at one
stage never reaches the next, nothing closes without evidence (hard rule 5), and
a seeded run is byte-identical (hard rule 9).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fc.config import Config, load_config
from fc.matching.cascade import CASCADE_ORDER, run_cascade
from fc.models.ids import deterministic_factory
from fc.models.match import stage_may_auto_close
from fc.models.transaction import Direction, Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)
_SETL = "setl_01KT07NVH5KTVYN9PVWMBFQW16"
_ORDER = "order_01KT07NV33WV987DMTMF64Y936"
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
    order_id: str | None = None,
    txn_type: str | None = None,
    voucher_type: str | None = None,
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
        order_id=order_id,
        txn_type=txn_type,
        voucher_type=voucher_type,
        raw_narration=narration,
        fee_paise=fee,
        tax_paise=tax,
        raw={},
        ingested_at=_AT,
    )


def _run(events: list[TransactionEvent], cfg: Config | None = None) -> object:
    return run_cascade(
        events,
        cfg=cfg or _cfg(),
        run_id="run",
        tenant_id="t",
        issue_id=deterministic_factory(seed=1, epoch_ms=1_780_000_000_000),
        created_at=_AT,
    )


def _settlement() -> list[TransactionEvent]:
    return [
        _event("bank", source="bank", amount=146_542, utr=_UTR, narration=f"NEFT CR:{_UTR}/RZP"),
        _event(
            "p1",
            source="razorpay",
            amount=97_695,
            utr=_UTR,
            settlement_id=_SETL,
            order_id=_ORDER,
            txn_type="payment",
            fee=2_305,
            tax=305,
        ),
        _event(
            "p2",
            source="razorpay",
            amount=48_847,
            utr=_UTR,
            settlement_id=_SETL,
            txn_type="payment",
            fee=1_153,
            tax=153,
        ),
        _event(
            "sales",
            source="ledger",
            amount=100_000,
            direction="credit",
            voucher_type="Sales",
            narration=f"Sales order {_ORDER}",
        ),
    ]


def test_the_stage_order_is_the_prd_order() -> None:
    assert CASCADE_ORDER == (
        "exact_ref",
        "fee_adjusted",
        "date_shift",
        "many_to_one",
        "fuzzy",
    )


def test_no_event_appears_in_two_match_groups() -> None:
    result = _run(_settlement())
    assigned = [e for m in result.matches for e in m.event_ids]
    assert len(assigned) == len(set(assigned))


def test_every_match_carries_at_least_one_evidence_entry() -> None:
    for match in _run(_settlement()).matches:
        assert match.evidence
        assert match.evidence[0].confidence_derivation is not None


def test_confidences_are_all_inside_the_unit_interval() -> None:
    for match in _run(_settlement()).matches:
        assert 0 <= match.confidence <= 1


def test_matched_and_unmatched_partition_the_input() -> None:
    events = _settlement()
    result = _run(events)
    assert set(result.matched_event_ids) | set(result.unmatched_event_ids) == {
        e.event_id for e in events
    }
    assert not set(result.matched_event_ids) & set(result.unmatched_event_ids)


def test_the_same_input_produces_the_same_output() -> None:
    first, second = _run(_settlement()), _run(_settlement())
    assert [m.model_dump_json() for m in first.matches] == [
        m.model_dump_json() for m in second.matches
    ]
    assert first.unmatched_event_ids == second.unmatched_event_ids


def test_a_later_stage_extends_a_group_rather_than_building_a_rival() -> None:
    """The bank narration lost its UTR, so only the arithmetic can attach it."""
    events = _settlement()
    events[0] = _event(
        "bank", source="bank", amount=146_542, narration="SETTLEMENT CREDIT RAZORPAY"
    )
    result = _run(events)
    hosting = [m for m in result.matches if "bank" in m.event_ids]
    assert len(hosting) == 1
    match = hosting[0]
    assert [e.stage for e in match.evidence] == ["exact_ref", "fee_adjusted"]
    assert match.confidence <= 1


def test_an_extended_group_keeps_the_weaker_of_the_two_confidences() -> None:
    events = _settlement()
    events[0] = _event(
        "bank", source="bank", amount=146_542, narration="SETTLEMENT CREDIT RAZORPAY"
    )
    match = next(m for m in _run(events).matches if "bank" in m.event_ids)
    derived = [e.confidence_derivation.result for e in match.evidence if e.confidence_derivation]
    assert match.confidence == min(derived)


def test_ledger_rows_with_no_reference_are_reported_and_left_unmatched() -> None:
    events = [
        *_settlement(),
        _event(
            "orphan", source="ledger", amount=999, voucher_type="Journal", narration="Bank charges"
        ),
    ]
    result = _run(events)
    assert "orphan" in result.ledger_refs.without_reference
    assert "orphan" in result.unmatched_event_ids
    assert result.diagnostics["ledger_rows_without_reference"] == 1


def test_an_empty_corpus_is_not_an_error() -> None:
    result = _run([])
    assert result.matches == ()
    assert result.unmatched_event_ids == ()


@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
@given(
    amounts=st.lists(st.integers(min_value=1, max_value=5_00_000), min_size=0, max_size=12),
    shifts=st.lists(st.integers(min_value=1, max_value=20), min_size=0, max_size=12),
)
def test_invariants_hold_on_arbitrary_input(amounts: list[int], shifts: list[int]) -> None:
    events: list[TransactionEvent] = []
    for i, amount in enumerate(amounts):
        day = 1 + (shifts[i] if i < len(shifts) else 1) % 20
        events.append(
            _event(
                f"g{i}",
                source="razorpay",
                amount=amount,
                day=day,
                utr=f"HDFC2615600000{i:02d}",
                settlement_id=f"setl_{i}",
                txn_type="payment",
                fee=0,
            )
        )
        events.append(
            _event(f"b{i}", source="bank", amount=amount, day=day, utr=f"HDFC2615600000{i:02d}")
        )

    result = _run(events)
    assigned = [e for m in result.matches for e in m.event_ids]
    assert len(assigned) == len(set(assigned))
    for match in result.matches:
        assert 0 <= match.confidence <= 1
        assert match.evidence


def test_the_same_seed_produces_the_same_refusals_and_search_costs() -> None:
    """Hard rule 9 over the abstentions, not just the matches.

    An engine whose *exceptions* vary between runs cannot be audited, and the
    subset-sum step counts are included because a work budget that drifted would
    silently change which settlements abstain.
    """
    events = _settlement()
    first, second = _run(events), _run(events)

    assert [(r.category, r.event_ids, r.reason) for r in first.refusals] == [
        (r.category, r.event_ids, r.reason) for r in second.refusals
    ]
    search = lambda r: {k: v for k, v in r.diagnostics.items() if "subset_sum" in k}  # noqa: E731
    assert search(first) == search(second)


def test_no_auto_closed_group_carries_a_leg_that_may_not_auto_close() -> None:
    """The permanent gate for the weakest-leg rule.

    Checked over the evidence rather than ``MatchResult.stage``: a group formed
    by stage 1 and extended by stage 5 still reports ``stage="exact_ref"``, so
    the PRD §12.3 formulation (filtering ``m.stage == "fuzzy"``) cannot see the
    case it is meant to catch.
    """
    for match in _run(_settlement()).matches:
        if not match.auto_closed:
            continue
        for leg in match.evidence:
            assert stage_may_auto_close(leg.stage, grouped_by=leg.grouped_by)
