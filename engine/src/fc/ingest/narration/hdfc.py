"""HDFC NetBanking narration parser — PRD §4.1.4, §6.1.

``NEFT CR:{UTR}/{party}/{ref}``, slash-delimited. The UTR itself is the
RBI-wide NEFT/RTGS scheme (:data:`~fc.ingest.narration.base.NEFT_RTGS_UTR_LEN`
= 16), not an HDFC-specific format.
"""

from __future__ import annotations

import re

from fc.ingest.narration.base import (
    NEFT_RTGS_UTR_LEN,
    ParsedNarration,
    is_truncated,
    parse_common_rail,
)

__all__ = ["HDFC_UTR_LEN", "HdfcNarrationParser"]

#: Kept as an HDFC-scoped alias of the shared national scheme length.
HDFC_UTR_LEN = NEFT_RTGS_UTR_LEN

#: ``party`` and ``ref`` are optional so a truncated narration — cut before
#: either trailing slash is reached — still yields whatever UTR fragment was
#: captured, rather than failing to match at all (PRD §6.1 truncation
#: detection needs the fragment to compare its length against the full shape).
_NEFT = re.compile(
    r"^NEFT\s+(?:CR|DR):(?P<utr>[^/]*)(?:/(?P<party>[^/]*))?(?:/(?P<ref>.*))?$", re.IGNORECASE
)


class HdfcNarrationParser:
    """Bank profile for HDFC NetBanking CSV narrations."""

    def parse(self, narration: str) -> ParsedNarration:
        text = narration.strip()

        match = _NEFT.match(text)
        if match:
            utr = match.group("utr").strip() or None
            return ParsedNarration(
                rail="neft",
                reference=utr,
                counterparty=(match.group("party") or "").strip() or None,
                vpa=None,
                ifsc=None,
                note=(match.group("ref") or "").strip() or None,
                truncated=is_truncated(text, utr, HDFC_UTR_LEN),
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
            truncated=is_truncated(text, None, HDFC_UTR_LEN),
        )
