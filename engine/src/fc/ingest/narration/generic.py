"""Generic narration parser — regex battery over every known reference shape.

PRD §4.1.4, §6.1: used when the bank profile is unknown. Tries each
structured bank format in turn and returns the first (highest-confidence)
match; every structured parser already falls back to the shared rail
patterns (UPI, IMPS, generic RTGS, NACH), so this module effectively tries
all known shapes without duplicating their regexes.
"""

from __future__ import annotations

from fc.ingest.narration.base import NEFT_RTGS_UTR_LEN, ParsedNarration, is_truncated
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.ingest.narration.icici import IciciNarrationParser
from fc.ingest.narration.idfc import IdfcNarrationParser

__all__ = ["GenericNarrationParser"]

_GENERIC_REF_LEN = NEFT_RTGS_UTR_LEN

_STRUCTURED_PARSERS = (HdfcNarrationParser(), IdfcNarrationParser(), IciciNarrationParser())


class GenericNarrationParser:
    """Falls back through every bank profile, in order, then the shared rails."""

    def parse(self, narration: str) -> ParsedNarration:
        text = narration.strip()

        for parser in _STRUCTURED_PARSERS:
            result = parser.parse(text)
            if result.rail is not None:
                return result

        return ParsedNarration(
            rail=None,
            reference=None,
            counterparty=None,
            vpa=None,
            ifsc=None,
            note=text,
            truncated=is_truncated(text, None, _GENERIC_REF_LEN),
        )
