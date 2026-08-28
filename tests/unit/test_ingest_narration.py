from __future__ import annotations

from fc.ingest.narration.generic import GenericNarrationParser
from fc.ingest.narration.hdfc import HDFC_UTR_LEN, HdfcNarrationParser
from fc.ingest.narration.icici import IciciNarrationParser
from fc.ingest.narration.idfc import IdfcNarrationParser


def test_hdfc_neft_full_utr_not_truncated() -> None:
    parser = HdfcNarrationParser()
    result = parser.parse("NEFT CR:HDFC22680123456/BLINKIT COMMERCE/order 88213")
    assert result.rail == "neft"
    assert result.reference == "HDFC22680123456"
    assert result.counterparty == "BLINKIT COMMERCE"
    assert result.truncated is False


def test_hdfc_neft_truncated_at_exactly_100_chars_with_14_char_utr_fragment() -> None:
    # A 14-char UTR fragment is shorter than HDFC_UTR_LEN (16), so once the
    # narration is >= 98 chars this must flag truncated=True (build DONE WHEN).
    fragment = "HDFC22680123"[:14] if len("HDFC22680123") >= 14 else "HDFC22680123"
    fragment = "HDFC2268012345"[:14]
    assert len(fragment) == 14
    prefix = "NEFT CR:" + fragment + "/"
    party_and_pad = "A" * (100 - len(prefix))
    narration = prefix + party_and_pad
    assert len(narration) == 100

    parser = HdfcNarrationParser()
    result = parser.parse(narration)
    assert result.reference == fragment
    assert len(result.reference) < HDFC_UTR_LEN
    assert result.truncated is True


def test_hdfc_short_narration_never_flagged_truncated() -> None:
    parser = HdfcNarrationParser()
    result = parser.parse("NEFT CR:HD/A/B")
    assert result.truncated is False


def test_idfc_neft_hyphen_delimited() -> None:
    parser = IdfcNarrationParser()
    result = parser.parse("NEFT-IDFB226801234567890123-ZEPTO MARKETPLACE-order 4471")
    assert result.rail == "neft"
    assert result.reference == "IDFB226801234567890123"
    assert result.counterparty == "ZEPTO MARKETPLACE"


def test_icici_rail_prefix_then_reference_token() -> None:
    parser = IciciNarrationParser()
    result = parser.parse("NEFT:ICIC0002268012345678901 LUMEA PERSONAL CARE")
    assert result.rail == "neft"
    assert result.reference == "ICIC0002268012345678901"


def test_upi_narration_parses_hyphenated_vpa() -> None:
    parser = HdfcNarrationParser()
    narration = "UPI-ZOMATO LTD-ZOMATO-ORDER@PAYTM-PYTM0123456-401537805904-ZOMATO PAYMENT"
    result = parser.parse(narration)
    assert result.rail == "upi"
    assert result.counterparty == "ZOMATO LTD"
    assert result.vpa == "ZOMATO-ORDER@PAYTM"
    assert result.ifsc == "PYTM0123456"
    assert result.reference == "401537805904"
    assert result.note == "ZOMATO PAYMENT"


def test_imps_reference_is_rrn_not_utr() -> None:
    parser = HdfcNarrationParser()
    result = parser.parse("IMPS/401537805904/AMIT KUMAR SHARMA VE")
    assert result.rail == "imps"
    assert result.reference == "401537805904"


def test_rtgs_generic_prefix() -> None:
    parser = HdfcNarrationParser()
    result = parser.parse("RBIA2268012345678901234")
    assert result.rail == "rtgs"


def test_nach_batch_line_is_marked_not_decomposed() -> None:
    parser = HdfcNarrationParser()
    result = parser.parse("NACH-BATCH00417-HDFC0000123")
    assert result.rail == "nach"
    assert result.reference == "BATCH00417"
    assert result.truncated is False


def test_generic_parser_tries_every_bank_shape() -> None:
    parser = GenericNarrationParser()
    hdfc_style = parser.parse("NEFT CR:HDFC22680123456/BLINKIT/ref")
    idfc_style = parser.parse("NEFT-IDFB226801234567890123-ZEPTO-ref")
    assert hdfc_style.rail == "neft"
    assert idfc_style.rail == "neft"


def test_generic_parser_unmatched_narration_returns_no_rail() -> None:
    parser = GenericNarrationParser()
    result = parser.parse("CASH DEPOSIT BRANCH")
    assert result.rail is None
    assert result.reference is None
