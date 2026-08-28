from __future__ import annotations

from datetime import UTC, datetime

from fc.ingest.tally import parse_tally_csv, parse_tally_xml
from fc.models.ids import deterministic_factory

INGESTED_AT = datetime(2026, 8, 28, 6, 0, tzinfo=UTC)


def _issue_id():
    return deterministic_factory(seed=42, epoch_ms=1_756_339_200_000)


CSV_CONTENT = (
    "voucher_date,voucher_type,voucher_number,ledger_name,party_ledger_name,debit,credit,"
    "narration,reference_number,cost_centre,gstin,voucher_guid\n"
    '2026-08-14,Receipt,RCP/2026-27/00412,Razorpay Settlement A/c,Razorpay,"(-)1,24,500.00",,'
    "Settlement credit order LUM-4471,LUM-4471,Own Store,23AAAAA0000A1Z5,"
    "b6b1e1c2-1234-4a5b-9c1d-0000000000aa\n"
)


def test_tally_negative_prefix_and_indian_grouping_yield_correct_paise_and_direction() -> None:
    result = parse_tally_csv(
        CSV_CONTENT,
        run_id="run_1",
        tenant_id="t_lumea",
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert len(result.rejections) == 0
    event = result.events[0]
    assert event.amount_paise == 12_450_000
    assert event.direction == "credit"


def test_voucher_guid_is_the_idempotency_key() -> None:
    result = parse_tally_csv(
        CSV_CONTENT,
        run_id="run_1",
        tenant_id="t_lumea",
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    event = result.events[0]
    assert event.voucher_guid == "b6b1e1c2-1234-4a5b-9c1d-0000000000aa"
    assert event.source_row_id == "b6b1e1c2-1234-4a5b-9c1d-0000000000aa"


def test_reparsing_same_file_twice_yields_identical_source_row_ids() -> None:
    first = parse_tally_csv(
        CSV_CONTENT,
        run_id="run_1",
        tenant_id="t_lumea",
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    second = parse_tally_csv(
        CSV_CONTENT,
        run_id="run_1",
        tenant_id="t_lumea",
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert first.events[0].source_row_id == second.events[0].source_row_id


def test_unknown_voucher_type_is_rejected() -> None:
    bad = CSV_CONTENT.replace("Receipt", "Estimate")
    result = parse_tally_csv(
        bad, run_id="run_1", tenant_id="t_lumea", issue_id=_issue_id(), ingested_at=INGESTED_AT
    )
    assert len(result.events) == 0
    assert len(result.rejections) == 1


XML_CONTENT = """<DAYBOOK>
  <VOUCHER>
    <DATE>2026-08-14</DATE>
    <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
    <VOUCHERNUMBER>PMT/2026-27/00091</VOUCHERNUMBER>
    <LEDGERNAME>Bank Charges</LEDGERNAME>
    <PARTYLEDGERNAME>Razorpay</PARTYLEDGERNAME>
    <DEBIT>1234.50</DEBIT>
    <CREDIT></CREDIT>
    <NARRATION>MDR on settlement</NARRATION>
    <GUID>c7c2f2d3-2345-4a5b-9c1d-0000000000bb</GUID>
  </VOUCHER>
</DAYBOOK>"""


def test_xml_common_tag_names_are_accepted() -> None:
    result = parse_tally_xml(
        XML_CONTENT,
        run_id="run_1",
        tenant_id="t_lumea",
        issue_id=_issue_id(),
        ingested_at=INGESTED_AT,
    )
    assert len(result.rejections) == 0
    event = result.events[0]
    assert event.direction == "debit"
    assert event.amount_paise == 123_450
    assert event.voucher_guid == "c7c2f2d3-2345-4a5b-9c1d-0000000000bb"
    assert event.ledger_account == "Bank Charges"
