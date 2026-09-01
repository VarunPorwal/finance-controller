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
    "INTERNAL_NARRATION_TAGS",
    "NARRATION_TRUNCATION_LEN",
    "NEFT_RTGS_UTR_LEN",
    "NarrationParser",
    "ParsedNarration",
    "is_internal_tag",
    "is_truncated",
    "document_reference",
    "narration_tag",
    "parse_common_rail",
    "parse_dash_narration",
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


#: Statement tags that name a bank-internal movement rather than a
#: counterparty: an account charge, credit interest, a tax challan paid from
#: the account, a branch cash deposit, a returned-instrument fee. The text
#: after such a tag describes the *charge*, not a party, so extracting it as a
#: counterparty would invent a trading relationship out of a fee line. Generic
#: Indian statement vocabulary, not a per-bank format.
INTERNAL_NARRATION_TAGS: tuple[str, ...] = (
    "CHARGES",
    "CHRG",
    "INT CR",
    "INT DR",
    "MISC",
    "CASH DEP",
    "CASH WDL",
    "ATM",
    "GST PMT",
    "TDS PAYMENT",
    "SI ",
)

#: Tokens that introduce a document/terminal reference *inside* a party
#: segment: ``PINELABS TID PL40218881`` names PINELABS, and everything from
#: ``TID`` onward is the terminal, not part of the name.
_REFERENCE_LEAD_TOKENS = frozenset(
    {"TID", "REF", "ACC", "AC", "A/C", "CA", "POLICY", "CHALLAN", "UTR", "RRN", "MID", "NO"}
)

#: A segment that is a bare reference: no lowercase, no spaces, and a run of
#: at least four digits. ``HDFCN26010300001`` and ``26011234567890`` are
#: references; ``SHREE PACKAGING LLP`` and ``ADS JAN26`` are not.
_BARE_REFERENCE = re.compile(r"^[A-Z0-9/]*\d{4,}[A-Z0-9/]*$")

#: ``{TAG}-{segment}-{segment}...``. The dash-delimited shape every major
#: Indian bank's NetBanking export uses outside the colon-delimited NEFT
#: format: the tag names the rail or the statement category, and the segments
#: that follow carry, in no fixed order, an IFSC, the party and a reference.
_DASH_RAILS: tuple[tuple[str, str], ...] = (
    ("NEFT", "neft"),
    ("RTGS", "rtgs"),
    ("IMPS", "imps"),
    ("UPI", "upi"),
    ("NACH", "nach"),
    ("ACH", "nach"),
)


def _strip_reference_tail(segment: str) -> str:
    """``PINELABS TID PL40218881`` -> ``PINELABS``."""
    tokens = segment.split()
    for index, token in enumerate(tokens):
        if token.upper() in _REFERENCE_LEAD_TOKENS and index > 0:
            return " ".join(tokens[:index])
    return segment


#: A token long enough, and digit-heavy enough, to name one document: a challan
#: number, an invoice number, a policy number, a terminal id. Eight characters
#: with a four-digit run is the threshold — below it a shared value proves
#: nothing, since two unrelated rows can both carry ``JAN26``.
_DOCUMENT_TOKEN = re.compile(r"[A-Z0-9][A-Z0-9/\-]{6,}")
_MIN_DOCUMENT_TOKEN_LEN = 8


def document_reference(narration: str) -> str | None:
    """The document this narration names, when it names exactly one.

    A tax challan, a policy, an invoice: the number is written into the
    narration and nowhere else, and both sides of the account write the *same*
    narration — the bank because it is describing the instrument, the daybook
    because whoever entered the voucher copied it across. That makes it a
    joinable reference, which matters because rows like a GST challan carry no
    counterparty a narration parser could extract and no reference column: with
    nothing identifying, stage 5 correctly abstains, and the same ₹1,28,740 is
    then reported twice, once as an unbooked bank debit and once as a ledger
    entry with no bank leg.

    Exactly one, or none: a narration naming two documents identifies itself
    with neither, the same rule ``LedgerRefs.identity_claims`` applies to
    settlement ids. Extraction is not attribution.
    """
    text = narration.strip().upper()
    found = {
        token
        for token in _DOCUMENT_TOKEN.findall(text)
        if len(token) >= _MIN_DOCUMENT_TOKEN_LEN and re.search(r"\d{4,}", token)
    }
    if len(found) != 1:
        return None
    return str(next(iter(found)))


def narration_tag(narration: str) -> str:
    """The leading statement tag: everything before the first dash, upper-cased.

    ``NEFT CR-...`` -> ``NEFT CR``; ``CHARGES-NEFT OUTWARD JAN26`` ->
    ``CHARGES``. Read by lane assignment, which needs the category the bank
    itself put on the row.
    """
    head = narration.strip().split("-", 1)[0]
    return " ".join(head.upper().split())


def is_internal_tag(narration: str) -> bool:
    """Whether the row's own tag names a bank-internal movement."""
    tag = narration_tag(narration)
    return any(tag.startswith(prefix.strip()) for prefix in INTERNAL_NARRATION_TAGS)


def parse_dash_narration(narration: str) -> ParsedNarration | None:
    """The generic dash-delimited shape, decomposed by *content* not position.

    Position is not usable: a real export writes ``NEFT CR-{ifsc}-{party}-
    {utr}`` on one row and ``POS SETTLEMENT CR-{party} TID {terminal}-{note}``
    on the next, and a positional regex for one silently mis-reads the other.
    So each segment is judged on its own shape — an IFSC, a bare reference, or
    a party — and the first segment that is none of the former is the party.

    Returns ``None`` when the narration carries no dash at all, so a caller can
    fall through to its own formats.
    """
    text = narration.strip()
    if "-" not in text:
        return None

    segments = [segment.strip() for segment in text.split("-")]
    tag = " ".join(segments[0].upper().split())

    rail: str | None = None
    for prefix, name in _DASH_RAILS:
        if tag.startswith(prefix):
            rail = name
            break

    ifsc: str | None = None
    counterparty: str | None = None
    for segment in segments[1:]:
        if not segment:
            continue
        if ifsc is None and IFSC_PATTERN.fullmatch(segment):
            ifsc = segment
            continue
        if _BARE_REFERENCE.fullmatch(segment):
            continue
        if counterparty is None:
            counterparty = _strip_reference_tail(segment) or None

    if is_internal_tag(text):
        counterparty = None

    token = re.search(rf"\b[A-Z0-9]{{{NEFT_RTGS_UTR_LEN}}}\b", text)
    reference = token.group(0) if token else document_reference(text)

    return ParsedNarration(
        rail=rail,
        reference=reference,
        counterparty=counterparty,
        vpa=None,
        ifsc=ifsc,
        note=tag,
        truncated=is_truncated(text, reference, NEFT_RTGS_UTR_LEN)
        if rail in ("neft", "rtgs")
        else False,
    )
