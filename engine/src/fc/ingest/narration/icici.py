"""ICICI Bank narration parser — PRD §4.1.4, §6.1.

"Mixed" delimiter: a rail prefix, a separator, then a single reference
token, with whatever remains treated as free text. UPI and NACH follow the
shared shapes in ``fc/ingest/narration/base.py``.

The exact separator layout is invented, not sourced from a real ICICI
export — see CLAUDE.md's ingestion notes. The UTR *length* is not a guess:
it's the RBI-wide NEFT/RTGS scheme, identical across every bank.
"""

from __future__ import annotations

import re

from fc.ingest.narration.base import (
    NEFT_RTGS_UTR_LEN,
    ParsedNarration,
    is_truncated,
    parse_common_rail,
)

__all__ = ["ICICI_REF_LEN", "IciciNarrationParser"]

ICICI_REF_LEN = NEFT_RTGS_UTR_LEN

_RAIL_REF = re.compile(
    r"^(?P<rail>NEFT|RTGS)[:\-\s]+(?P<ref>[A-Za-z0-9]+)(?:[\s/\-](?P<rest>.*))?$", re.IGNORECASE
)


class IciciNarrationParser:
    """Bank profile for ICICI Bank narrations."""

    def parse(self, narration: str) -> ParsedNarration:
        text = narration.strip()

        match = _RAIL_REF.match(text)
        if match:
            ref = match.group("ref")
            return ParsedNarration(
                rail=match.group("rail").lower(),
                reference=ref,
                counterparty=(match.group("rest") or "").strip() or None,
                vpa=None,
                ifsc=None,
                note=None,
                truncated=is_truncated(text, ref, ICICI_REF_LEN),
            )

        common = parse_common_rail(text)
        if common is not None:
            return common

        return ParsedNarration(
            rail=None,
            reference=None,
            counterparty=None,
            vpa=None,
            ifsc=None,
            note=text,
            truncated=is_truncated(text, None, ICICI_REF_LEN),
        )
