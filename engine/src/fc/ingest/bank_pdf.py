"""Verified document extraction — PRD §7.7, differentiator D6.

A multimodal model reads the statement. Arithmetic decides whether to believe
it. If the running balance does not reconcile, the extraction is rejected and
nothing is persisted.

That sentence is the whole design, and the ordering in :func:`extract_bank_pdf`
is what makes it true rather than claimed:

1. the model transcribes rows, against a response schema
2. amounts — strings, as printed — go through :func:`fc.models.money.to_paise`,
   which is deterministic and tested; the model is never asked to compute paise
3. ``verify_balance_continuity`` (written in Prompt 2, unchanged) checks
   ``bal[n] == bal[n-1] + deposit - withdrawal`` for every row
4. only then is the extraction confirmed — and confirming is also the only
   thing that writes it to the LLM cache, so a rejected extraction cannot be
   re-served on a retry (§7.3, cache poisoning)
5. rows become events through the same function the CSV path uses, so a PDF and
   a CSV of the same statement are indistinguishable downstream

A rejected extraction is a *correct outcome*, not a failure. The break location
is reported so a human can see which row the model got wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from fc.ingest.aliases import AliasTable
from fc.ingest.bank_csv import BankIngestResult, RawBankRow, rows_to_events
from fc.ingest.narration.base import NarrationParser
from fc.ingest.validators import (
    Break,
    IngestResult,
    Rejection,
    reject,
    verify_balance_continuity,
)
from fc.llm.client import LLMClient, TerminalUnavailable, load_prompt
from fc.llm.schemas import MULTIMODAL, ExtractionOut, PdfRow
from fc.models.money import to_paise

__all__ = ["ExtractionRejected", "ExtractionUnavailable", "extract_bank_pdf"]


class ExtractionRejected(Exception):
    """The transcription did not survive the balance check. Nothing persisted.

    Carries every break in the file, not just the first —
    ``verify_balance_continuity`` resyncs to each row's own stated balance, so a
    single mis-read digit shows as one break rather than corrupting every row
    after it.
    """

    def __init__(self, breaks: tuple[Break, ...], *, row_count: int) -> None:
        first = breaks[0] if breaks else None
        super().__init__(
            f"running balance does not reconcile: {len(breaks)} break(s) in {row_count} rows"
            + (
                f", first at row {first.row} (expected {first.expected}, found {first.found})"
                if first
                else ""
            )
        )
        self.breaks = breaks
        self.row_count = row_count


class ExtractionUnavailable(Exception):
    """No multimodal model was reachable. The CSV path needs none — say so."""


@dataclass(frozen=True)
class PdfExtraction:
    """The accepted result, plus what it took to get there (for ``llm_calls``)."""

    ingest: BankIngestResult
    model: str
    cached: bool
    row_count: int


async def extract_bank_pdf(
    pdf: bytes,
    *,
    client: LLMClient,
    run_id: str,
    tenant_id: str,
    narration_parser: NarrationParser,
    opening_balance_paise: int,
    issue_id: Callable[[str], str],
    ingested_at: datetime,
    aliases: AliasTable | None = None,
) -> PdfExtraction:
    """Extract, verify, and only then believe.

    Raises :class:`ExtractionRejected` when the arithmetic disagrees with the
    model, and :class:`ExtractionUnavailable` when no multimodal model could be
    reached at all. Neither leaves anything persisted or cached.
    """
    try:
        result = await client.call(
            "pdf_extract",
            prompt=load_prompt("extraction"),
            tenant_id=tenant_id,
            run_id=run_id,
            schema=ExtractionOut,
            pdf=pdf,
            requires=MULTIMODAL,
            timeout_s=120.0,
        )
    except TerminalUnavailable as exc:
        raise ExtractionUnavailable(str(exc)) from exc

    extracted = ExtractionOut.model_validate_json(result.text)
    rejections: list[Rejection] = []
    rows = _to_raw_rows(extracted.rows, rejections)

    balanced, breaks = verify_balance_continuity(rows, opening_balance_paise)
    if not balanced:
        # The deterministic check disagreed. Log verified=false, cache nothing,
        # persist nothing, and hand the break rows back so a person can look at
        # the ones the model got wrong.
        client.reject(result, tenant_id=tenant_id, run_id=run_id)
        raise ExtractionRejected(tuple(breaks), row_count=len(rows))

    # Only now does this response become cacheable.
    confirmed = client.confirm(result, tenant_id=tenant_id, run_id=run_id)

    events = rows_to_events(
        rows,
        run_id=run_id,
        tenant_id=tenant_id,
        narration_parser=narration_parser,
        issue_id=issue_id,
        ingested_at=ingested_at,
        aliases=aliases,
        rejections=rejections,
    )
    return PdfExtraction(
        ingest=BankIngestResult(
            ingest=IngestResult(events=tuple(events), rejections=tuple(rejections)),
            balanced=True,
            breaks=(),
        ),
        model=confirmed.model,
        cached=confirmed.cached,
        row_count=len(rows),
    )


def _to_raw_rows(rows: list[PdfRow], rejections: list[Rejection]) -> list[RawBankRow]:
    """Transcribed strings to integer paise, deterministically.

    A row whose amounts or dates cannot be parsed is rejected and *excluded*,
    never repaired — which means it also drops out of the balance chain, and
    the continuity check will notice. That is the intended interaction: an
    unparseable row is exactly the kind of thing a plausible-looking bad
    extraction produces, and it should cause a rejection rather than a silent
    gap.
    """
    parsed: list[RawBankRow] = []
    for i, row in enumerate(rows):
        try:
            parsed.append(
                RawBankRow(
                    txn_date=_parse_ddmmyyyy(row.txn_date),
                    value_date=_parse_ddmmyyyy(row.value_date) if row.value_date else None,
                    narration=row.narration.strip(),
                    chq_ref_no=(row.chq_ref_no or "").strip() or None,
                    withdrawal_paise=_optional_amount(row.withdrawal),
                    deposit_paise=_optional_amount(row.deposit),
                    closing_balance_paise=to_paise(row.closing_balance),
                    raw=row.model_dump(mode="json", exclude_none=False),
                )
            )
        except (ValueError, TypeError) as exc:
            reject(rejections, f"pdf_row_{i}", f"unparseable extracted row: {exc}")
    return parsed


def _parse_ddmmyyyy(text: str) -> date:
    return datetime.strptime(text.strip(), "%d/%m/%Y").date()


def _optional_amount(text: str | None) -> int | None:
    stripped = (text or "").strip()
    return to_paise(stripped) if stripped else None
