"""IDFC FIRST Bank narration parser — PRD §4.1.4, §6.1.

Hyphen-delimited, with the UTR in segment two: ``NEFT-{UTR}-{party}-{ref}``
or ``RTGS-{UTR}-{party}-{ref}``. UPI references (12 digits) and NACH batch
lines follow the shared shapes in ``fc/ingest/narration/base.py``.

The exact hyphen layout is invented, not sourced from a real IDFC export —
see CLAUDE.md's ingestion notes. The UTR *length* is not a guess: it's the
RBI-wide NEFT/RTGS scheme, identical across every bank.
"""

from __future__ import annotations

import re

from fc.ingest.narration.base import (
    NEFT_RTGS_UTR_LEN,
    ParsedNarration,
    is_truncated,
    parse_common_rail,
)

__all__ = ["IDFC_UTR_LEN", "IdfcNarrationParser"]

IDFC_UTR_LEN = NEFT_RTGS_UTR_LEN

#: ``party`` and ``ref`` are optional so a narration truncated right after
#: the UTR still yields the fragment rather than failing to match at all.
_NEFT_RTGS = re.compile(
    r"^(?P<rail>NEFT|RTGS)-(?P<utr>[^-]+)(?:-(?P<party>[^-]*))?(?:-(?P<ref>.*))?$", re.IGNORECASE
)


class IdfcNarrationParser:
    """Bank profile for IDFC FIRST Bank narrations."""

    def parse(self, narration: str) -> ParsedNarration:
        text = narration.strip()

        match = _NEFT_RTGS.match(text)
        if match:
            utr = match.group("utr").strip()
            return ParsedNarration(
                rail=match.group("rail").lower(),
                reference=utr,
                counterparty=(match.group("party") or "").strip() or None,
                vpa=None,
                ifsc=None,
                note=(match.group("ref") or "").strip() or None,
                truncated=is_truncated(text, utr, IDFC_UTR_LEN),
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
            truncated=is_truncated(text, None, IDFC_UTR_LEN),
        )
