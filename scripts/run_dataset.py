"""Run any three-source dataset through the production pipeline, and — when an
answer key is supplied — diff the engine's verdict against it.

Nothing here knows anything about a particular dataset: every file is a CLI
argument, every rule comes out of the rules file, and the answer key is read,
never encoded. It exists so a second corpus can be pointed at the engine
without going through the database or the API.

Usage::

    python scripts/run_dataset.py --dir data/datasets/v2 \
        --rules data/datasets/v2/recon_rules_v2_array.json \
        --answer-key data/datasets/v2/answer_key_v2.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine" / "src"))

from fc.config import load_config  # noqa: E402
from fc.ingest.aliases import load_aliases  # noqa: E402
from fc.ingest.bank_csv import parse_bank_csv  # noqa: E402
from fc.ingest.narration.hdfc import HdfcNarrationParser  # noqa: E402
from fc.ingest.razorpay import parse_razorpay_recon  # noqa: E402
from fc.ingest.tally import parse_tally_csv  # noqa: E402
from fc.models.ids import deterministic_factory  # noqa: E402
from fc.models.money import fmt_inr  # noqa: E402
from fc.models.transaction import TransactionEvent  # noqa: E402
from fc.pipeline import run_pipeline  # noqa: E402
from fc.rules.loader import build_ruleset_from_entries  # noqa: E402

EPOCH_MS = 1_780_000_000_000
INGESTED_AT = datetime(2026, 8, 29, tzinfo=UTC)
RUN_ID = "run_dataset"

#: An external rules file names its deduction layers in the vocabulary of a
#: rate card ("tax", "tcs"), not in the Rulebook's own (:data:`DeductionType`).
#: One mapping, applied to type and basis alike, so a `basis: commission`
#: still chains onto the line above it.
_DEDUCTION_ALIASES = {
    "tax": "gst_on_fee",
    "gst": "gst_on_fee",
    "tds": "tds_194o",
    "tcs": "custom",
    "mdr": "mdr",
    "commission": "commission",
    "reserve": "reserve",
    "platform_fee": "platform_fee",
}


def _canonical_deduction(entry: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    for key in ("type", "basis"):
        value = out.get(key)
        if isinstance(value, str):
            out[key] = _DEDUCTION_ALIASES.get(value.lower(), value)
    rate = out.get("rate")
    if isinstance(rate, str):
        out["rate"] = Decimal(rate)
    return out


def load_external_rules(path: Path, *, tenant_id: str) -> tuple[Any, ...]:
    entries = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    if isinstance(entries, dict):
        entries = entries.get("rules", [])
    normalised = []
    for entry in entries:
        body = dict(entry)
        body["deductions"] = [_canonical_deduction(d) for d in body.get("deductions") or []]
        normalised.append(body)
    return build_ruleset_from_entries(
        normalised,
        source_label=str(path),
        tenant_id=tenant_id,
        created_at=INGESTED_AT,
    )


def _only(directory: Path, *patterns: str) -> Path:
    for pattern in patterns:
        hits = sorted(directory.glob(pattern))
        if hits:
            return hits[0]
    raise SystemExit(f"no file matching {patterns} in {directory}")


def ingest(
    directory: Path, *, tenant_id: str, opening_balance_paise: int
) -> tuple[tuple[TransactionEvent, ...], int]:
    issue_id = deterministic_factory(seed=42, epoch_ms=EPOCH_MS)
    aliases = load_aliases()
    razorpay = parse_razorpay_recon(
        json.loads(_only(directory, "*razorpay*.json").read_text(encoding="utf-8")),
        run_id=RUN_ID,
        tenant_id=tenant_id,
        issue_id=issue_id,
        ingested_at=INGESTED_AT,
    )
    bank = parse_bank_csv(
        _only(directory, "*bank*.csv").read_text(encoding="utf-8"),
        run_id=RUN_ID,
        tenant_id=tenant_id,
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=opening_balance_paise,
        issue_id=issue_id,
        ingested_at=INGESTED_AT,
        aliases=aliases,
    )
    ledger = parse_tally_csv(
        _only(directory, "*tally*.csv", "*daybook*.csv").read_text(encoding="utf-8"),
        run_id=RUN_ID,
        tenant_id=tenant_id,
        issue_id=issue_id,
        ingested_at=INGESTED_AT,
        aliases=aliases,
    )
    events = (*razorpay.events, *bank.ingest.events, *ledger.events)
    rejections = len(razorpay.rejections) + len(bank.ingest.rejections) + len(ledger.rejections)
    return events, rejections


#: Exception categories that are a statement about *this settlement's payout*.
#: Deliberately narrower than "any open exception": an unrecorded chargeback
#: and a duplicate receipt are real findings that happen to sit inside a
#: settlement whose payout reconciled perfectly, and the answer key scores them
#: as standalone items for exactly that reason. ``unknown`` is out for the same
#: reason — it means the group did not reach the auto-close bar, which is a
#: statement about evidence strength, not about the money.
PAYOUT_CATEGORIES = frozenset(
    {
        "missing_in_bank",
        "missing_in_gateway",
        "missing_in_ledger",
        "amount_variance",
        "ambiguous_multi_candidate",
        "revenue_booked_not_settled",
    }
)


def _settlement_verdicts(result: Any) -> dict[str, str]:
    """What the engine concluded about each gateway settlement's payout.

    ``matched`` means nothing open says this payout failed to reconcile three
    ways. A settlement whose bank credit proves out perfectly but whose ledger
    leg is missing or booked at the wrong amount is *not* matched — the answer
    key calls those exception_resolvable, and it is right to: the cash being
    provable is not the same claim as the reconciliation being complete.
    """
    settlement_of_event = {
        event.event_id: event.settlement_id for event in result.events if event.settlement_id
    }
    # A ledger or bank row carries no settlement id of its own, so an exception
    # raised on one reaches its settlement through the match group they share.
    settlements_of_group: dict[str, set[str]] = {}
    for match in result.cascade.matches:
        ids = {settlement_of_event[e] for e in match.event_ids if e in settlement_of_event}
        for event_id in match.event_ids:
            settlements_of_group.setdefault(event_id, set()).update(ids)

    failed: dict[str, list[Any]] = {}
    for exc in result.exceptions:
        if exc.status == "resolved" or exc.category not in PAYOUT_CATEGORIES:
            continue
        touched: set[str] = set()
        for event_id in exc.event_ids:
            sid = settlement_of_event.get(event_id)
            if sid:
                touched.add(sid)
            touched.update(settlements_of_group.get(event_id, ()))
        for sid in touched:
            failed.setdefault(sid, []).append(exc)

    verdicts: dict[str, str] = {}
    for event in result.events:
        if event.source != "razorpay" or not event.settlement_id:
            continue
        open_excs = failed.get(event.settlement_id, [])
        if not open_excs:
            verdicts[event.settlement_id] = "matched"
        else:
            tiers = sorted({e.tier for e in open_excs})
            cats = sorted({e.category for e in open_excs})
            verdicts[event.settlement_id] = f"exception[{','.join(tiers)}:{','.join(cats)}]"
    return verdicts


def diff_against_answer_key(result: Any, key: Mapping[str, Any]) -> int:
    verdicts = _settlement_verdicts(result)
    print("\n=== SETTLEMENT DIFF vs ANSWER KEY ===")
    agree = 0
    for entry in key.get("settlements", []):
        sid = entry["settlement_id"]
        want = entry["expected_status"]
        got = verdicts.get(sid, "ABSENT (settlement id not in gateway events)")
        want_matched = want == "matched"
        got_matched = got == "matched"
        ok = want_matched == got_matched
        agree += ok
        flag = "OK " if ok else "XX "
        print(f"{flag}{sid:24} {entry['scenario']:22} want={want:24} got={got}")
    print(f"\n{agree}/{len(key.get('settlements', []))} settlements agree on matched/not-matched")
    return agree


def summarise(result: Any) -> None:
    bridge = result.cash_bridge
    print("\n=== ENGINE SUMMARY ===")
    print(f"events            {len(result.events)}")
    print(f"matches           {len(result.cascade.matches)}")
    print(f"matched events    {len(result.cascade.matched_event_ids)}")
    print(f"exceptions        {len(result.exceptions)}")
    by_tier: dict[str, int] = {}
    by_cat: dict[str, int] = {}
    for exc in result.exceptions:
        by_tier[exc.tier] = by_tier.get(exc.tier, 0) + 1
        by_cat[exc.category] = by_cat.get(exc.category, 0) + 1
    print(f"  by tier         {dict(sorted(by_tier.items()))}")
    print(f"  by category     {dict(sorted(by_cat.items()))}")
    print("\n=== LANES ===")
    for lane in bridge.lanes:
        print(
            f"  {lane.lane:12} in {fmt_inr(lane.bank_in_paise):>15} "
            f"out {fmt_inr(lane.bank_out_paise):>15} books {fmt_inr(lane.ledger_paise):>15}"
            f"  open {lane.exception_count:>3} {fmt_inr(lane.unreconciled_paise):>15}"
        )

    books = bridge.books_vs_bank
    print("\n=== BOOKS vs BANK ===")
    print(f"  per the books           {fmt_inr(books.books_movement_paise)}")
    print(f"  per the bank            {fmt_inr(books.bank_movement_paise)}")
    print(f"  difference              {fmt_inr(books.difference_paise)}")
    print(f"    timing                {fmt_inr(books.timing_paise)}")
    print(f"    unrecorded in books   {fmt_inr(books.unrecorded_in_books_paise)}")
    print(f"    under investigation   {fmt_inr(books.under_investigation_paise)}")
    print(f"    unexplained           {fmt_inr(books.unexplained_paise)}")

    print("\n=== CASH BRIDGE ===")
    print(f"  gross collected      {fmt_inr(bridge.gross_collected_paise)}")
    for segment in bridge.segments:
        print(
            f"  {segment.label:<22} {fmt_inr(segment.amount_paise):>16}"
            f"   attributed {fmt_inr(segment.attributed_paise):>16}"
            f"  ({len(segment.exception_ids)} exc)"
        )
    print(f"  expected net         {fmt_inr(bridge.expected_net_paise)}")
    print(f"  bank credited        {fmt_inr(bridge.actual_bank_paise)}")
    print(f"  unexplained          {fmt_inr(bridge.unexplained_paise)}")
    print(f"  held (not collected) {fmt_inr(bridge.held_paise)}")
    print(
        f"  cash at risk         {fmt_inr(bridge.cash_at_risk_paise)}  "
        f"{bridge.at_risk.headline(as_of=INGESTED_AT.date())}"
    )
    print(f"  unidentified inflows {fmt_inr(bridge.unidentified_inflow_paise)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--answer-key", type=Path)
    parser.add_argument("--opening-balance-paise", type=int, default=0)
    parser.add_argument("--dump-events", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config()
    events, rejections = ingest(
        args.dir,
        tenant_id=cfg.tenant_id,
        opening_balance_paise=args.opening_balance_paise,
    )
    rules = load_external_rules(args.rules, tenant_id=cfg.tenant_id) if args.rules else ()
    result = run_pipeline(
        events,
        cfg=cfg,
        rules=rules,
        run_id=RUN_ID,
        tenant_id=cfg.tenant_id,
        issue_id=deterministic_factory(seed=7, epoch_ms=EPOCH_MS),
        created_at=INGESTED_AT,
        aliases=load_aliases(),
    )
    print(f"ingest rejections {rejections}")
    summarise(result)
    if args.answer_key:
        diff_against_answer_key(result, json.loads(args.answer_key.read_text(encoding="utf-8")))
    if args.dump_events:
        for event in result.events:
            print(
                f"{event.source:9} {event.txn_date} {event.direction:6} "
                f"{fmt_inr(event.amount_paise):>16} {event.txn_type or '-':11} "
                f"{(event.counterparty_norm or '-'):28} {(event.raw_narration or '')[:70]}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
