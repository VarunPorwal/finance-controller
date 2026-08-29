"""Verified document extraction — PRD §7.7, differentiator D6.

"The model reads the PDF. Arithmetic decides whether to believe it." These
tests are about the second half of that sentence: what happens when the
arithmetic disagrees.

Three things have to hold, and only the first is obvious:

1. a broken running balance rejects the extraction and persists nothing
2. the rejected response is never written to the cache
3. a retry therefore calls the model again rather than being served the same
   bad extraction back — which is the failure mode a boolean flipped after the
   fact would have left wide open (§7.3, cache poisoning)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fc.config import Config
from fc.ingest.bank_csv import HEADER, parse_bank_csv
from fc.ingest.bank_pdf import ExtractionRejected, ExtractionUnavailable, extract_bank_pdf
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.llm.client import TIERS, LLMClient, RawResponse
from fc.models.ids import deterministic_factory

INGESTED_AT = datetime(2026, 8, 29, tzinfo=UTC)
OPENING_BALANCE = 10_00_000_00
PDF = b"%PDF-1.7\nnot really a pdf, the fake provider never looks\n"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _issue_id() -> Any:
    return deterministic_factory(seed=42, epoch_ms=1_756_339_200_000)


def _rows(*rows: dict[str, Any]) -> str:
    return json.dumps({"rows": list(rows)})


def _row(
    narration: str,
    *,
    deposit: str | None = None,
    withdrawal: str | None = None,
    closing_balance: str,
    txn_date: str = "12/08/2026",
) -> dict[str, Any]:
    return {
        "txn_date": txn_date,
        "value_date": txn_date,
        "narration": narration,
        "chq_ref_no": None,
        "withdrawal": withdrawal,
        "deposit": deposit,
        "closing_balance": closing_balance,
    }


#: Three rows whose running balance reconciles against OPENING_BALANCE.
GOOD = _rows(
    _row(
        "NEFT CR:HDFC20262240001234/LUMEA RETAIL/INV-0912",
        deposit="1,000.00",
        closing_balance="10,01,000.00",
    ),
    _row(
        "NEFT DR:HDFC20262240005678/VENDOR PAYOUT/PO-4471",
        withdrawal="500.00",
        closing_balance="10,00,500.00",
    ),
    _row(
        "UPI/423910238471/PAYMENT FROM RAVI KUMAR", deposit="250.50", closing_balance="10,00,750.50"
    ),
)

#: The middle row's balance is wrong by ₹100 — the kind of thing a model
#: mis-reading one digit produces, and exactly what the check exists to catch.
BROKEN = _rows(
    _row(
        "NEFT CR:HDFC20262240001234/LUMEA RETAIL/INV-0912",
        deposit="1,000.00",
        closing_balance="10,01,000.00",
    ),
    _row(
        "NEFT DR:HDFC20262240005678/VENDOR PAYOUT/PO-4471",
        withdrawal="500.00",
        closing_balance="10,00,600.00",
    ),
    _row(
        "UPI/423910238471/PAYMENT FROM RAVI KUMAR", deposit="250.50", closing_balance="10,00,850.50"
    ),
)


def _plain(amount: str | None) -> str:
    """The same amount as a CSV would carry it.

    A printed statement groups digits (``1,24,500.00``); an unquoted CSV column
    cannot, because the comma is the delimiter — ``parse_csv_line`` would fold
    the overflow into the narration, which is correct behaviour and the wrong
    input for this comparison. ``to_paise`` accepts both spellings, and that is
    exactly why the two paths converge.
    """
    return (amount or "").replace(",", "")


class CountingProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    async def generate(self, spec: Any, **kwargs: Any) -> RawResponse:
        self.calls += 1
        return RawResponse(text=self.text)


def _client(tmp_path: Path, text: str) -> tuple[LLMClient, CountingProvider]:
    provider = CountingProvider(text)
    cfg = Config(llm_cache_dir=str(tmp_path))  # type: ignore[arg-type]
    return LLMClient(cfg, providers={"gemini": provider, "groq": provider}), provider


async def _extract(client: LLMClient) -> Any:
    return await extract_bank_pdf(
        PDF,
        client=client,
        run_id="run_1",
        tenant_id="t_lumea",
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=OPENING_BALANCE,
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )


# --- the accepted path -------------------------------------------------------


@pytest.mark.anyio
async def test_a_reconciling_extraction_becomes_events(tmp_path: Path) -> None:
    client, provider = _client(tmp_path, GOOD)
    extraction = await _extract(client)
    assert provider.calls == 1
    assert extraction.row_count == 3
    events = extraction.ingest.ingest.events
    assert len(events) == 3
    assert extraction.ingest.balanced is True
    assert extraction.ingest.breaks == ()


@pytest.mark.anyio
async def test_amounts_are_converted_by_to_paise_not_by_the_model(tmp_path: Path) -> None:
    """The model transcribes ``1,000.00``; deterministic code makes it 100000.
    Asking for paise would have been asking for arithmetic (hard rule 1)."""
    client, _ = _client(tmp_path, GOOD)
    events = (await _extract(client)).ingest.ingest.events
    assert [e.amount_paise for e in events] == [100_000, 50_000, 25_050]
    assert [e.direction for e in events] == ["credit", "debit", "credit"]


@pytest.mark.anyio
async def test_a_pdf_and_a_csv_of_the_same_statement_produce_identical_events(
    tmp_path: Path,
) -> None:
    """The claim, asserted rather than described.

    Both paths run through ``rows_to_events``, so the narration parse, the
    counterparty alias, the rail-dependent UTR/RRN choice and the idempotency
    hash have exactly one implementation between them. Comparing the two
    outputs field by field is what stops that quietly forking later.
    """
    client, _ = _client(tmp_path, GOOD)
    from_pdf = (await _extract(client)).ingest.ingest.events

    csv_text = "\n".join(
        [
            ",".join(HEADER),
            *(
                ",".join(
                    [
                        r["txn_date"],
                        r["value_date"] or "",
                        r["narration"],
                        r["chq_ref_no"] or "",
                        _plain(r["withdrawal"]),
                        _plain(r["deposit"]),
                        _plain(r["closing_balance"]),
                    ]
                )
                for r in json.loads(GOOD)["rows"]
            ),
        ]
    )
    from_csv = parse_bank_csv(
        csv_text,
        run_id="run_1",
        tenant_id="t_lumea",
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=OPENING_BALANCE,
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    ).ingest.events

    assert len(from_pdf) == len(from_csv) == 3
    # ``raw`` differs by construction (the CSV keeps its own column names) and
    # event ids are minted per call; everything that describes the transaction
    # must be identical.
    compared = {"raw", "event_id"}
    for pdf_event, csv_event in zip(from_pdf, from_csv, strict=True):
        assert pdf_event.model_dump(exclude=compared) == csv_event.model_dump(exclude=compared)

    # And the idempotency hash in particular, since that is what makes
    # re-ingesting the same statement in the other format a no-op.
    assert [e.source_row_id for e in from_pdf] == [e.source_row_id for e in from_csv]


# --- the rejected path (the point of the whole feature) ----------------------


@pytest.mark.anyio
async def test_a_broken_running_balance_rejects_the_extraction_with_the_break_row(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path, BROKEN)
    with pytest.raises(ExtractionRejected) as caught:
        await _extract(client)
    breaks = caught.value.breaks
    assert breaks, "rejected without saying where"
    assert breaks[0].row == 1
    assert breaks[0].expected == 10_00_500_00
    assert breaks[0].found == 10_00_600_00
    assert caught.value.row_count == 3
    assert "row 1" in str(caught.value)


@pytest.mark.anyio
async def test_a_rejected_extraction_writes_nothing_to_the_cache(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, BROKEN)
    with pytest.raises(ExtractionRejected):
        await _extract(client)
    assert not list(tmp_path.rglob("*.json")), "a rejected extraction was cached"


@pytest.mark.anyio
async def test_a_retry_after_a_rejection_calls_the_model_again(tmp_path: Path) -> None:
    """The guard that a boolean set after the fact would not have provided: the
    bad response must not be sitting in the cache waiting to be re-served."""
    client, provider = _client(tmp_path, BROKEN)
    for _ in range(2):
        with pytest.raises(ExtractionRejected):
            await _extract(client)
    assert provider.calls == 2, "the rejected extraction was served from cache on retry"


@pytest.mark.anyio
async def test_an_accepted_extraction_is_cached_and_the_retry_does_not_call_again(
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path, GOOD)
    await _extract(client)
    second = await _extract(client)
    assert provider.calls == 1
    assert second.cached is True


@pytest.mark.anyio
async def test_an_unparseable_row_causes_a_rejection_rather_than_a_silent_gap(
    tmp_path: Path,
) -> None:
    """An excluded row drops out of the balance chain, and the continuity check
    notices. That interaction is intended: a plausible-looking bad extraction
    is exactly what produces one."""
    broken_date = _rows(
        _row(
            "NEFT CR:HDFC20262240001234/LUMEA/INV",
            deposit="1,000.00",
            closing_balance="10,01,000.00",
        ),
        _row(
            "NEFT DR:HDFC20262240005678/VENDOR/PO",
            withdrawal="500.00",
            closing_balance="10,00,500.00",
            txn_date="not a date",
        ),
        _row("UPI/423910238471/RAVI", deposit="250.50", closing_balance="10,00,750.50"),
    )
    client, _ = _client(tmp_path, broken_date)
    with pytest.raises(ExtractionRejected):
        await _extract(client)


@pytest.mark.anyio
async def test_no_multimodal_model_reports_an_action_rather_than_failing_obscurely(
    tmp_path: Path,
) -> None:
    cfg = Config(llm_cache_dir=str(tmp_path), llm_mode="off")  # type: ignore[arg-type]
    client = LLMClient(cfg, providers={})
    with pytest.raises(ExtractionUnavailable, match="CSV"):
        await _extract(client)


@pytest.mark.anyio
async def test_the_capability_gate_never_offers_a_pdf_to_a_text_only_model(
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path, GOOD)
    for key, health in client.health.items():
        if not any(m.multimodal for tier in TIERS.values() for m in tier if m.key == key):
            continue
        health.trip_for_session()
    with pytest.raises(ExtractionUnavailable):
        await _extract(client)
    assert provider.calls == 0
