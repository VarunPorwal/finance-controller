"""Shared constants, money/text helpers, and the 16 failure-mode registry.

PRD §4.1.8, §0.3, §2.6 D1. Every scenario below is one of the sixteen the
generator must produce; each carries a target count (scaled by ``N``) and the
bucket/ground-truth label the corresponding rows should carry once matching
runs against them. ``razorpay_gen``, ``bank_gen`` and ``tally_gen`` import
from here rather than duplicating money/date/id plumbing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from fc.models.money import RUPEE, fmt_inr

__all__ = [
    "EPOCH_MS",
    "EXTRA_SCENARIOS",
    "INGESTED_AT",
    "MAX_SUBSET_N",
    "MDR_RATES",
    "METHOD_MIX",
    "OPENING_BALANCE_PAISE",
    "PERIOD_END",
    "PERIOD_START",
    "PLATFORM_COMMISSION",
    "RESERVE_RATE",
    "SCENARIO_3_BATCH_SIZES",
    "SCENARIOS",
    "TENANT_ID",
    "Order",
    "Scenario",
    "Settlement",
    "compute_totals",
    "effective_rate",
    "fee_and_tax",
    "fiscal_year_label",
    "lognormal_amount_paise",
    "make_utr",
    "paise_to_rupee_str",
    "round_paise",
    "scenario_counts",
    "to_tally_amount_str",
]

TENANT_ID = "t_lumea"

# A fixed window, not wall-clock: three months ending on the date CLAUDE.md
# records as "today" for this repo. Reserve releases (T+90) can land after it.
PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 8, 28)
INGESTED_AT = datetime(2026, 8, 28, 6, 0, tzinfo=UTC)
EPOCH_MS = int(datetime(2026, 6, 1, tzinfo=UTC).timestamp() * 1000)

OPENING_BALANCE_PAISE = 10_00_000_00  # ₹10,00,000.00

# PRD §0.3.
METHOD_MIX: dict[str, Decimal] = {
    "upi": Decimal("0.52"),
    "card": Decimal("0.27"),
    "netbanking": Decimal("0.11"),
    "wallet": Decimal("0.07"),
    "emi": Decimal("0.03"),
}
MDR_RATES: dict[str, Decimal] = {
    "upi": Decimal("0.000"),
    "card": Decimal("0.020"),
    "netbanking": Decimal("0.009"),
    "wallet": Decimal("0.018"),
    "emi": Decimal("0.024"),
}
GST_ON_MDR = Decimal("0.18")
TDS_194O = Decimal("0.01")
RESERVE_RATE = Decimal("0.05")
PLATFORM_COMMISSION = Decimal("0.18")

#: engine/src/fc/config.py's ``max_subset_n`` default (PRD §6.4 stage 4). Not
#: imported from there — the generator stays decoupled from env-driven config
#: — but scenario 3's largest batch is sized one above it on purpose, so a
#: candidate set this large exists in the corpus for stage 4's cap/timeout.
MAX_SUBSET_N = 40

#: One bank credit against 14 Razorpay rows (PRD §4.1.8 #3), plus two more
#: scales so the settlement-id fast path, an ordinary-large batch, and a
#: batch past the subset-sum cap are all represented in the corpus.
SCENARIO_3_BATCH_SIZES: tuple[int, ...] = (14, 25, MAX_SUBSET_N + 1)

_TWO_PLACES = Decimal("0.01")


def round_paise(value: Decimal) -> int:
    """Round a paise-denominated ``Decimal`` to the nearest paise, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paise_to_rupee_str(paise: int) -> str:
    """Plain (ungrouped) two-decimal rupee string, as HDFC's CSV export uses."""
    return str((Decimal(paise) / 100).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


def to_tally_amount_str(paise: int) -> str:
    """Indian-grouped rupee string; negative values use Tally's ``(-)`` prefix,
    never a minus sign (CLAUDE.md gotcha)."""
    grouped = fmt_inr(abs(paise))[len(RUPEE) :]
    return f"(-){grouped}" if paise < 0 else grouped


def fiscal_year_label(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def make_utr(prefix: str, d: date, seq: int) -> str:
    """16-char RBI-wide NEFT/RTGS UTR: 4-char bank prefix + 2-digit year +
    3-digit day-of-year + 7-digit sequence (PRD §4.1.4)."""
    doy = d.timetuple().tm_yday
    return f"{prefix}{d.year % 100:02d}{doy:03d}{seq:07d}"


_LOGNORM_MEDIAN = 850.0
_LOGNORM_P90 = 3200.0
_Z90 = 1.2816


def lognormal_amount_paise(
    rng: random.Random, floor_paise: int = 5_000, ceil_paise: int = 18_00_000
) -> int:
    """Order value: log-normal, median ₹850, p90 ₹3,200, tail to ₹18,000 (PRD §0.3).

    The float sampling is inherent to the distribution and never touches
    stored money: it's locked into paise via ``round`` immediately, the same
    boundary ``to_paise`` uses for rupee-string input.
    """
    import math

    mu = math.log(_LOGNORM_MEDIAN)
    sigma = (math.log(_LOGNORM_P90) - mu) / _Z90
    rupees = rng.lognormvariate(mu, sigma)
    paise = round(rupees * 100)
    return max(floor_paise, min(ceil_paise, paise))


@dataclass
class Order:
    order_id: str
    channel: Literal["own_store", "marketplace"]
    platform: str | None
    method: str
    amount_paise: int
    order_date: date
    gt_group: str
    payment_id: str = ""
    refund_paise: int = 0
    dispute_paise: int = 0
    is_refund_only: bool = False
    gt_label: str | None = None
    gt_bucket: str = "matched"
    #: Whether this order's ledger voucher quotes its order id (scenario 16).
    #: A real Tally Sales narration often carries no gateway reference at all,
    #: and when two orders in a batch share an amount and a date that is what
    #: makes them genuinely indistinguishable. Leaving the id in the narration
    #: would let exact reference matching resolve them in one hop, which is not
    #: the failure mode the scenario exists to produce.
    ledger_reference_visible: bool = True
    #: Marketplace-only per-order override (scenario 18: a rate change lands
    #: mid-settlement, so orders on either side of the cutover carry
    #: different rates — only an effective-dated rule resolves the whole
    #: batch cleanly).
    commission_rate: Decimal | None = None


@dataclass
class Settlement:
    settlement_id: str
    channel: Literal["own_store", "marketplace"]
    platform: str | None
    settle_date: date
    value_date: date
    orders: list[Order] = field(default_factory=list)
    scenario: int | None = None
    gt_bucket: str = "matched"  # matched | rule_resolved | exception
    gt_label: str | None = None
    on_hold: bool = False
    reserve_rate: Decimal = Decimal("0")
    reserve_release_paise: int = 0
    reserve_release_of: str | None = None
    narration_mode: str = "hdfc_neft"  # hdfc_neft | short_utr | transposed | unparseable
    duplicate_voucher: bool = False
    skip_bank_row: bool = False
    #: Marketplace-only settlement-wide override (scenario 17: the platform
    #: actually charged a different commission than the standard rulebook
    #: rate — a residual the standard rule can't explain).
    commission_rate_override: Decimal | None = None


def fee_and_tax(gross_paise: int, rate: Decimal) -> tuple[int, int]:
    """(fee_paise, gst_paise_within_fee), each rounded to the nearest paise
    per transaction — never on a batch total (CLAUDE.md ingestion note)."""
    mdr_base = round_paise(Decimal(gross_paise) * rate)
    gst = round_paise(Decimal(mdr_base) * GST_ON_MDR)
    return mdr_base + gst, gst


@dataclass(frozen=True)
class SettlementTotals:
    gross_paise: int
    mdr_base_paise: int
    gst_paise: int
    tds_paise: int
    reserve_paise: int
    refund_paise: int
    dispute_paise: int
    net_credit_paise: int


def effective_rate(settlement: Settlement, order: Order) -> Decimal:
    """The MDR/commission rate actually applied to one order.

    Own-store rates are fixed by method (PRD §0.3). Marketplace rates default
    to the standard commission but can be overridden per order (scenario 18:
    a mid-period rate change) or per settlement (scenario 17: the platform
    charged a different rate than the rulebook assumes) — both single source
    of truth here, so razorpay_gen and compute_totals never disagree.
    """
    if settlement.channel == "own_store":
        return MDR_RATES[order.method]
    if order.commission_rate is not None:
        return order.commission_rate
    if settlement.commission_rate_override is not None:
        return settlement.commission_rate_override
    return PLATFORM_COMMISSION


def compute_totals(settlement: Settlement) -> SettlementTotals:
    """The single arithmetic path every generator module uses, so the
    Razorpay batch, the bank credit and the Tally receipt always agree to
    the paise."""
    gross = 0
    mdr_base_total = 0  # pure MDR, excluding the GST already folded into fee
    gst_total = 0
    refund_total = 0
    dispute_total = 0
    for order in settlement.orders:
        if not order.is_refund_only:
            gross += order.amount_paise
            rate = effective_rate(settlement, order)
            fee, gst = fee_and_tax(order.amount_paise, rate)
            mdr_base_total += fee - gst
            gst_total += gst
        refund_total += order.refund_paise
        dispute_total += order.dispute_paise

    # fee_total (= mdr_base_total + gst_total) is the *single* deduction each
    # payment row's own `credit` field already applied (credit = amount -
    # fee). Subtracting mdr_base_total and gst_total here on top of that
    # would double-count the GST portion — the bank credit only loses the
    # fee once.
    fee_total = mdr_base_total + gst_total
    tds_total = round_paise(Decimal(gross) * TDS_194O) if gross else 0
    reserve_total = round_paise(Decimal(gross) * settlement.reserve_rate) if gross else 0

    net_credit = (
        gross
        - fee_total
        - tds_total
        - reserve_total
        - refund_total
        - dispute_total
        + settlement.reserve_release_paise
    )
    return SettlementTotals(
        gross_paise=gross,
        mdr_base_paise=mdr_base_total,
        gst_paise=gst_total,
        tds_paise=tds_total,
        reserve_paise=reserve_total,
        refund_paise=refund_total,
        dispute_paise=dispute_total,
        net_credit_paise=net_credit,
    )


@dataclass(frozen=True)
class Scenario:
    id: int
    key: str
    description: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(1, "truncated_narration", "Truncated narration, UTR cut at 100 chars"),
    Scenario(2, "utr_absent_from_bank", "UTR in Razorpay, absent from bank narration"),
    Scenario(3, "many_to_one", "One bank credit against 14 Razorpay rows"),
    Scenario(4, "refund_lag", "Refund landing 3 days after original settlement"),
    Scenario(5, "duplicate_voucher", "Duplicate ledger voucher, same amount, different number"),
    Scenario(6, "chargeback_unrecorded", "Chargeback debited, never recorded in ledger"),
    Scenario(7, "rounding_drift", "Per-transaction rounding drift"),
    Scenario(8, "nach_batch", "NACH batch line, unresolvable by design"),
    Scenario(9, "direct_neft", "Bank credit with no gateway record"),
    Scenario(10, "value_date_shift", "Value date differing from transaction date"),
    Scenario(11, "tally_negative_grouping", "Tally amount as (-)1,24,500.00"),
    Scenario(12, "settlement_on_hold", "Settlement placed on hold"),
    Scenario(13, "partial_refund", "Partial refund against a multi-item order"),
    Scenario(14, "reserve_t90", "Reserve deduction with T+90 release"),
    Scenario(15, "transposed_utr", "Transposed digits in a UTR"),
    Scenario(16, "ambiguous_same_amount", "Same amount, same day, two different orders"),
)

#: Not part of the original 16 — added so the marketplace channel gives the
#: Deduction Rulebook (Prompt 6) real material: a rate the standard rule
#: can't explain, and a rate that only resolves with effective dating.
EXTRA_SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        17,
        "marketplace_commission_mismatch",
        "Marketplace commission charged at a different rate than the rulebook's standard rate",
    ),
    Scenario(
        18,
        "marketplace_rate_change_midperiod",
        "Marketplace commission rate changes mid-settlement; only effective dating resolves it",
    ),
)

#: Target case count per scenario at N=500; scaled linearly and floored at 2.
#: Scenario 3 is sized explicitly via SCENARIO_3_BATCH_SIZES instead, not here.
_BASE_COUNTS: dict[int, int] = {
    1: 5,
    2: 4,
    4: 4,
    5: 3,
    6: 4,
    7: 3,
    8: 4,
    9: 6,
    10: 5,
    11: 2,
    12: 3,
    13: 5,
    14: 3,
    15: 5,
    16: 5,
    17: 2,
    18: 2,
}


def scenario_counts(n: int) -> dict[int, int]:
    scale = max(n, 1) / 500
    return {sid: max(2, round(base * scale)) for sid, base in _BASE_COUNTS.items()}
