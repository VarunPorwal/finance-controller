"""Shared narration-parsing types, common rail patterns, truncation detection.

PRD §4.1.4, §6.1. Truncation detection is the single most impactful narration
behaviour in real deployments: HDFC NetBanking narration truncates at ~100
characters, cutting the UTR mid-string, and a truncated reference must be
excluded from exact matching downstream rather than matched wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "IFSC_PATTERN",
    "NARRATION_TRUNCATION_LEN",
    "NEFT_RTGS_UTR_LEN",
    "NarrationParser",
    "ParsedNarration",
    "is_truncated",
    "parse_common_rail",
]

#: PRD §6.1: a narration this long or longer is suspected truncated.
NARRATION_TRUNCATION_LEN = 98

#: The NEFT/RTGS UTR shape is an RBI-wide scheme, not a per-bank format: a
#: 4-character IFSC prefix, a 2-digit year, a 3-digit day-of-year and a
#: 7-digit sequence — 4 + 2 + 3 + 7 = 16 characters, identical across every
#: bank (PRD §4.1.4).
NEFT_RTGS_UTR_LEN = 16

IFSC_PATTERN = re.compile(r"[A-Z]{4}0[A-Z0-9]{6}")

#: ``UPI-{payee}-{vpa}-{ifsc}-{ref}-{note}``. The vpa itself may contain a
#: hyphen (real merchant VPAs commonly do, e.g. ``zomato-order@paytm``), so it
#: is bounded on the right by the IFSC shape rather than split naively.
_UPI = re.compile(
    r"^UPI-(?P<payee>.+?)-(?P<vpa>[\w.\-]+@[A-Za-z]+)-(?P<ifsc>[A-Z]{4}0[A-Z0-9]{6})-"
    r"(?P<ref>\d{1,12})(?:-(?P<note>.*))?$"
)

#: ``IMPS/{ref}`` or ``IMPS CR {ref}``; ref is a 12-digit RRN, not a UTR.
_IMPS = re.compile(r"^IMPS[/\s](?:CR\s+)?(?P<ref>\d{1,12})(?:[/\s](?P<party>.+))?$")

#: RBI RTGS UTRs universally start with the sponsor code ``RBIA``. The
#: reference itself is not length-bounded here — truncation is judged
#: against the expected length separately, in :func:`is_truncated`.
_RTGS = re.compile(r"^(?P<ref>RBIA[0-9A-Z]*)(?:[\s/\-](?P<rest>.*))?$")

#: One line covers 200-500 mandates; only the batch reference and sponsor
#: bank code are extractable, never the individual mandates (PRD §4.1.4).
_NACH = re.compile(
    r"^NACH[\s\-:]+(?P<batch_ref>[^\s\-]+)(?:[\s\-]+(?P<sponsor_bank>.*))?$", re.IGNORECASE
)


@dataclass(frozen=True)
class ParsedNarration:
    """The structured shape a raw bank narration decomposes into."""

    rail: str | None
    reference: str | None
    counterparty: str | None
    vpa: str | None
    ifsc: str | None
    note: str | None
    truncated: bool


class NarrationParser(Protocol):
    def parse(self, narration: str) -> ParsedNarration: ...


def is_truncated(narration: str, reference: str | None, expected_len: int) -> bool:
    """PRD §6.1: ``len(narration) >= 98`` and the reference is shorter than
    the full shape expected for its rail.

    Only evaluated once a reference-extraction attempt has been made; the
    caller supplies the expected length for the rail/bank combination it
    just tried, since that shape is bank-specific (see ``fc/ingest/narration/
    hdfc.py`` for why HDFC's own UTR length differs from the generic one).
    """
    if len(narration) < NARRATION_TRUNCATION_LEN:
        return False
    if reference is None:
        return True
    return len(reference) < expected_len


def parse_common_rail(narration: str) -> ParsedNarration | None:
    """Rail patterns that are the same shape across every bank: UPI, IMPS,
    generic RBI RTGS, NACH. Tried by every bank-specific parser as a fallback
    after its own NEFT/RTGS format fails to match.
    """
    text = narration.strip()

    match = _UPI.match(text)
    if match:
        ref = match.group("ref")
        return ParsedNarration(
            rail="upi",
            reference=ref,
            counterparty=match.group("payee").strip() or None,
            vpa=match.group("vpa"),
            ifsc=match.group("ifsc"),
            note=(match.group("note") or "").strip() or None,
            truncated=is_truncated(text, ref, 12),
        )

    match = _IMPS.match(text)
    if match:
        ref = match.group("ref")
        return ParsedNarration(
            rail="imps",
            reference=ref,
            counterparty=(match.group("party") or "").strip() or None,
            vpa=None,
            ifsc=None,
            note=None,
            truncated=is_truncated(text, ref, 12),
        )

    match = _RTGS.match(text)
    if match:
        ref = match.group("ref")
        return ParsedNarration(
            rail="rtgs",
            reference=ref,
            counterparty=None,
            vpa=None,
            ifsc=None,
            note=(match.group("rest") or "").strip() or None,
            truncated=is_truncated(text, ref, NEFT_RTGS_UTR_LEN),
        )

    match = _NACH.match(text)
    if match:
        return ParsedNarration(
            rail="nach",
            reference=match.group("batch_ref"),
            counterparty=match.group("sponsor_bank"),
            vpa=None,
            ifsc=None,
            note=text,
            # A NACH line is marked, never decomposed into mandates (PRD:
            # "not parseable ... without the NPCI file"), so truncation of
            # the batch reference is not evaluated.
            truncated=False,
        )

    return None
