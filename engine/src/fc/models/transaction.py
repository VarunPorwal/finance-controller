"""The canonical transaction event — PRD §4.2.

Every source (Razorpay settlement rows, bank statement lines, Tally vouchers)
normalises into this one shape. Field names are load-bearing: the SQLAlchemy
table in ``db/models.py``, the Alembic migration and the generated TypeScript
client all key off them.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["Direction", "Source", "TransactionEvent"]

Source = Literal["razorpay", "bank", "ledger"]
Direction = Literal["credit", "debit"]


class TransactionEvent(BaseModel):
    """One normalised row from one source. Money is integer paise, always."""

    model_config = ConfigDict(extra="forbid")

    event_id: str  # ULID, sortable by time
    run_id: str
    tenant_id: str
    source: Source
    source_row_id: str  # entity_id | stmt_line_hash | voucher_guid

    amount_paise: int  # ALWAYS integer paise
    direction: Direction
    currency: str = "INR"

    txn_date: date
    value_date: date | None = None
    settled_at: datetime | None = None

    # reference ladder, most -> least reliable
    utr: str | None = None
    rrn: str | None = None
    settlement_id: str | None = None
    order_id: str | None = None
    payment_id: str | None = None
    voucher_number: str | None = None
    voucher_guid: str | None = None

    counterparty: str | None = None
    counterparty_norm: str | None = None
    method: str | None = None  # card|upi|netbanking|wallet|emi
    rail: str | None = None  # neft|rtgs|imps|upi|nach|internal
    txn_type: str | None = None  # payment|refund|dispute|adjustment|transfer
    raw_narration: str | None = None

    fee_paise: int | None = None
    tax_paise: int | None = None
    on_hold: bool = False

    ledger_account: str | None = None
    voucher_type: str | None = None

    raw: dict[str, Any]  # untouched original row
    ingested_at: datetime

    # ground truth — generator only, stripped on the production path
    gt_match_group: str | None = None
    gt_label: str | None = None

    @property
    def effective_date(self) -> date:
        """The date matching blocks on: value date where the source gives one."""
        return self.value_date or self.txn_date

    def without_ground_truth(self) -> TransactionEvent:
        """Strip generator labels. Anything reaching the decision path uses this."""
        return self.model_copy(update={"gt_match_group": None, "gt_label": None})
