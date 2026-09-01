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

__all__ = [
    "BANK_ACCOUNT_WORDS",
    "Direction",
    "Source",
    "TransactionEvent",
    "bank_signed_paise",
    "is_bank_account",
]

#: Words that name a bank or cash account in a chart of accounts. Used to
#: decide which leg of a daybook voucher is the bank's own, which is what
#: fixes that row's sign. Read from the account name rather than from
#: configuration because the sign convention has to be right even on a
#: tenant whose chart of accounts nobody has described to the engine.
#: "Bank Charges" is excluded explicitly: it contains the word and is an
#: expense account, the exact false positive CLAUDE.md warns about for
#: ``bank_ledger_names``.
BANK_ACCOUNT_WORDS = ("BANK", "CASH", "CURRENT A")

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

    @property
    def bank_signed_paise(self) -> int:
        """Signed amount with "money toward the bank account" as positive.

        Bank and gateway rows already say this with ``direction``. Tally does
        not, and the correction is *not* a blanket flip of every ledger row —
        which is what this used to be, and it silently doubled every operating
        payment it touched.

        Which way a daybook row points depends on which leg of the voucher it
        is. A Receipt's bank leg books money arriving as a **debit** to the bank
        account, Tally's asset convention, so that row flips. The same
        voucher's expense or party leg is an ordinary debit meaning money out,
        and flipping it turns a ₹92,000 rent payment into a ₹92,000 receipt —
        which on a single-row daybook export (where the bank leg is implied and
        only the expense leg is written down) made every payment disagree with
        its own bank debit by exactly twice its value.
        """
        sign = 1 if self.direction == "credit" else -1
        if self.source == "ledger" and is_bank_account(self.ledger_account):
            sign = -sign
        return sign * self.amount_paise

    def without_ground_truth(self) -> TransactionEvent:
        """Strip generator labels. Anything reaching the decision path uses this."""
        return self.model_copy(update={"gt_match_group": None, "gt_label": None})


def is_bank_account(ledger_account: str | None) -> bool:
    """Whether a Tally ledger name denotes a bank or cash account."""
    name = (ledger_account or "").upper()
    if "CHARGES" in name:
        return False
    return any(word in name for word in BANK_ACCOUNT_WORDS)


def bank_signed_paise(event: TransactionEvent) -> int:
    """Module-level alias of :attr:`TransactionEvent.bank_signed_paise`."""
    return event.bank_signed_paise
