from __future__ import annotations

import pytest

from fc.ingest.detect import UnsupportedFormat, detect_bank_format


def test_pdf_magic_bytes_detected() -> None:
    assert detect_bank_format(b"%PDF-1.7 rest of file", "statement") == "pdf"


def test_csv_extension_detected() -> None:
    assert detect_bank_format(b"txn_date,narration\n", "hdfc_aug.csv") == "csv"
    assert detect_bank_format(b"txn_date,narration\n", "hdfc_aug.txt") == "csv"


def test_unrecognised_format_raises() -> None:
    with pytest.raises(UnsupportedFormat):
        detect_bank_format(b"not a real file", "statement.xlsx")
