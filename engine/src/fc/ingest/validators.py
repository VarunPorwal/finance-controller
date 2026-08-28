"""Cross-source ingestion guards — PRD §6.1.

Balance continuity, typed schema rejection, and the idempotency-key table.
Every rejection is logged with a reason and returned to the caller; nothing
is ever silently dropped (build prompt "DO NOT" list).
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from fc.models.transaction import Source, TransactionEvent

__all__ = [
    "Break",
    "FieldRejection",
    "HasBalanceFields",
    "IngestResult",
    "Rejection",
    "check_idempotency",
    "logger",
    "reject",
    "validate_schema",
    "verify_balance_continuity",
]

logger = logging.getLogger("fc.ingest")


@dataclass(frozen=True)
class Break:
    """A running-balance discontinuity found at ``row`` (0-indexed, body-relative)."""

    row: int
    expected: int
    found: int


@dataclass(frozen=True)
class FieldRejection:
    """One field that failed schema validation."""

    field: str
    expected: str
    found: str


@dataclass(frozen=True)
class Rejection:
    """A row that did not become a :class:`TransactionEvent`, and why."""

    source_row_id: str | None
    reason: str
    fields: tuple[FieldRejection, ...] = ()


@dataclass(frozen=True)
class IngestResult:
    """What every adapter's parse function returns: events, plus what was rejected."""

    events: tuple[TransactionEvent, ...]
    rejections: tuple[Rejection, ...]


class HasBalanceFields(Protocol):
    """Read-only shape: properties, not plain attributes, so a frozen
    dataclass (immutable, read-only fields) still structurally satisfies it —
    a mutable-attribute Protocol requires write access mypy won't grant."""

    @property
    def deposit_paise(self) -> int | None: ...
    @property
    def withdrawal_paise(self) -> int | None: ...
    @property
    def closing_balance_paise(self) -> int: ...


def verify_balance_continuity(
    rows: Sequence[HasBalanceFields], opening_paise: int
) -> tuple[bool, list[Break]]:
    """``bal[n] == bal[n-1] + deposit[n] - withdrawal[n]``, PRD §6.1.

    Resyncs to the row's own stated balance after each break, so every break
    in the file is found rather than only the first.
    """
    bal = opening_paise
    breaks: list[Break] = []
    for i, row in enumerate(rows):
        bal = bal + (row.deposit_paise or 0) - (row.withdrawal_paise or 0)
        if bal != row.closing_balance_paise:
            breaks.append(Break(row=i, expected=bal, found=row.closing_balance_paise))
            bal = row.closing_balance_paise
    return (len(breaks) == 0, breaks)


def validate_schema(row: Mapping[str, Any], model: type[BaseModel]) -> list[FieldRejection]:
    """Validate ``row`` against ``model``; return a typed rejection per bad field."""
    try:
        model.model_validate(row)
    except ValidationError as exc:
        out: list[FieldRejection] = []
        for err in exc.errors():
            field_path = ".".join(str(part) for part in err["loc"]) or "__root__"
            out.append(
                FieldRejection(
                    field=field_path,
                    expected=err.get("msg", ""),
                    found=repr(err.get("input")),
                )
            )
        return out
    return []


def check_idempotency(source: Source, row: Mapping[str, Any]) -> str:
    """PRD §6.1 idempotency table: the same row parsed twice yields the same key."""
    if source == "razorpay":
        return str(row["entity_id"])
    if source == "ledger":
        return str(row["voucher_guid"])
    if source == "bank":
        parts = "|".join(
            str(row[k]) for k in ("txn_date", "amount", "narration", "closing_balance")
        )
        return hashlib.sha256(parts.encode("utf-8")).hexdigest()
    raise ValueError(f"unknown source: {source!r}")


def reject(
    rejections: list[Rejection],
    source_row_id: str | None,
    reason: str,
    fields: Sequence[FieldRejection] = (),
) -> None:
    """Append a logged, typed rejection. The single write path so nothing is dropped silently."""
    logger.warning("ingest rejection row=%s reason=%s", source_row_id, reason)
    rejections.append(Rejection(source_row_id=source_row_id, reason=reason, fields=tuple(fields)))
