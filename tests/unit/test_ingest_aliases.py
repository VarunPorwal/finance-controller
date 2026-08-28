from __future__ import annotations

from pathlib import Path

from fc.ingest.aliases import load_aliases, normalise_counterparty

ALIASES_PATH = Path(__file__).resolve().parents[2] / "data" / "aliases.yaml"


def test_aliases_file_has_at_least_ten_entries() -> None:
    table = load_aliases(ALIASES_PATH)
    canonicals = set(table.lookup.values())
    assert len(canonicals) >= 10


def test_known_variants_resolve_to_canonical() -> None:
    table = load_aliases(ALIASES_PATH)
    assert normalise_counterparty("BLNKT/SETTL", table) == "BLINKIT"
    assert normalise_counterparty("Grofers India", table) == "BLINKIT"
    assert normalise_counterparty("kiranakart tech", table) == "ZEPTO"
    assert normalise_counterparty("RZP", table) == "RAZORPAY"


def test_unmatched_name_falls_back_to_normalised_string() -> None:
    table = load_aliases(ALIASES_PATH)
    assert (
        normalise_counterparty("SOME RANDOM MERCHANT PVT LTD", table)
        == "SOME RANDOM MERCHANT PVT LTD"
    )


def test_normalisation_strips_rail_prefix_punctuation_and_whitespace() -> None:
    assert normalise_counterparty("UPI-Zomato Ltd.") == "ZOMATO LTD"
    assert normalise_counterparty("  RAZORPAY   SOFTWARE  ") == "RAZORPAY SOFTWARE"


def test_no_aliases_table_falls_back_to_normalised_string() -> None:
    assert normalise_counterparty("BLNKT/SETTL") == "BLNKT SETTL"
