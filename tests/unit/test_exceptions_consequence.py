"""Cash impact and deadline — PRD §6.8.6."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from fc.config import load_config
from fc.exceptions.classify import Classified
from fc.exceptions.consequence import consequence_and_deadline
from fc.models.transaction import Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)
_CFG = load_config(env_file=None, environ={})


def _event(event_id: str, *, source: Source, amount: int, **kwargs: object) -> TransactionEvent:
    defaults: dict[str, object] = {
        "run_id": "run",
        "tenant_id": "t",
        "source": source,
        "source_row_id": event_id,
        "amount_paise": amount,
        "direction": "credit",
        "txn_date": date(2026, 8, 1),
        "raw": {},
        "ingested_at": _AT,
    }
    defaults.update(kwargs)
    return TransactionEvent(event_id=event_id, **defaults)  # type: ignore[arg-type]


def _classified(category: str, event_ids: tuple[str, ...]) -> Classified:
    return Classified(
        event_ids=event_ids,
        category=category,  # type: ignore[arg-type]
        amount_paise=10_000,
        residual_paise=10_000,
        reason="test",
        confidence=Decimal("0.9"),
        gross_paise=10_000,
        gap_paise=10_000,
    )


def test_chargeback_deadline_is_the_dispute_window_from_the_event_date() -> None:
    event = _event("dp", source="razorpay", amount=10_000, txn_date=date(2026, 8, 1))
    classified = _classified("chargeback_unrecorded", ("dp",))

    text, deadline = consequence_and_deadline(
        classified, events_by_id={"dp": event}, cfg=_CFG, as_of=date(2026, 8, 1)
    )

    assert deadline is not None
    assert (deadline - date(2026, 8, 1)).days == _CFG.dispute_window_days
    assert "unrecoverable" in text
    assert str(_CFG.dispute_window_days) in text


def test_missing_in_bank_deadline_is_the_sla_from_settlement() -> None:
    event = _event("pay", source="razorpay", amount=10_000, settled_at=_AT)
    classified = _classified("missing_in_bank", ("pay",))

    text, deadline = consequence_and_deadline(
        classified, events_by_id={"pay": event}, cfg=_CFG, as_of=date(2026, 8, 1)
    )

    assert deadline is not None
    assert (deadline - _AT.date()).days == _CFG.missing_in_bank_sla_days
    assert "not yet received" in text


def test_timing_lag_carries_no_hard_deadline() -> None:
    event = _event("e", source="bank", amount=10_000)
    classified = _classified("timing_lag", ("e",))

    _, deadline = consequence_and_deadline(
        classified, events_by_id={"e": event}, cfg=_CFG, as_of=date(2026, 8, 1)
    )

    assert deadline is None


def test_unknown_carries_neither_consequence_nor_deadline() -> None:
    event = _event("e", source="bank", amount=10_000)
    classified = _classified("unknown", ("e",))

    text, deadline = consequence_and_deadline(
        classified, events_by_id={"e": event}, cfg=_CFG, as_of=date(2026, 8, 1)
    )

    assert text is None
    assert deadline is None
