"""Synthetic corpus generator entrypoint — PRD §2.6 D1, §3.7, §4.1.8.

``python -m fc.generator.seed``, driven by the ``SEED``/``N`` environment
variables (``.\\scripts\\dev.ps1 generate -Seed 42 -N 500`` /
``make generate SEED=42 N=500``). Same seed, same ``N`` -> byte-identical
output: every random draw comes from one ``random.Random(seed)`` instance,
consumed in a fixed order, and every id from
:func:`fc.models.ids.deterministic_factory` seeded the same way. No
wall-clock, no dict/set iteration where order isn't first pinned down
(CLAUDE.md hard rule 9).
"""

from __future__ import annotations

import json
import os
import random
import sys
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fc.generator import bank_gen, ground_truth, razorpay_gen, tally_gen
from fc.generator.bank_gen import StandaloneBankRow
from fc.generator.scenarios import (
    EPOCH_MS,
    INGESTED_AT,
    METHOD_MIX,
    OPENING_BALANCE_PAISE,
    PERIOD_END,
    PERIOD_START,
    PLATFORM_COMMISSION,
    RESERVE_RATE,
    SCENARIO_3_BATCH_SIZES,
    TENANT_ID,
    Order,
    Settlement,
    compute_totals,
    lognormal_amount_paise,
    make_utr,
    scenario_counts,
)
from fc.ingest.bank_csv import parse_bank_csv
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.ingest.razorpay import parse_razorpay_recon
from fc.ingest.tally import parse_tally_csv
from fc.models.ids import deterministic_factory

OUTPUT_DIR = Path(__file__).resolve().parents[4] / "data" / "generated"
PLATFORMS = ("BLINKIT", "ZEPTO")
IssueId = Callable[[str], str]

_UPI_PADDING_WORDS = (
    "LUMEA", "PERSONAL", "CARE", "PRIVATE", "LIMITED", "CUSTOMER", "SETTLEMENT",
    "REFERENCE", "PADDING", "TEXT", "FOR", "NARRATION", "LENGTH", "REQUIREMENT",
)  # fmt: skip


def _upi_midcut_narration(seq: int) -> str:
    """A UPI narration genuinely truncated mid-reference, not just short.

    The UPI rail is ``UPI-{payee}-{vpa}-{ifsc}-{ref}-{note}``: the reference
    comes after two variable-length segments, so growing ``payee`` until the
    string crosses the 98-char truncation threshold and then slicing lands
    the cut inside the 12-digit ``ref`` itself — a real substring, not a
    hand-picked short token.
    """
    vpa = f"customer{seq}@upi"
    ifsc = "HDFC0001234"
    ref = f"{490000000000 + seq:012d}"
    note = "ORDER PAYMENT SETTLEMENT"

    def prefix_len(payee: str) -> int:
        return len(f"UPI-{payee}-{vpa}-{ifsc}-")

    payee = ""
    i = 0
    while prefix_len(payee) + 5 < 98:
        payee = f"{payee} {_UPI_PADDING_WORDS[i % len(_UPI_PADDING_WORDS)]}".strip()
        i += 1

    full = f"UPI-{payee}-{vpa}-{ifsc}-{ref}-{note}"
    cut_at = prefix_len(payee) + 5  # keeps exactly 5 of the 12 reference digits
    return full[:cut_at]


def _pick_method(rng: random.Random) -> str:
    r = rng.random()
    cum = 0.0
    for method, share in METHOD_MIX.items():
        cum += float(share)
        if r <= cum:
            return method
    return "emi"


def _random_date(rng: random.Random, start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=rng.randint(0, span))


def _build_orders(rng: random.Random, issue_id: IssueId, n: int) -> tuple[list[Order], list[Order]]:
    n_marketplace = round(n * 0.30)
    n_own = n - n_marketplace

    own_orders = [
        Order(
            order_id=issue_id("order_"),
            channel="own_store",
            platform=None,
            method=_pick_method(rng),
            amount_paise=lognormal_amount_paise(rng),
            order_date=_random_date(rng, PERIOD_START, PERIOD_END),
            gt_group="",
        )
        for _ in range(n_own)
    ]
    marketplace_orders = [
        Order(
            order_id=issue_id("order_"),
            channel="marketplace",
            platform=PLATFORMS[i % len(PLATFORMS)],
            method="upi",
            amount_paise=lognormal_amount_paise(rng),
            order_date=_random_date(rng, PERIOD_START, PERIOD_END),
            gt_group="",
        )
        for i in range(n_marketplace)
    ]
    return own_orders, marketplace_orders


def _chunk_own_store(
    rng: random.Random, orders: list[Order], issue_id: IssueId
) -> list[Settlement]:
    settlements: list[Settlement] = []
    ordered = sorted(orders, key=lambda o: (o.order_date, o.order_id))
    i = 0
    while i < len(ordered):
        size = min(len(ordered) - i, rng.randint(3, 6))
        chunk = ordered[i : i + size]
        i += size
        settlement_id = issue_id("setl_")
        settle_date = max(o.order_date for o in chunk) + timedelta(days=2)
        for order in chunk:
            order.gt_group = settlement_id
        settlements.append(
            Settlement(
                settlement_id=settlement_id,
                channel="own_store",
                platform=None,
                settle_date=settle_date,
                value_date=settle_date,
                orders=chunk,
            )
        )
    return settlements


def _chunk_marketplace(orders: list[Order], issue_id: IssueId) -> list[Settlement]:
    groups: dict[tuple[str, int, int], list[Order]] = {}
    for order in orders:
        iso_year, iso_week, _ = order.order_date.isocalendar()
        groups.setdefault((order.platform or "", iso_year, iso_week), []).append(order)

    settlements: list[Settlement] = []
    for key in sorted(groups.keys()):
        chunk = groups[key]
        platform = key[0]
        settlement_id = issue_id("setl_")
        settle_date = max(o.order_date for o in chunk) + timedelta(days=7)
        for order in chunk:
            order.gt_group = settlement_id
        settlements.append(
            Settlement(
                settlement_id=settlement_id,
                channel="marketplace",
                platform=platform,
                settle_date=settle_date,
                value_date=settle_date,
                orders=chunk,
            )
        )
    return settlements


def generate(seed: int, n: int) -> dict[str, Any]:
    rng = random.Random(seed)
    issue_id = deterministic_factory(seed, EPOCH_MS)
    counts = scenario_counts(n)

    own_orders, marketplace_orders = _build_orders(rng, issue_id, n)

    # Scenario 3: settlements with exactly 14, 25 and MAX_SUBSET_N+1 legs,
    # reserved before chunking so the remainder chunks to realistic batch
    # sizes. The three scales exercise the settlement-id fast path (all
    # three), an ordinary large batch (25), and the subset-sum cap/timeout
    # guard (41 > MAX_SUBSET_N) once stage 4 exists (PRD §6.4).
    scenario3_settlements: list[Settlement] = []
    for size in SCENARIO_3_BATCH_SIZES:
        batch = own_orders[:size]
        own_orders = own_orders[size:]
        settlement_id = issue_id("setl_")
        settle_date = max(o.order_date for o in batch) + timedelta(days=2)
        for order in batch:
            order.gt_group = settlement_id
        scenario3_settlements.append(
            Settlement(
                settlement_id=settlement_id,
                channel="own_store",
                platform=None,
                settle_date=settle_date,
                value_date=settle_date,
                orders=batch,
                scenario=3,
            )
        )

    settlements = _chunk_own_store(rng, own_orders, issue_id)
    settlements += _chunk_marketplace(marketplace_orders, issue_id)
    settlements += scenario3_settlements
    settlements.sort(key=lambda s: (s.settle_date, s.settlement_id))

    own_store_settlements = [
        s for s in settlements if s.channel == "own_store" and s.scenario is None
    ]
    marketplace_settlements = [
        s for s in settlements if s.channel == "marketplace" and s.scenario is None
    ]
    standalone_bank: list[StandaloneBankRow] = []
    extra_settlements: list[Settlement] = []

    def _take(pool: list[Settlement], k: int) -> list[Settlement]:
        picked = pool[:k]
        del pool[:k]
        return picked

    # --- narration/timing scenarios: mutate an already-clean settlement in place ---
    for settlement in _take(own_store_settlements, counts[1]):
        settlement.scenario = 1
        settlement.narration_mode = "short_utr"
        settlement.gt_bucket = "exception"
        settlement.gt_label = "reference_truncated"

    for settlement in _take(own_store_settlements, counts[2]):
        settlement.scenario = 2
        settlement.narration_mode = "unparseable"
        settlement.gt_bucket = "exception"
        settlement.gt_label = "reference_truncated"

    for settlement in _take(own_store_settlements, counts[15]):
        settlement.scenario = 15
        settlement.narration_mode = "transposed"
        settlement.gt_bucket = "exception"
        settlement.gt_label = "reference_truncated"

    for settlement in _take(own_store_settlements, counts[10]):
        settlement.scenario = 10
        settlement.value_date = settlement.settle_date + timedelta(days=2)

    for settlement in _take(own_store_settlements, counts[11]):
        settlement.scenario = 11

    for settlement in _take(own_store_settlements, counts[7]):
        settlement.scenario = 7
        settlement.gt_bucket = "rule_resolved"

    for settlement in _take(own_store_settlements, counts[12]):
        settlement.scenario = 12
        settlement.on_hold = True
        settlement.gt_bucket = "exception"
        settlement.gt_label = "missing_in_bank"

    for settlement in _take(own_store_settlements, counts[5]):
        settlement.scenario = 5
        settlement.duplicate_voucher = True

    for settlement in _take(own_store_settlements, counts[6]):
        settlement.scenario = 6
        target = settlement.orders[0]
        target.dispute_paise = target.amount_paise

    for settlement in _take(own_store_settlements, counts[13]):
        settlement.scenario = 13
        target = settlement.orders[0]
        target.refund_paise = round(target.amount_paise * 0.4)

    for settlement in _take(own_store_settlements, counts[16]):
        settlement.scenario = 16
        if len(settlement.orders) >= 2:
            a, b = settlement.orders[0], settlement.orders[1]
            b.amount_paise = a.amount_paise
            b.order_date = a.order_date
            for order in (a, b):
                # The rows still belong to their settlement - that is what the
                # money did - so gt_group stays the settlement id. What makes
                # them ambiguous is that their ledger legs carry no order
                # reference, leaving an identical amount and date as the only
                # evidence. Re-grouping them under a synthetic id instead would
                # mark a correct pairing as wrong and reward a matcher for
                # ignoring an identifier it can plainly see.
                order.ledger_reference_visible = False
                order.gt_label = "ambiguous_multi_candidate"
                order.gt_bucket = "exception"

    for settlement in _take(own_store_settlements, counts[4]):
        origin_order = settlement.orders[0]
        refund_id = issue_id("setl_")
        refund_date = settlement.settle_date + timedelta(days=3)
        refund_order = Order(
            order_id=origin_order.order_id,
            channel="own_store",
            platform=None,
            method=origin_order.method,
            amount_paise=origin_order.amount_paise,
            order_date=origin_order.order_date,
            gt_group=refund_id,
            payment_id=origin_order.payment_id,
            refund_paise=origin_order.amount_paise,
            is_refund_only=True,
        )
        extra_settlements.append(
            Settlement(
                settlement_id=refund_id,
                channel="own_store",
                platform=None,
                settle_date=refund_date,
                value_date=refund_date,
                orders=[refund_order],
                scenario=4,
            )
        )

    for settlement in _take(own_store_settlements, counts[14]):
        settlement.scenario = 14
        settlement.reserve_rate = RESERVE_RATE
        settlement.gt_bucket = "rule_resolved"
        totals = compute_totals(settlement)
        release_id = issue_id("setl_")
        release_date = settlement.settle_date + timedelta(days=90)
        extra_settlements.append(
            Settlement(
                settlement_id=release_id,
                channel="own_store",
                platform=None,
                settle_date=release_date,
                value_date=release_date,
                orders=[],
                scenario=14,
                reserve_release_paise=totals.reserve_paise,
                reserve_release_of=settlement.settlement_id,
            )
        )

    # --- marketplace-only scenarios: give the Deduction Rulebook (Prompt 6)
    # real material — a rate the standard rule can't explain, a rate that
    # only resolves with effective dating, and a partial refund.
    for settlement in _take(marketplace_settlements, counts[17]):
        settlement.scenario = 17
        settlement.commission_rate_override = PLATFORM_COMMISSION + Decimal("0.02")
        settlement.gt_bucket = "exception"
        settlement.gt_label = "amount_variance"

    for settlement in _take(marketplace_settlements, counts[18]):
        settlement.scenario = 18
        settlement.gt_bucket = "rule_resolved"
        if len(settlement.orders) >= 2:
            ordered = sorted(settlement.orders, key=lambda o: o.order_date)
            cutover = ordered[len(ordered) // 2].order_date
            for order in ordered:
                if order.order_date >= cutover:
                    order.commission_rate = PLATFORM_COMMISSION + Decimal("0.02")

    for settlement in _take(marketplace_settlements, 1):
        settlement.scenario = 13
        target = settlement.orders[0]
        target.refund_paise = round(target.amount_paise * 0.4)

    settlements += extra_settlements
    settlements.sort(key=lambda s: (s.settle_date, s.settlement_id))

    # --- standalone bank-only rows: scenarios 8 (NACH) and 9 (direct NEFT) ---
    for i in range(counts[8]):
        d = _random_date(rng, PERIOD_START, PERIOD_END)
        batch_ref = f"BATCH{1000 + i:05d}"
        group = issue_id("grp_")
        standalone_bank.append(
            StandaloneBankRow(
                narration=f"NACH-{batch_ref}-NPCI",
                amount_paise=lognormal_amount_paise(
                    rng, floor_paise=50_00_00, ceil_paise=200_00_00
                ),
                txn_date=d,
                scenario=8,
                gt_label="nach_batch_unexploded",
                gt_group=group,
            )
        )
    for i in range(counts[9]):
        d = _random_date(rng, PERIOD_START, PERIOD_END)
        utr = make_utr("HDFC", d, 9_000_000 + i)
        group = issue_id("grp_")
        # Every other row carries a comma in the free-text party field, like
        # a real remitter name ("BLINKIT, COMMERCE") — exercises the
        # narration-comma-overflow path in fc.ingest.bank_csv.parse_csv_line.
        party = f"CUSTOMER {i}, PRIVATE LIMITED" if i % 2 == 0 else "CUSTOMER DIRECT PAYMENT"
        standalone_bank.append(
            StandaloneBankRow(
                narration=f"NEFT CR:{utr}/{party}/INV-DIRECT-{i:04d}",
                amount_paise=lognormal_amount_paise(rng),
                txn_date=d,
                scenario=9,
                gt_label="missing_in_gateway",
                gt_group=group,
            )
        )

    # Scenario 1, second realisation: the UPI rail is the only coded
    # narration format where the reference sits after variable-length free
    # text (payee, then vpa), so a real 98+-char export can genuinely slice
    # through the reference mid-digit — unlike HDFC's NEFT template, where
    # the UTR sits immediately after the fixed 8-char prefix and can never
    # be shortened by tail truncation. This is the only path that exercises
    # `is_truncated` against a reference actually cut mid-token.
    for i in range(3):
        d = _random_date(rng, PERIOD_START, PERIOD_END)
        group = issue_id("grp_")
        standalone_bank.append(
            StandaloneBankRow(
                narration=_upi_midcut_narration(i),
                amount_paise=lognormal_amount_paise(rng),
                txn_date=d,
                scenario=1,
                gt_label="reference_truncated",
                gt_group=group,
            )
        )

    utr_by_settlement = {
        s.settlement_id: make_utr("HDFC", s.settle_date, i) for i, s in enumerate(settlements)
    }

    razorpay_rows, razorpay_gt = razorpay_gen.build(settlements, issue_id, utr_by_settlement)
    bank_text, bank_gt = bank_gen.build(settlements, standalone_bank, utr_by_settlement)
    tally_text, tally_gt = tally_gen.build(settlements, issue_id)

    all_gt = razorpay_gt + bank_gt + tally_gt

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "razorpay_recon.json").write_text(
        json.dumps(razorpay_rows, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "bank_statement.csv").write_text(bank_text, encoding="utf-8", newline="\n")
    (OUTPUT_DIR / "tally_daybook.csv").write_text(tally_text, encoding="utf-8", newline="\n")
    ground_truth.write_ground_truth(OUTPUT_DIR / "ground_truth.jsonl", all_gt)
    manifest = ground_truth.write_manifest(
        OUTPUT_DIR / "manifest.json",
        seed=seed,
        n=n,
        entries=all_gt,
        row_counts={
            "razorpay_rows": len(razorpay_rows),
            "bank_rows": bank_text.count("\n") - 1,
            "tally_rows": tally_text.count("\n") - 1,
            "settlements": len(settlements),
            "standalone_bank_rows": len(standalone_bank),
        },
    )
    _self_check(razorpay_rows, bank_text, bank_gt, tally_text, seed)
    return manifest


def _self_check(
    razorpay_rows: list[dict[str, Any]],
    bank_text: str,
    bank_gt: list[ground_truth.GTEntry],
    tally_text: str,
    seed: int,
) -> None:
    check_issue_id = deterministic_factory(seed=seed, epoch_ms=EPOCH_MS)

    rp_result = parse_razorpay_recon(
        razorpay_rows,
        run_id="run_selfcheck",
        tenant_id=TENANT_ID,
        issue_id=check_issue_id,
        ingested_at=INGESTED_AT,
    )
    if rp_result.rejections:
        n_rejected = len(rp_result.rejections)
        raise AssertionError(f"razorpay self-check: {n_rejected} unexpected rejections")

    bank_result = parse_bank_csv(
        bank_text,
        run_id="run_selfcheck",
        tenant_id=TENANT_ID,
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=OPENING_BALANCE_PAISE,
        issue_id=check_issue_id,
        ingested_at=INGESTED_AT,
    )
    if bank_result.ingest.rejections:
        n_rejected = len(bank_result.ingest.rejections)
        raise AssertionError(f"bank self-check: {n_rejected} unexpected rejections")
    if not bank_result.balanced:
        raise AssertionError(f"bank self-check: balance discontinuity — {bank_result.breaks}")

    _check_settlement_arithmetic(razorpay_rows, bank_result.ingest.events, bank_gt)

    tally_result = parse_tally_csv(
        tally_text,
        run_id="run_selfcheck",
        tenant_id=TENANT_ID,
        issue_id=check_issue_id,
        ingested_at=INGESTED_AT,
    )
    if tally_result.rejections:
        n_rejected = len(tally_result.rejections)
        raise AssertionError(f"tally self-check: {n_rejected} unexpected rejections")


def _check_settlement_arithmetic(
    razorpay_rows: list[dict[str, Any]],
    bank_events: Any,
    bank_gt: list[ground_truth.GTEntry],
) -> None:
    """For every settlement: sum(payment.credit) - TDS - reserve - refunds -
    disputes + reserve_release == the bank credit actually posted for it.

    Each payment row's own ``credit`` already deducted the full fee (MDR +
    GST), so this must not subtract fee or tax again — the bug this catches
    is exactly that: a second, hidden deduction sneaking into either side.

    Bank rows are matched to their settlement via the ground-truth key
    (the same idempotency hash the real adapter computes), not by searching
    the narration text for the settlement id — scenario 1 deliberately
    truncates that narration, which would silently drop those settlements
    out of a text-search-based check instead of actually verifying them.
    """
    by_settlement: dict[str, int] = {}
    for row in razorpay_rows:
        sid = row.get("settlement_id")
        if sid is None:
            continue
        net = by_settlement.get(sid, 0)
        row_type = row["type"]
        if row_type == "payment":
            net += row["credit"]
        elif row_type in ("refund", "dispute"):
            net -= row["debit"]
        elif row_type == "adjustment":
            net += row["credit"] - row["debit"]
        by_settlement[sid] = net

    sid_by_bank_key = {g.key: g.gt_match_group for g in bank_gt}
    bank_credit_by_settlement: dict[str, int] = {}
    for event in bank_events:
        sid = sid_by_bank_key.get(event.source_row_id)
        if sid is not None and sid in by_settlement:
            signed = event.amount_paise if event.direction == "credit" else -event.amount_paise
            bank_credit_by_settlement[sid] = signed

    unmatched = [sid for sid in by_settlement if sid not in bank_credit_by_settlement]
    # Legitimately bank-less settlements: on-hold (scenario 12, money hasn't
    # moved) and reserve-release settlements with no orders of their own are
    # ruled out by construction elsewhere; anything left here is a real gap.
    on_hold_settlement_ids = {row["settlement_id"] for row in razorpay_rows if row.get("on_hold")}
    genuinely_missing = [sid for sid in unmatched if sid not in on_hold_settlement_ids]
    if genuinely_missing:
        raise AssertionError(
            f"settlement arithmetic self-check: {len(genuinely_missing)} settlements "
            f"have no matching bank row — {genuinely_missing[:5]}"
        )

    mismatches = []
    for sid, expected in by_settlement.items():
        actual = bank_credit_by_settlement.get(sid)
        if actual is None:
            continue  # on-hold or zero-net settlements post no bank row
        if actual != expected:
            mismatches.append((sid, expected, actual))
    if mismatches:
        detail = "; ".join(f"{sid}: expected={e} actual={a}" for sid, e, a in mismatches[:5])
        raise AssertionError(
            f"settlement arithmetic self-check: {len(mismatches)} mismatches — {detail}"
        )


def main() -> None:
    seed = int(os.environ.get("SEED", "42"))
    n = int(os.environ.get("N", "500"))
    manifest = generate(seed, n)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
    sys.exit(0)
