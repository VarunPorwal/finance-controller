"""Reconciliation pipeline orchestration, stages 0-9 — PRD §3.3, §6, §6.10.

One breath: ingest three sources -> block -> match in five passes -> apply
customer rules -> classify -> score -> cluster -> tier -> recommend -> hand a
human a ranked queue -> compute the cash bridge underneath it.

This module composes stages that already exist (:mod:`fc.matching.cascade`,
:mod:`fc.rules.apply`) with the ones this prompt adds
(:mod:`fc.exceptions.*`, :mod:`fc.cash.bridge`). It owns exactly one piece of
domain logic of its own: turning a marketplace settlement's ledger receipt and
its gateway rows into the ``gap_paise`` / ``gross_paise`` pair the Rulebook
answers (the same arithmetic ``tests/eval/test_rules_corpus.py``'s ``Payout``
fixture proves against the real rates) — every other stage below is a
straight call into the module that owns that decision.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, NamedTuple

from fc.cash.bridge import CashBridge, compute_cash_bridge
from fc.config import Config, load_config
from fc.eval.corpus import DATA_DIR, load_corpus
from fc.exceptions.classify import RuleGap, classify_exceptions
from fc.exceptions.cluster import cluster_exceptions
from fc.exceptions.consequence import consequence_and_deadline
from fc.exceptions.priority import priority_score
from fc.exceptions.recommend import recommended_action
from fc.exceptions.tier import tier_for
from fc.ingest.aliases import AliasTable
from fc.matching.cascade import CascadeResult, run_cascade
from fc.models.exception_ import Cluster, Exception_, ExceptionStatus, ResolvedBy
from fc.models.ids import deterministic_factory
from fc.models.money import fmt_inr
from fc.models.rule import Rule
from fc.models.transaction import TransactionEvent
from fc.rules.apply import apply_rules
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules

__all__ = ["PIPELINE_STAGES", "PipelineResult", "main", "run_pipeline"]

PIPELINE_STAGES: Final[tuple[str, ...]] = (
    "ingest",
    "normalise",
    "block",
    "match_cascade",
    "three_way",
    "apply_rules",
    "classify_exceptions",
    "cluster",
    "tier_and_prioritise",
    "cash_bridge",
)

#: A marketplace payout's Tally Receipt narrates the settlement it closes as
#: "Settlement credit {settlement_id}" (``fc.generator.tally_gen``). This is
#: the only place that reference gets read back out, and it must stay in step
#: with the generator's own narration string or the Rulebook silently stops
#: finding batches to apply to (CLAUDE.md's IDFC/ICICI/Tally-XML note applies
#: here too: change both sides in the same commit).
_SETTLEMENT_RECEIPT_REF = re.compile(r"Settlement credit (\S+)")

#: Same marker ``fc.cash.bridge`` matches in a settlement-line-item
#: adjustment row's ``description`` (PRD §4.1.7). Duplicated rather than
#: imported: the two modules are asking different questions of the same
#: field (the bridge sums it, this module verifies its rate), and a shared
#: constant would suggest a coupling that does not otherwise exist.
_TDS_MARKER = "TDS"


@dataclass(frozen=True)
class PipelineResult:
    events: tuple[TransactionEvent, ...]
    cascade: CascadeResult
    rule_gaps: tuple[RuleGap, ...]
    exceptions: tuple[Exception_, ...]
    clusters: tuple[Cluster, ...]
    cash_bridge: CashBridge


class _Lifecycle(NamedTuple):
    status: ExceptionStatus
    resolved_by: ResolvedBy | None = None
    resolved_at: datetime | None = None
    resolution_reason: str | None = None


def _lifecycle_for(tier: str, *, created_at: datetime) -> _Lifecycle:
    """The status a freshly tiered exception is born in.

    §6.8's tier is a decision about who acts, and the status has to say the
    same thing or nothing downstream can act on it. Both mismatches were live:

    * ``monitor`` means "the system will look again on ``recheck_at``", but the
      row was written ``open``, and the recheck job selects
      ``status == 'monitoring'``. It had therefore selected nothing on every
      tick since it was built.

    * ``auto`` means the pipeline resolved it — an AUTO_SAFE category at or
      above ``auto_threshold``, with the NEVER_AUTO gate already passed. The row
      was written ``open`` and then hidden from the queue by the UI under the
      heading "Already handled", so eight exceptions were neither surfaced to a
      human nor recorded as closed. ``resolved_by='system'`` is what makes
      "already handled" true rather than a caption.

    ``resolved_at`` uses the run's ``created_at``, not the clock, so the same
    seed still produces byte-identical exceptions (hard rule 9).
    """
    if tier == "monitor":
        return _Lifecycle(status="monitoring")
    if tier == "auto":
        return _Lifecycle(
            status="resolved",
            resolved_by="system",
            resolved_at=created_at,
            resolution_reason=(
                "auto-resolved: category is auto-safe and confidence met the threshold"
            ),
        )
    return _Lifecycle(status="open")


def run_pipeline(
    events: Sequence[TransactionEvent],
    *,
    cfg: Config,
    rules: Sequence[Rule],
    run_id: str,
    tenant_id: str,
    issue_id: Callable[[str], str],
    created_at: datetime,
    aliases: AliasTable | None = None,
) -> PipelineResult:
    """Run stages 0-9 end to end. What ``make demo`` runs.

    ``issue_id`` and ``created_at`` are injected exactly as in
    ``fc.matching.cascade.run_cascade``: decision code never reads the wall
    clock, so a seeded run is byte-identical (CLAUDE.md hard rule 9).
    """
    events = tuple(events)
    cascade = run_cascade(
        events,
        cfg=cfg,
        run_id=run_id,
        tenant_id=tenant_id,
        issue_id=issue_id,
        created_at=created_at,
    )

    rule_gaps = _all_rule_gaps(events, rules, cfg=cfg, aliases=aliases)

    classified = classify_exceptions(events, cascade, rule_gaps=rule_gaps)
    tier_decisions = [
        tier_for(
            item.category,
            confidence=item.confidence,
            cfg=cfg,
            expected_resolution_date=item.expected_resolution_date,
        )
        for item in classified
    ]

    by_id = {event.event_id: event for event in events}
    as_of = created_at.date()
    consequences = [
        consequence_and_deadline(item, events_by_id=by_id, cfg=cfg, as_of=as_of)
        for item in classified
    ]

    cluster_groups = cluster_exceptions(classified, [decision.tier for decision in tier_decisions])
    cluster_size_by_index: dict[int, int] = {}
    for group in cluster_groups:
        for index in group.member_indices:
            cluster_size_by_index[index] = len(group.member_indices)

    clusters: list[Cluster] = []
    cluster_id_of: dict[int, str] = {}
    for group in cluster_groups:
        cluster_id = issue_id("cls_")
        for index in group.member_indices:
            cluster_id_of[index] = cluster_id
        clusters.append(
            Cluster(
                cluster_id=cluster_id,
                run_id=run_id,
                tenant_id=tenant_id,
                root_cause=group.root_cause,
                label=group.label,
                grouping_key=group.grouping_key,
                member_count=len(group.member_indices),
                total_paise=group.total_paise,
                max_tier=group.max_tier,
                suggested_fix=group.suggested_fix,
                created_at=created_at,
            )
        )

    exceptions: list[Exception_] = []
    for index, item in enumerate(classified):
        tier_decision = tier_decisions[index]
        lifecycle = _lifecycle_for(tier_decision.tier, created_at=created_at)
        consequence, deadline = consequences[index]
        exceptions.append(
            Exception_(
                exception_id=issue_id("exc_"),
                run_id=run_id,
                tenant_id=tenant_id,
                event_ids=list(item.event_ids),
                category=item.category,
                amount_paise=item.amount_paise,
                residual_paise=item.residual_paise,
                confidence=item.confidence,
                tier=tier_decision.tier,
                priority_score=priority_score(
                    amount_paise=item.priority_amount,
                    tier=tier_decision.tier,
                    confidence=item.confidence,
                    deadline=deadline,
                    as_of=as_of,
                    cluster_size=cluster_size_by_index.get(index, 0),
                ),
                cluster_id=cluster_id_of.get(index),
                rules_applied=list(item.rules_applied),
                recommended_action=recommended_action(item, events_by_id=by_id, deadline=deadline),
                consequence=consequence,
                deadline=deadline,
                recheck_at=tier_decision.recheck_at,
                signature=item.signature,
                created_at=created_at,
                status=lifecycle.status,
                resolved_by=lifecycle.resolved_by,
                resolved_at=lifecycle.resolved_at,
                resolution_reason=lifecycle.resolution_reason,
            )
        )

    cash_bridge = compute_cash_bridge(events, exceptions)

    return PipelineResult(
        events=events,
        cascade=cascade,
        rule_gaps=rule_gaps,
        exceptions=tuple(exceptions),
        clusters=tuple(clusters),
        cash_bridge=cash_bridge,
    )


#: The ``razorpay_mdr_*`` starter-pack rule ids (per-transaction MDR/GST,
#: scoped by ``method``) and the batch-level statutory TDS rule (§ below),
#: selected by prefix so ``_all_rule_gaps`` feeds each gap-builder only the
#: rules that question is actually asking about. Feeding the whole ruleset to
#: every builder would let a broadly-scoped rule answer a question it was
#: never meant to (see the module-level note on ``razorpay_tds_batch``).
_MDR_RULE_PREFIX = "razorpay_mdr_"
_TDS_BATCH_RULE_ID = "razorpay_tds_batch"


def _all_rule_gaps(
    events: Sequence[TransactionEvent],
    rules: Sequence[Rule],
    *,
    cfg: Config,
    aliases: AliasTable | None,
) -> tuple[RuleGap, ...]:
    """Every settlement-level and per-transaction gap the Rulebook answers.

    Three questions, three separate gaps, on purpose:

    1. **Batch payout** (:func:`_settlement_rule_gaps`) — a marketplace's
       weekly commission, applied to the whole settlement. Own-store
       settlements are structurally excluded (see that function): no rule in
       the starter pack is scoped to explain a *batch* mixing several MDR
       rates, and asking one to try produced 58 false ``amount_variance``
       exceptions before this split existed.
    2. **Per-transaction MDR/GST** (:func:`_per_transaction_mdr_gaps`) — the
       question own-store settlements actually need answered: did Razorpay
       charge the contracted rate on *this* payment. Marketplace settlements
       are excluded here in the other direction, using the same settlement
       ids question 1 already proved are marketplace-covered.
    3. **Batch TDS 194-O** (:func:`_own_store_tds_gaps`) — a fixed statutory
       rate, deducted once per settlement, never per transaction (unlike
       MDR). Marketplace settlements already verify their own TDS inside
       ``blinkit_commission``/``zepto_commission``; excluded again here so it
       is never checked twice.
    """
    settlement_gaps, marketplace_settlement_ids = _settlement_rule_gaps(
        events, rules, cfg=cfg, aliases=aliases
    )
    mdr_rules = tuple(r for r in rules if r.rule_id.startswith(_MDR_RULE_PREFIX))
    tds_rules = tuple(r for r in rules if r.rule_id == _TDS_BATCH_RULE_ID)
    return (
        *settlement_gaps,
        *_per_transaction_mdr_gaps(
            events, mdr_rules, cfg=cfg, aliases=aliases, skip_settlements=marketplace_settlement_ids
        ),
        *_own_store_tds_gaps(
            events, tds_rules, cfg=cfg, aliases=aliases, skip_settlements=marketplace_settlement_ids
        ),
    )


def _gateway_rows_by_settlement(
    events: Sequence[TransactionEvent],
) -> dict[str, list[TransactionEvent]]:
    by_settlement: dict[str, list[TransactionEvent]] = {}
    for event in events:
        if event.source == "razorpay" and event.settlement_id:
            by_settlement.setdefault(event.settlement_id, []).append(event)
    return by_settlement


def _settlement_rule_gaps(
    events: Sequence[TransactionEvent],
    rules: Sequence[Rule],
    *,
    cfg: Config,
    aliases: AliasTable | None,
) -> tuple[tuple[RuleGap, ...], frozenset[str]]:
    """One :class:`~fc.exceptions.classify.RuleGap` per settlement payout,
    plus the settlement ids a rule actually claimed (§6.7's ``considered``).

    The question the books ask, not the one the cascade already answered:
    a Tally Receipt booked against a named counterparty, matched to its
    gateway rows by the settlement id its own narration names. Mirrors
    ``tests/eval/test_rules_corpus.py``'s ``Payout`` fixture, generalised
    past the two named marketplaces it was proven against — any counterparty
    settling in a batch, not just Blinkit and Zepto, gets the same treatment.
    """
    gateway_rows_by_settlement = _gateway_rows_by_settlement(events)

    gaps: list[RuleGap] = []
    claimed_settlement_ids: set[str] = set()
    for event in events:
        if (
            event.source != "ledger"
            or event.voucher_type != "Receipt"
            or not event.counterparty_norm
        ):
            continue
        reference = _SETTLEMENT_RECEIPT_REF.search(event.raw_narration or "")
        if reference is None:
            continue
        settlement_id = reference.group(1)
        rows = [
            row
            for row in gateway_rows_by_settlement.get(settlement_id, ())
            if row.txn_type == "payment" and row.direction == "credit"
        ]
        if not rows:
            continue

        # The payment row's stored amount is already net of its own fee, so
        # the gross the commission was charged on is amount + fee (§6.1).
        gross_paise = sum(row.amount_paise + (row.fee_paise or 0) for row in rows)
        gap_paise = gross_paise - event.amount_paise

        outcome = apply_rules(
            rules,
            event=event,
            on_date=event.effective_date,
            gap_paise=gap_paise,
            gross_paise=gross_paise,
            n_txns=len(rows),
            cfg=cfg,
            aliases=aliases,
        )
        if outcome.considered > 0:
            claimed_settlement_ids.add(settlement_id)
        gaps.append(
            RuleGap(
                event_ids=(event.event_id, *sorted(row.event_id for row in rows)),
                outcome=outcome,
                counterparty_norm=event.counterparty_norm,
                rail=event.rail,
            )
        )
    return tuple(gaps), frozenset(claimed_settlement_ids)


def _per_transaction_mdr_gaps(
    events: Sequence[TransactionEvent],
    mdr_rules: Sequence[Rule],
    *,
    cfg: Config,
    aliases: AliasTable | None,
    skip_settlements: frozenset[str],
) -> tuple[RuleGap, ...]:
    """Verify one payment row's MDR/GST against the contracted rate for its
    method — the check a batch-level rule structurally cannot make, because a
    batch mixes methods and a mixed batch has no single rate (the starter
    pack's own comment on why there is no batch-level own-store rule).

    ``gap_paise`` is ``fee_paise`` itself: Razorpay's own recon report already
    states what it deducted, and the question here is only whether that
    matches what the rate card says it should have deducted — not whether the
    money is otherwise accounted for, which the cascade's ``fee_adjusted``
    stage already proved from the same field.
    """
    gaps: list[RuleGap] = []
    for event in events:
        if (
            event.source != "razorpay"
            or event.txn_type != "payment"
            or event.direction != "credit"
            or event.fee_paise is None
        ):
            continue
        if event.settlement_id in skip_settlements:
            continue
        gross_paise = event.amount_paise + event.fee_paise
        outcome = apply_rules(
            mdr_rules,
            event=event,
            on_date=event.effective_date,
            gap_paise=event.fee_paise,
            gross_paise=gross_paise,
            n_txns=1,
            cfg=cfg,
            aliases=aliases,
        )
        gaps.append(
            RuleGap(
                event_ids=(event.event_id,),
                outcome=outcome,
                counterparty_norm=event.counterparty_norm,
                rail=event.rail,
            )
        )
    return tuple(gaps)


def _own_store_tds_gaps(
    events: Sequence[TransactionEvent],
    tds_rules: Sequence[Rule],
    *,
    cfg: Config,
    aliases: AliasTable | None,
    skip_settlements: frozenset[str],
) -> tuple[RuleGap, ...]:
    """Verify one settlement's TDS 194-O adjustment row against 1% of gross.

    A separate gap from the batch payout gap on purpose: TDS is a fixed
    statutory rate applied once per settlement, not per transaction, so it
    cannot ride inside :func:`_per_transaction_mdr_gaps` (a per-row gap has no
    TDS component to explain) and it must not ride inside
    :func:`_settlement_rule_gaps` either (own-store settlements are excluded
    from that gap entirely — see its docstring — because no rule there can
    explain the *whole* mixed-rate batch). Marketplace settlements are
    excluded here because their commission rule already verifies TDS as part
    of its own stack; checking it again here would be the same finding twice.
    """
    gross_by_settlement: dict[str, int] = {}
    for event in events:
        if event.source == "razorpay" and event.txn_type == "payment" and event.settlement_id:
            gross_by_settlement[event.settlement_id] = gross_by_settlement.get(
                event.settlement_id, 0
            ) + (event.amount_paise + (event.fee_paise or 0))

    gaps: list[RuleGap] = []
    for event in events:
        if event.source != "razorpay" or event.txn_type != "adjustment":
            continue
        if _TDS_MARKER not in str(event.raw.get("description") or ""):
            continue
        if event.settlement_id in skip_settlements:
            continue
        gross_paise = gross_by_settlement.get(event.settlement_id or "", 0)
        if not gross_paise:
            continue
        outcome = apply_rules(
            tds_rules,
            event=event,
            on_date=event.effective_date,
            gap_paise=abs(event.amount_paise),
            gross_paise=gross_paise,
            n_txns=1,
            cfg=cfg,
            aliases=aliases,
        )
        gaps.append(
            RuleGap(
                event_ids=(event.event_id,),
                outcome=outcome,
                counterparty_norm=event.counterparty_norm,
                rail=event.rail,
            )
        )
    return tuple(gaps)


#: The demo path's own fixed clock and tenant, matching ``fc.eval.report``'s
#: (hard rule 9: a run is a pure function of the corpus, not of when it was
#: typed) — ``make demo`` and ``make eval`` are different questions asked of
#: the same corpus, and both must answer them the same way twice.
_DEMO_EPOCH_MS = 1_780_000_000_000
_DEMO_CREATED_AT = datetime(2026, 8, 29, tzinfo=UTC)
_DEMO_RUN_ID = "run_demo"


def _run_demo(cfg: Config) -> int:
    if not DATA_DIR.exists():
        print(f"no corpus at {DATA_DIR}; run the generate target first", file=sys.stderr)
        return 1

    corpus = load_corpus()
    rule_set = load_rules(DEFAULT_RULES_PATH, tenant_id=cfg.tenant_id, created_at=_DEMO_CREATED_AT)
    rules = rule_set.rules
    issue_id = deterministic_factory(seed=7, epoch_ms=_DEMO_EPOCH_MS)

    result = run_pipeline(
        corpus.events,
        cfg=cfg,
        rules=rules,
        run_id=_DEMO_RUN_ID,
        tenant_id=cfg.tenant_id,
        issue_id=issue_id,
        created_at=_DEMO_CREATED_AT,
    )
    print(_render(result))
    return 0


def _render(result: PipelineResult) -> str:
    """The §13.5 dashboard headline, as plain text."""
    matched = len(result.cascade.matched_event_ids)
    rule_resolved = sum(1 for gap in result.rule_gaps if gap.outcome.may_auto_close)
    escalated = sum(1 for exc in result.exceptions if exc.tier == "escalate")
    monitored = sum(1 for exc in result.exceptions if exc.tier == "monitor")
    bridge = result.cash_bridge
    lines = [
        "",
        f"{len(result.events)} records · {matched} matched · {rule_resolved} rule-resolved · "
        f"{len(result.exceptions)} exceptions",
        f"-> {len(result.clusters)} root causes · escalate {escalated} · monitor {monitored}",
        "",
        "RECONCILIATION BRIDGE",
        f"  gross collected                            {fmt_inr(bridge.gross_collected_paise)}",
    ]
    for segment in bridge.deductions:
        lines.append(f"  {segment.label:<28}              -{fmt_inr(segment.amount_paise)}")
    net = fmt_inr(bridge.expected_net_paise)
    bank = fmt_inr(bridge.actual_bank_paise)
    gap = fmt_inr(bridge.unexplained_paise)
    lines.append(f"  expected net                                {net}")
    lines.append(f"  bank credited                               {bank}")
    lines.append(f"  unexplained                                 {gap}")
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--demo" not in args:
        print("usage: python -m fc.pipeline --demo", file=sys.stderr)
        return 1
    return _run_demo(load_config())


if __name__ == "__main__":
    raise SystemExit(main())
