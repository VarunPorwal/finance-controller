from __future__ import annotations

from datetime import UTC, datetime

from fc.ingest.bank_csv import parse_bank_csv, parse_csv_line
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.models.ids import deterministic_factory
from fc.models.money import to_paise

INGESTED_AT = datetime(2026, 8, 28, 6, 0, tzinfo=UTC)
HEADER = (
    "txn_date",
    "value_date",
    "narration",
    "chq_ref_no",
    "withdrawal_amt",
    "deposit_amt",
    "closing_balance",
)


def _issue_id():
    return deterministic_factory(seed=42, epoch_ms=1_756_339_200_000)


def test_narration_comma_overflow_absorbed_without_error() -> None:
    line = "14/08/2026,14/08/2026,NEFT CR:HD/PARTY, WITH A COMMA/ref,0,,5000.00,110000.00"
    fields = parse_csv_line(line, HEADER)
    assert fields["narration"] == "NEFT CR:HD/PARTY, WITH A COMMA/ref"
    assert fields["closing_balance"] == "110000.00"


def test_bank_csv_row_with_comma_in_narration_parses_via_full_pipeline() -> None:
    content = (
        "txn_date,value_date,narration,chq_ref_no,withdrawal_amt,deposit_amt,closing_balance\n"
        "14/08/2026,14/08/2026,NEFT CR:HDFC22680123456/BLINKIT, COMMERCE/ref,0,,5000.00,105000.00\n"
    )
    result = parse_bank_csv(
        content,
        run_id="run_1",
        tenant_id="t_lumea",
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=to_paise("100000.00"),
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert len(result.ingest.rejections) == 0
    event = result.ingest.events[0]
    assert "BLINKIT, COMMERCE" in event.raw_narration
    assert event.amount_paise == to_paise("5000.00")
    assert event.direction == "credit"


def test_withdrawal_and_deposit_columns_never_collapsed() -> None:
    content = (
        "txn_date,value_date,narration,chq_ref_no,withdrawal_amt,deposit_amt,closing_balance\n"
        "14/08/2026,14/08/2026,NEFT CR:HDFC22680123456/BLINKIT/ref,0,,5000.00,105000.00\n"
        "15/08/2026,15/08/2026,ATM WDL,0,1000.00,,104000.00\n"
    )
    result = parse_bank_csv(
        content,
        run_id="run_1",
        tenant_id="t_lumea",
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=to_paise("100000.00"),
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert result.balanced is True
    credit, debit = result.ingest.events
    assert credit.direction == "credit" and credit.amount_paise == to_paise("5000.00")
    assert debit.direction == "debit" and debit.amount_paise == to_paise("1000.00")


def test_chq_ref_no_literal_zero_is_preserved_not_treated_as_missing() -> None:
    content = (
        "txn_date,value_date,narration,chq_ref_no,withdrawal_amt,deposit_amt,closing_balance\n"
        "14/08/2026,14/08/2026,NEFT CR:HDFC22680123456/BLINKIT/ref,0,,5000.00,105000.00\n"
    )
    result = parse_bank_csv(
        content,
        run_id="run_1",
        tenant_id="t_lumea",
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=to_paise("100000.00"),
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert result.ingest.events[0].raw["chq_ref_no"] == "0"


def test_broken_running_balance_returns_all_breaks_not_just_the_first() -> None:
    content = (
        "txn_date,value_date,narration,chq_ref_no,withdrawal_amt,deposit_amt,closing_balance\n"
        "14/08/2026,14/08/2026,NEFT CR:HDFC22680123456/BLINKIT/ref,0,,5000.00,999999.00\n"
        "15/08/2026,15/08/2026,ATM WDL,0,1000.00,,888888.00\n"
    )
    result = parse_bank_csv(
        content,
        run_id="run_1",
        tenant_id="t_lumea",
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=to_paise("100000.00"),
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert result.balanced is False
    assert len(result.breaks) == 2
    assert result.breaks[0].row == 0
    assert result.breaks[0].expected == to_paise("105000.00")
    assert result.breaks[0].found == to_paise("999999.00")
    assert result.breaks[1].row == 1


def test_value_date_diverges_from_txn_date() -> None:
    content = (
        "txn_date,value_date,narration,chq_ref_no,withdrawal_amt,deposit_amt,closing_balance\n"
        "14/08/2026,16/08/2026,NEFT CR:HDFC22680123456/BLINKIT/ref,0,,5000.00,105000.00\n"
    )
    result = parse_bank_csv(
        content,
        run_id="run_1",
        tenant_id="t_lumea",
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=to_paise("100000.00"),
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    event = result.ingest.events[0]
    assert event.txn_date.day == 14
    assert event.value_date is not None
    assert event.value_date.day == 16


def test_truly_malformed_row_is_rejected_and_logged_not_dropped_silently() -> None:
    content = (
        "txn_date,value_date,narration,chq_ref_no,withdrawal_amt,deposit_amt,closing_balance\n"
        "14/08/2026,14/08/2026\n"  # far too few fields, not a comma-overflow case
    )
    result = parse_bank_csv(
        content,
        run_id="run_1",
        tenant_id="t_lumea",
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=to_paise("100000.00"),
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert len(result.ingest.events) == 0
    assert len(result.ingest.rejections) == 1
