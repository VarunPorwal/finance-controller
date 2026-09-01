"""Tally Prime day book ingestion — PRD §4.1.6, §6.1.

Negatives export with a ``(-)`` prefix, not a minus sign, and Indian digit
grouping (``(-)1,24,500.00``); :func:`fc.models.money.to_paise` already
parses both. ``voucher_guid`` is the idempotency key: a repeated XML import
must not duplicate a voucher, and a CSV/XML re-parse of the same file must
yield the same ``source_row_id`` every time.

``reference_number`` is an invoice/bill reference (e.g. ``INV/2026-27/0412``),
not a gateway order id, so it is kept only in ``raw`` and never mapped onto
:attr:`TransactionEvent.order_id` — three-way matching (PRD §6.4) finds the
ledger leg via ``narration``, where the actual order reference appears.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime
from typing import Any
from xml.etree import ElementTree

from fc.ingest.aliases import AliasTable, normalise_counterparty
from fc.ingest.narration.base import NEFT_RTGS_UTR_LEN, document_reference
from fc.ingest.validators import IngestResult, Rejection, check_idempotency, reject
from fc.models.money import to_paise
from fc.models.transaction import Direction, TransactionEvent

__all__ = ["VOUCHER_TYPES", "parse_tally_csv", "parse_tally_xml"]

#: PRD §4.1.6: all 7 voucher types.
VOUCHER_TYPES = ("Sales", "Receipt", "Payment", "Journal", "Credit Note", "Debit Note", "Contra")

#: PRD §4.1.6 field table, canonical order.
FIELDS = (
    "voucher_date",
    "voucher_type",
    "voucher_number",
    "ledger_name",
    "party_ledger_name",
    "debit",
    "credit",
    "narration",
    "reference_number",
    "cost_centre",
    "gstin",
    "voucher_guid",
)

#: Common Tally XML day-book export tag names, aliased onto the canonical
#: field set above (no single authoritative export schema is given in the
#: PRD beyond the field table, so both the canonical tag names and these
#: common ones are accepted — see the module notes surfaced at the end of
#: this build for the assumption this rests on).
XML_TAG_ALIASES: dict[str, str] = {
    "date": "voucher_date",
    "vouchertypename": "voucher_type",
    "vouchernumber": "voucher_number",
    "ledgername": "ledger_name",
    "partyledgername": "party_ledger_name",
    "debit": "debit",
    "credit": "credit",
    "narration": "narration",
    "referencenumber": "reference_number",
    "costcentre": "cost_centre",
    "gstin": "gstin",
    "guid": "voucher_guid",
}


def parse_tally_csv(
    content: str,
    *,
    run_id: str,
    tenant_id: str,
    issue_id: Callable[[str], str],
    ingested_at: datetime,
    aliases: AliasTable | None = None,
) -> IngestResult:
    """Parse a Tally day book CSV export whose header is the 12 §4.1.6 field names."""
    reader = csv.DictReader(io.StringIO(content))
    return _parse_rows(
        reader,
        run_id=run_id,
        tenant_id=tenant_id,
        issue_id=issue_id,
        ingested_at=ingested_at,
        aliases=aliases,
    )


def parse_tally_xml(
    content: str,
    *,
    run_id: str,
    tenant_id: str,
    issue_id: Callable[[str], str],
    ingested_at: datetime,
    aliases: AliasTable | None = None,
) -> IngestResult:
    """Parse a Tally day book XML export.

    Accepts either the canonical flat tag set (``<voucher_date>`` etc.) or
    common Tally export tag names (``<DATE>``, ``<VOUCHERTYPENAME>``, ...),
    matched case-insensitively via :data:`XML_TAG_ALIASES`, as either child
    elements or attributes of a ``<VOUCHER>``/``<TALLYVOUCHER>`` element.
    """
    root = ElementTree.fromstring(content)
    rows: list[dict[str, str]] = []
    for voucher in root.iter():
        if voucher.tag.lower() not in ("voucher", "tallyvoucher"):
            continue
        row: dict[str, str] = {}
        for child in voucher:
            key = child.tag.lower()
            field = XML_TAG_ALIASES.get(key, key if key in FIELDS else None)
            if field is not None:
                row[field] = (child.text or "").strip()
        for attr_name, attr_value in voucher.attrib.items():
            field = XML_TAG_ALIASES.get(attr_name.lower(), attr_name.lower())
            if field in FIELDS and field not in row:
                row[field] = attr_value.strip()
        if row:
            rows.append(row)

    return _parse_rows(
        rows,
        run_id=run_id,
        tenant_id=tenant_id,
        issue_id=issue_id,
        ingested_at=ingested_at,
        aliases=aliases,
    )


def _parse_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    run_id: str,
    tenant_id: str,
    issue_id: Callable[[str], str],
    ingested_at: datetime,
    aliases: AliasTable | None,
) -> IngestResult:
    events: list[TransactionEvent] = []
    rejections: list[Rejection] = []

    for i, raw in enumerate(rows):
        row = dict(raw)
        guid_hint = row.get("voucher_guid")
        try:
            voucher_type = _required(row, "voucher_type")
            if voucher_type not in VOUCHER_TYPES:
                raise ValueError(f"unknown voucher_type: {voucher_type!r}")
            voucher_date = date.fromisoformat(_required(row, "voucher_date"))
            debit_paise = to_paise(row.get("debit") or "0")
            credit_paise = to_paise(row.get("credit") or "0")
            direction, amount_paise = _leg(debit_paise, credit_paise)
            guid = _required(row, "voucher_guid")
        except (ValueError, KeyError) as exc:
            reject(rejections, str(guid_hint) if guid_hint else f"row_{i}", f"malformed row: {exc}")
            continue

        party = row.get("party_ledger_name") or None
        utr, rrn = _voucher_reference(row.get("reference_number"), narration=row.get("narration"))
        source_row_id = check_idempotency("ledger", {"voucher_guid": guid})

        events.append(
            TransactionEvent(
                event_id=issue_id("evt_"),
                run_id=run_id,
                tenant_id=tenant_id,
                source="ledger",
                source_row_id=source_row_id,
                amount_paise=amount_paise,
                direction=direction,
                txn_date=voucher_date,
                utr=utr,
                rrn=rrn,
                voucher_number=row.get("voucher_number") or None,
                voucher_guid=guid,
                counterparty=party,
                counterparty_norm=normalise_counterparty(party, aliases) if party else None,
                raw_narration=row.get("narration") or None,
                ledger_account=row.get("ledger_name") or None,
                voucher_type=voucher_type,
                raw=row,
                ingested_at=ingested_at,
            )
        )

    return IngestResult(events=tuple(events), rejections=tuple(rejections))


#: See ``fc.ingest.bank_csv._document_reference`` — the same threshold, for
#: the same reason, on the other side of the same join.
_MIN_VOUCHER_REFERENCE_LEN = 6

_UTR_SHAPED = re.compile(rf"^[A-Z0-9]{{{NEFT_RTGS_UTR_LEN}}}$")


def _voucher_reference(raw: object, *, narration: object = None) -> tuple[str | None, str | None]:
    """Tally's ``reference_number`` split into ``(utr, rrn)`` by shape.

    A daybook Receipt records whatever reference the payer quoted. When that
    is a 16-character NEFT/RTGS UTR it *is* the UTR and belongs at the top of
    the reference ladder; when it is an invoice number, a POS terminal id or a
    marketplace payout id it is a document reference and rides in ``rrn``,
    matching where ``fc.ingest.bank_csv`` puts the bank statement's own
    ``chq_ref_no``. The two together are what let a bank row and its voucher
    match with no gateway row in between.
    """
    value = str(raw or "").strip()
    if len(value) < _MIN_VOUCHER_REFERENCE_LEN:
        # A Payment voucher routinely leaves the reference column empty and
        # writes the bank narration verbatim into ``narration`` instead — the
        # same string the statement carries. Reading it here is what lets a
        # challan or invoice payment reconcile at all.
        return None, document_reference(str(narration or ""))
    if _UTR_SHAPED.match(value):
        return value, None
    return None, value


def _required(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError(f"missing required field: {key}")
    return str(value).strip()


def _leg(debit_paise: int, credit_paise: int) -> tuple[Direction, int]:
    """A negative leg reverses the natural column meaning: a negative debit
    is effectively a credit of that magnitude, and vice versa (PRD example:
    ``(-)1,24,500.00`` -> ``amount_paise = 12450000`` with direction derived).
    """
    net = debit_paise - credit_paise
    if net > 0:
        return "debit", net
    if net < 0:
        return "credit", -net
    raise ValueError("both debit and credit are zero")
