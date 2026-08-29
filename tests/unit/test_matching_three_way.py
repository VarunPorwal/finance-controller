"""Three-way resolution catches what two-way structurally cannot — PRD §6.4, D7.

The case that justifies the differentiator: a duplicate Tally voucher. Gateway
and bank agree perfectly, the money moved once, and the books say it moved twice.
There is nothing for a two-way reconciliation to disagree with, so it closes the
group at confidence 1.0 and reports success.

The awkward part, and what these tests mostly defend, is that "two or more ledger
legs" cannot be read literally. A healthy settlement group holds a Sales voucher
per order, a Receipt, and Journals for MDR, GST, TDS and reserve - nine to
forty-five ledger legs is normal. A test that flagged every group with more than
one leg would condemn the whole corpus while looking like it worked.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fc.config import Config, load_config
from fc.matching.cascade import run_cascade
from fc.matching.three_way import leg_signature
from fc.models.ids import deterministic_factory
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
    voucher_type: str | None = None,
    voucher_number: str | None = None,
    narration: str | None = None,
    fee: int | None = None,
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
        txn_type="payment" if source == "razorpay" else None,
        voucher_type=voucher_type,
        voucher_number=voucher_number,
        raw_narration=narration,
        fee_paise=fee,
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


def _two_way() -> list[TransactionEvent]:
    """Gateway and bank agreeing, joined by a shared UTR."""
    return [
        _event("bank", source="bank", amount=100_000, utr=_UTR, narration=f"NEFT CR:{_UTR}/RZP"),
        _event(
            "pay",
            source="razorpay",
            amount=100_000,
            utr=_UTR,
            settlement_id=_SETL,
            order_id=_ORDER,
        ),
    ]


def _receipt(event_id: str, *, voucher_number: str) -> TransactionEvent:
    return _event(
        event_id,
        source="ledger",
        amount=100_000,
        direction="debit",
        voucher_type="Receipt",
        voucher_number=voucher_number,
        narration=f"Settlement credit {_SETL}",
    )


def test_a_duplicate_voucher_is_refused_and_the_group_never_auto_closes() -> None:
    """PRD §12.2 #7, and the whole justification for D7.

    Both receipts quote the same settlement, so stage 1 unions them into the
    group: the duplicate is not sitting in the unmatched pool waiting to be
    found, it is already inside a group that would otherwise close at 1.0.
    """
    events = [
        *_two_way(),
        _receipt("rcp1", voucher_number="RCP/00037"),
        _receipt("rcp2", voucher_number="RCP/00038"),
    ]
    result = _run(events)

    duplicates = [r for r in result.refusals if r.category == "duplicate_ledger_entry"]
    assert len(duplicates) == 1
    assert set(duplicates[0].event_ids) == {"rcp1", "rcp2"}

    holding = next(m for m in result.matches if "rcp1" in m.event_ids)
    assert not holding.auto_closed


def test_the_signature_ignores_voucher_identity_and_keeps_the_movement() -> None:
    """Two rows are duplicates precisely when they differ only in identity."""
    first, second = (
        _receipt("a", voucher_number="RCP/00037"),
        _receipt("b", voucher_number="RCP/00038"),
    )
    assert leg_signature(first) == leg_signature(second)


def test_a_settlements_many_journal_legs_are_not_a_duplicate() -> None:
    """The false positive that a naive leg count would produce on every batch."""
    events = [
        *_two_way(),
        _receipt("rcp", voucher_number="RCP/00037"),
        _event(
            "mdr",
            source="ledger",
            amount=2_000,
            direction="credit",
            voucher_type="Journal",
            voucher_number="JV/1",
            narration=f"MDR on {_SETL}",
        ),
        _event(
            "gst",
            source="ledger",
            amount=360,
            direction="credit",
            voucher_type="Journal",
            voucher_number="JV/2",
            narration=f"GST input on {_SETL}",
        ),
        _event(
            "tds",
            source="ledger",
            amount=1_000,
            direction="credit",
            voucher_type="Journal",
            voucher_number="JV/3",
            narration=f"TDS 194-O on {_SETL}",
        ),
    ]
    result = _run(events)
    assert [r for r in result.refusals if r.category == "duplicate_ledger_entry"] == []


def test_two_journals_recording_one_deduction_twice_are_not_flagged_either() -> None:
    """Duplication is judged on the cash-side leg only.

    Two identical Journals are the same deduction described twice, which the
    deduction stack reconciles. Two Receipts are the books claiming the money
    arrived twice, which nothing downstream can reconcile.
    """
    same = dict(
        source="ledger",
        amount=2_000,
        direction="credit",
        voucher_type="Journal",
        narration=f"MDR on {_SETL}",
    )
    events = [
        *_two_way(),
        _receipt("rcp", voucher_number="RCP/00037"),
        _event("j1", voucher_number="JV/1", **same),  # type: ignore[arg-type]
        _event("j2", voucher_number="JV/2", **same),  # type: ignore[arg-type]
    ]
    result = _run(events)
    assert [r for r in result.refusals if r.category == "duplicate_ledger_entry"] == []


def test_a_group_with_no_ledger_leg_is_missing_in_ledger() -> None:
    result = _run(_two_way())
    missing = [r for r in result.refusals if r.category == "missing_in_ledger"]
    assert len(missing) == 1
    assert set(missing[0].event_ids) == {"bank", "pay"}


def test_one_ledger_leg_attaches_and_the_group_becomes_three_way() -> None:
    events = [
        *_two_way(),
        _event(
            "sales",
            source="ledger",
            amount=100_000,
            voucher_type="Sales",
            voucher_number="SL/1",
            narration=f"Sales order {_ORDER}",
        ),
    ]
    result = _run(events)
    holding = next(m for m in result.matches if "sales" in m.event_ids)
    assert sorted(set(holding.sources_covered)) == ["bank", "ledger", "razorpay"]
    assert holding.is_three_way
    assert "sales" in result.matched_event_ids
    assert "sales" not in result.unmatched_event_ids


def test_two_rival_legs_refuse_and_neither_is_attached() -> None:
    """§6.4: two or more found is a duplicate, not a choice.

    The legs are unreferenced, so nothing joins them earlier and they arrive here
    as genuine rivals for one movement. Attaching either would assert something
    the books do not say.
    """
    events = [
        *_two_way(),
        _event("l1", source="ledger", amount=100_000, voucher_type="Sales", voucher_number="SL/1"),
        _event("l2", source="ledger", amount=100_000, voucher_type="Sales", voucher_number="SL/2"),
    ]
    result = _run(events)

    rivals = [r for r in result.refusals if r.category == "duplicate_ledger_entry"]
    assert len(rivals) == 1
    # The refusal names the group as well as the rivals: the finding is about
    # this movement's ledger attribution, so the group must be implicated or
    # nothing stops it closing at full confidence.
    assert {"l1", "l2"} <= set(rivals[0].event_ids)
    assert {"bank", "pay"} <= set(rivals[0].event_ids)

    holding = next(m for m in result.matches if "bank" in m.event_ids)
    assert "l1" not in holding.event_ids
    assert "l2" not in holding.event_ids
    assert not holding.auto_closed


def test_a_ledger_row_citing_two_settlements_is_not_attached() -> None:
    """Extraction is not attribution, in three-way as in stage 1."""
    other = "setl_01KT07NVH5KTVYN9PVWMBFQW17"
    events = [
        *_two_way(),
        _event(
            "reserve",
            source="ledger",
            amount=100_000,
            voucher_type="Journal",
            voucher_number="JV/9",
            narration=f"Rolling reserve release settlement {other} for {_SETL}",
        ),
    ]
    result = _run(events)
    holding = next(m for m in result.matches if "bank" in m.event_ids)
    assert "reserve" not in holding.event_ids


def test_the_run_is_reproducible_with_three_way_in_the_pipeline() -> None:
    events = [
        *_two_way(),
        _receipt("rcp1", voucher_number="RCP/00037"),
        _receipt("rcp2", voucher_number="RCP/00038"),
    ]
    first, second = _run(events), _run(events)
    assert [m.model_dump_json() for m in first.matches] == [
        m.model_dump_json() for m in second.matches
    ]
    assert [(r.category, r.event_ids) for r in first.refusals] == [
        (r.category, r.event_ids) for r in second.refusals
    ]


def test_a_never_auto_refusal_blocks_auto_close_at_any_threshold() -> None:
    events = [
        *_two_way(),
        _receipt("rcp1", voucher_number="RCP/00037"),
        _receipt("rcp2", voucher_number="RCP/00038"),
    ]
    result = _run(events, _cfg(auto_threshold=Decimal(0)))
    holding = next(m for m in result.matches if "rcp1" in m.event_ids)
    assert not holding.auto_closed
