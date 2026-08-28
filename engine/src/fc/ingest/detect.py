"""Bank statement format detection — PRD §6.1.

MT940 is cut per §0.1: no MT940 signature is checked here.
"""

from __future__ import annotations

from typing import Literal

__all__ = ["BankFormat", "UnsupportedFormat", "detect_bank_format"]

BankFormat = Literal["pdf", "csv"]

_PDF_MAGIC = b"%PDF-"
_CSV_EXTENSIONS = (".csv", ".txt")


class UnsupportedFormat(ValueError):
    """The bytes/filename combination do not match any supported format."""


def detect_bank_format(content: bytes, filename: str) -> BankFormat:
    if content[:5] == _PDF_MAGIC:
        return "pdf"
    if filename.lower().endswith(_CSV_EXTENSIONS):
        return "csv"
    raise UnsupportedFormat(f"cannot detect bank statement format for {filename!r}")
