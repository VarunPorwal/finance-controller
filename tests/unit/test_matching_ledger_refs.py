"""Ledger narration yields gateway references, and says when it cannot.

Two behaviours carry weight. A narration citing several ids of one kind names
itself with none of them - ``Rolling reserve release settlement setl_B for
setl_A`` merged two settlements into one match until this was enforced. And a
row that yields nothing is counted and kept, never dropped, so the exception
pipeline can tell "the matcher missed it" from "there was nothing to match on".
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from fc.matching.ledger_refs import extract_refs, index_ledger_refs
from fc.models.transaction import Source, TransactionEvent

_AT = datetime(2026, 8, 1, tzinfo=UTC)
_ULID = "01KT07NV33WV987DMTMF64Y936"
_ULID2 = "01KT07NVH5KTVYN9PVWMBFQW16"


def _ledger(event_id: str, narration: str | None, source: Source = "ledger") -> TransactionEvent:
    return TransactionEvent(
        event_id=event_id,
        run_id="run",
        tenant_id="t",
        source=source,
        source_row_id=event_id,
        amount_paise=1000,
        direction="debit",
        txn_date=date(2026, 6, 1),
        raw_narration=narration,
        raw={},
        ingested_at=_AT,
    )


def test_extracts_an_order_reference_from_a_sales_narration() -> None:
    refs = extract_refs(f"Sales order order_{_ULID}")
    assert refs.order_ids == (f"order_{_ULID}",)
    assert refs.settlement_ids == ()


def test_extracts_a_settlement_reference_from_a_receipt_narration() -> None:
    refs = extract_refs(f"Settlement credit setl_{_ULID} 6 orders")
    assert refs.settlement_ids == (f"setl_{_ULID}",)


def test_ignores_tokens_using_letters_the_ulid_alphabet_excludes() -> None:
    """Crockford base32 has no I, L, O or U, so such a token is not an id."""
    assert extract_refs("Sales order order_01KT07NV33WV987DMTMF64Y93I").order_ids == ()
    assert extract_refs("Sales order order_OILU7NV33WV987DMTMF64Y936").order_ids == ()


def test_ignores_a_bare_ulid_with_no_entity_prefix() -> None:
    assert extract_refs(_ULID).empty


def test_deduplicates_repeated_mentions() -> None:
    refs = extract_refs(f"order_{_ULID} and again order_{_ULID}")
    assert refs.order_ids == (f"order_{_ULID}",)


def test_a_narration_naming_two_settlements_claims_neither() -> None:
    narration = f"Rolling reserve release settlement setl_{_ULID} for setl_{_ULID2}"
    refs = extract_refs(narration)
    assert len(refs.settlement_ids) == 2
    assert refs.identity_claims().settlement_ids == ()
    assert refs.identity_claims().empty


def test_one_settlement_and_one_order_are_both_identity_claims() -> None:
    refs = extract_refs(f"Settlement setl_{_ULID} for order_{_ULID2}")
    claims = refs.identity_claims()
    assert claims.settlement_ids == (f"setl_{_ULID}",)
    assert claims.order_ids == (f"order_{_ULID2}",)


def test_rows_with_no_reference_are_counted_and_kept() -> None:
    index = index_ledger_refs(
        [
            _ledger("a", f"Sales order order_{_ULID}"),
            _ledger("b", "Bank charges for the period"),
            _ledger("c", None),
        ]
    )
    assert index.without_reference == ("b", "c")
    assert set(index.refs) == {"a", "b", "c"}


def test_rows_with_an_ambiguous_narration_are_counted_separately() -> None:
    index = index_ledger_refs([_ledger("a", f"release settlement setl_{_ULID} for setl_{_ULID2}")])
    assert index.ambiguous == ("a",)
    assert index.without_reference == ()
    assert index.identity_for_event("a").empty


def test_only_ledger_rows_are_indexed() -> None:
    index = index_ledger_refs([_ledger("bank", f"order_{_ULID}", source="bank")])
    assert index.refs == {}
