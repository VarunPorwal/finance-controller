"""Razorpay settlement recon report ingestion — PRD §4.1.1, §4.1.2, §6.1.

Every amount in this report arrives already in integer paise — it must not
be run through :func:`fc.models.money.to_paise` (hard rule: Razorpay
bypasses rupee-string conversion entirely). Refund rows sit inside the same
settlement batch as the payments they refund, with ``debit`` populated and
``credit`` zero.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from fc.ingest.validators import IngestResult, Rejection, check_idempotency, reject, validate_schema
from fc.models.money import already_paise
from fc.models.transaction import Direction, TransactionEvent

__all__ = ["RazorpayReconRow", "parse_razorpay_recon"]

#: PRD §4.1.2 structural fact: ``entity_id`` carries one of these prefixes
#: depending on row type (payment, order, refund, settlement, settlement
#: line item, dispute). ``fc.generator.razorpay_gen`` emits ``dp_`` for
#: disputes; real Razorpay recon exports use ``disp_`` instead — both are
#: accepted so an uploaded real export isn't rejected wholesale.
ENTITY_ID_PREFIXES = ("pay_", "order_", "rfnd_", "setl_", "setlod_", "dp_", "disp_")

RazorpayType = Literal["payment", "refund", "adjustment", "dispute", "transfer"]
RazorpayCreditType = Literal["default", "refund", "dispute"]
RazorpayMethod = Literal["card", "upi", "netbanking", "wallet", "emi"]
RazorpayCardType = Literal["credit", "debit"]


class RazorpayReconRow(BaseModel):
    """One row of the settlement recon report — the 26 fields of PRD §4.1.2."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    type: RazorpayType
    debit: int
    credit: int
    amount: int
    currency: str = "INR"
    fee: int
    tax: int
    on_hold: bool
    settled: bool
    created_at: int
    settled_at: int | None = None
    settlement_id: str | None = None
    posted_at: int | None = None
    credit_type: RazorpayCreditType
    description: str | None = None
    notes: Any = None
    payment_id: str | None = None
    settlement_utr: str | None = None
    order_id: str | None = None
    order_receipt: str | None = None
    method: RazorpayMethod | None = None
    card_network: str | None = None
    card_issuer: str | None = None
    card_type: RazorpayCardType | None = None
    dispute_id: str | None = None


def parse_razorpay_recon(
    rows: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
    tenant_id: str,
    issue_id: Callable[[str], str],
    ingested_at: datetime,
) -> IngestResult:
    """Parse Razorpay recon report rows into :class:`TransactionEvent`.

    Pure: no I/O beyond the mappings handed in, no wall clock. ``issue_id``
    (see :func:`fc.models.ids.deterministic_factory`) and ``ingested_at`` are
    supplied by the caller so a seeded run is byte-identical (CLAUDE.md hard
    rule 9).
    """
    events: list[TransactionEvent] = []
    rejections: list[Rejection] = []

    for raw in rows:
        raw_dict = dict(raw)
        entity_id_hint = raw_dict.get("entity_id")

        field_errors = validate_schema(raw_dict, RazorpayReconRow)
        if field_errors:
            reject(
                rejections,
                str(entity_id_hint) if entity_id_hint else None,
                "schema validation failed",
                field_errors,
            )
            continue

        row = RazorpayReconRow.model_validate(raw_dict)

        if not row.entity_id.startswith(ENTITY_ID_PREFIXES):
            reject(rejections, row.entity_id, f"unrecognised entity_id prefix: {row.entity_id!r}")
            continue

        direction, amount_paise = _leg(row)
        source_row_id = check_idempotency("razorpay", {"entity_id": row.entity_id})

        events.append(
            TransactionEvent(
                event_id=issue_id("evt_"),
                run_id=run_id,
                tenant_id=tenant_id,
                source="razorpay",
                source_row_id=source_row_id,
                amount_paise=amount_paise,
                direction=direction,
                currency=row.currency,
                txn_date=_unix_to_date(row.created_at),
                value_date=_unix_to_date(row.posted_at) if row.posted_at is not None else None,
                settled_at=_unix_to_datetime(row.settled_at)
                if row.settled_at is not None
                else None,
                utr=row.settlement_utr,
                settlement_id=row.settlement_id,
                order_id=row.order_id,
                payment_id=row.payment_id,
                method=row.method,
                txn_type=row.type,
                fee_paise=already_paise(row.fee),
                tax_paise=already_paise(row.tax),
                on_hold=row.on_hold,
                raw=raw_dict,
                ingested_at=ingested_at,
            )
        )

    return IngestResult(events=tuple(events), rejections=tuple(rejections))


def _leg(row: RazorpayReconRow) -> tuple[Direction, int]:
    """Which settlement leg this row represents, and its magnitude in paise."""
    credit = already_paise(row.credit)
    if credit:
        return "credit", credit
    debit = already_paise(row.debit)
    if debit:
        return "debit", debit
    amount = already_paise(row.amount)
    return ("debit", -amount) if amount < 0 else ("credit", amount)


def _unix_to_date(ts: int) -> date:
    return datetime.fromtimestamp(ts, tz=UTC).date()


def _unix_to_datetime(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC)
