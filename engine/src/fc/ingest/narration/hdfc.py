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

#: A real HDFC NetBanking export dash-delimits instead of colon-delimits, and
#: puts the UTR *last* rather than first: ``NEFT CR-{bank_code}-{party}-
#: {UTR}`` — sometimes with a trailing batch-split or consolidation suffix
#: (``-PART 1/2``, ``-CONSOLIDATED 2 BATCHES``) the colon format's positional
#: regex has no way to anticipate. Tried after ``_NEFT`` fails: rather than a
#: second positional pattern (fragile against however many dash-joined
#: segments a real export uses), this looks for the UTR by *shape* — the
#: RBI-wide 16-character scheme is the only run of that length in the
#: narration, so a bare search finds it regardless of what surrounds it.
#: A row with no UTR at all (an untagged settlement credit) correctly yields
#: no match here, same as the colon format's empty-UTR case.
_NEFT_DASH = re.compile(r"^NEFT\s+(?:CR|DR)-", re.IGNORECASE)
_UTR_TOKEN = re.compile(rf"\b[A-Z0-9]{{{NEFT_RTGS_UTR_LEN}}}\b")


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

        if _NEFT_DASH.match(text):
            token = _UTR_TOKEN.search(text)
            utr = token.group(0) if token else None
            return ParsedNarration(
                rail="neft",
                reference=utr,
                counterparty=None,
                vpa=None,
                ifsc=None,
                note=None,
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
