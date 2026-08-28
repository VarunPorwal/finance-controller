"""HDFC-style NetBanking CSV ingestion — PRD §4.1.3, §6.1.

Withdrawal and deposit stay in separate columns, never collapsed, until a
row becomes exactly one :class:`TransactionEvent`. The running balance is
verified at ingestion rather than trusted. The header can be exceeded by a
row's field count when the narration contains an unescaped comma — the
overflow is absorbed into the narration column, never treated as failure to
parse (only a genuine field-count mismatch raises :class:`MalformedRow`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from fc.ingest.aliases import AliasTable, normalise_counterparty
from fc.ingest.narration.base import NarrationParser
from fc.ingest.validators import (
    Break,
    IngestResult,
    Rejection,
    check_idempotency,
    reject,
    verify_balance_continuity,
)
from fc.models.money import to_paise
from fc.models.transaction import Direction, TransactionEvent

__all__ = ["BankIngestResult", "MalformedRow", "RawBankRow", "parse_bank_csv", "parse_csv_line"]

#: PRD §4.1.3 field table, in header order.
HEADER = (
    "txn_date",
    "value_date",
    "narration",
    "chq_ref_no",
    "withdrawal_amt",
    "deposit_amt",
    "closing_balance",
)


class MalformedRow(ValueError):
    """A CSV line whose field count cannot be reconciled with the header, even
    after absorbing narration overflow (PRD §6.1)."""


@dataclass(frozen=True)
class RawBankRow:
    """One parsed CSV line, amounts converted to paise, before it becomes an event."""

    txn_date: date
    value_date: date | None
    narration: str
    chq_ref_no: str | None
    withdrawal_paise: int | None
    deposit_paise: int | None
    closing_balance_paise: int
    raw: dict[str, str]


@dataclass(frozen=True)
class BankIngestResult:
    ingest: IngestResult
    balanced: bool
    breaks: tuple[Break, ...]


def parse_csv_line(line: str, header: Sequence[str]) -> dict[str, str]:
    """Absorb narration-comma overflow — the §6.1 algorithm, verbatim.

    Indian bank CSVs frequently emit more fields than the header declares
    because the narration contains an unescaped comma. Narration is the only
    free-text column, so any overflow belongs there.
    """
    parts = line.split(",")
    if len(parts) == len(header):
        return dict(zip(header, parts, strict=True))

    narration_idx = header.index("narration")
    overflow = len(parts) - len(header)
    if overflow < 0:
        raise MalformedRow(line)

    merged = (
        parts[:narration_idx]
        + [",".join(parts[narration_idx : narration_idx + overflow + 1])]
        + parts[narration_idx + overflow + 1 :]
    )
    if len(merged) != len(header):
        raise MalformedRow(line)
    return dict(zip(header, merged, strict=True))


def parse_bank_csv(
    content: str,
    *,
    run_id: str,
    tenant_id: str,
    narration_parser: NarrationParser,
    opening_balance_paise: int,
    issue_id: Callable[[str], str],
    ingested_at: datetime,
    aliases: AliasTable | None = None,
) -> BankIngestResult:
    """Parse an HDFC-style NetBanking CSV export into :class:`TransactionEvent`.

    Pure: no I/O beyond ``content``, no wall clock. Returns the ingest
    result alongside the balance-continuity check for the whole file, so a
    corrupt upload or hallucinated extraction is caught here rather than
    silently matched later.
    """
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if not lines:
        return BankIngestResult(
            ingest=IngestResult(events=(), rejections=()), balanced=True, breaks=()
        )

    header = [h.strip().lower() for h in lines[0].split(",")]
    body = lines[1:]

    parsed_rows: list[RawBankRow] = []
    rejections: list[Rejection] = []

    for i, line in enumerate(body):
        line_no = i + 2  # 1-indexed, plus the header line
        try:
            fields = parse_csv_line(line, header)
        except MalformedRow:
            reject(
                rejections,
                f"line_{line_no}",
                f"field count does not reconcile with header: {line!r}",
            )
            continue

        try:
            parsed_rows.append(_to_raw_row(fields))
        except (ValueError, KeyError) as exc:
            reject(rejections, f"line_{line_no}", f"malformed row: {exc}")
            continue

    balanced, breaks = verify_balance_continuity(parsed_rows, opening_balance_paise)

    events: list[TransactionEvent] = []
    for row in parsed_rows:
        if row.deposit_paise:
            direction: Direction = "credit"
            amount_paise = row.deposit_paise
        elif row.withdrawal_paise:
            direction = "debit"
            amount_paise = row.withdrawal_paise
        else:
            reject(rejections, None, f"row has neither withdrawal nor deposit amount: {row.raw!r}")
            continue

        parsed = narration_parser.parse(row.narration)
        counterparty_norm = (
            normalise_counterparty(parsed.counterparty, aliases) if parsed.counterparty else None
        )
        source_row_id = check_idempotency(
            "bank",
            {
                "txn_date": row.txn_date.isoformat(),
                "amount": amount_paise,
                "narration": row.narration,
                "closing_balance": row.closing_balance_paise,
            },
        )

        events.append(
            TransactionEvent(
                event_id=issue_id("evt_"),
                run_id=run_id,
                tenant_id=tenant_id,
                source="bank",
                source_row_id=source_row_id,
                amount_paise=amount_paise,
                direction=direction,
                txn_date=row.txn_date,
                value_date=row.value_date,
                # Truncated references are excluded from exact matching
                # downstream (PRD §6.1); the flag itself lives on the
                # narration, surfaced via raw_narration and raw.
                utr=parsed.reference if parsed.rail in ("neft", "rtgs") else None,
                rrn=parsed.reference if parsed.rail in ("imps", "upi") else None,
                counterparty=parsed.counterparty,
                counterparty_norm=counterparty_norm,
                rail=parsed.rail,
                raw_narration=row.narration,
                raw=row.raw,
                ingested_at=ingested_at,
            )
        )

    return BankIngestResult(
        ingest=IngestResult(events=tuple(events), rejections=tuple(rejections)),
        balanced=balanced,
        breaks=tuple(breaks),
    )


def _to_raw_row(fields: dict[str, str]) -> RawBankRow:
    return RawBankRow(
        txn_date=_parse_ddmmyyyy(fields["txn_date"]),
        value_date=_parse_ddmmyyyy(fields["value_date"])
        if fields.get("value_date", "").strip()
        else None,
        narration=fields["narration"].strip(),
        chq_ref_no=fields["chq_ref_no"].strip() or None,
        withdrawal_paise=_optional_amount(fields["withdrawal_amt"]),
        deposit_paise=_optional_amount(fields["deposit_amt"]),
        closing_balance_paise=to_paise(fields["closing_balance"]),
        raw=fields,
    )


def _parse_ddmmyyyy(text: str) -> date:
    return datetime.strptime(text.strip(), "%d/%m/%Y").date()


def _optional_amount(text: str) -> int | None:
    text = text.strip()
    return to_paise(text) if text else None
