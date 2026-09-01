"""The §6.8 classification tree — deterministic, from evidence already gathered.

Three kinds of leftover feed this: what a matching stage or three-way
resolution already refused (already categorised, at the source, from evidence
in its own hand — see ``fc.matching.stages.StageRefusal``), what the Rulebook
could not fully explain (``fc.rules.apply``), and what never matched at all.
A fourth kind is a sweep rather than a leftover: every dispute-type Razorpay
row is checked against the ledger's own "Disputes" bookings regardless of
whether the matching cascade folded it into an auto-closing settlement group,
because nothing in ``fc.matching`` ever refuses on dispute presence and a
``NEVER_AUTO`` category must not depend on a match's ``auto_closed`` flag to
be seen at all (CLAUDE.md carry-forward: 4 ``chargeback_unrecorded`` events
were sitting inside auto-closed matches for exactly this reason).

No LLM. Every category here is read off fields already on a
:class:`~fc.models.transaction.TransactionEvent`, a
:class:`~fc.matching.stages.StageRefusal` or a
:class:`~fc.rules.apply.RuleOutcomeResult` — CLAUDE.md hard rule 2.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fc.ingest.narration.base import narration_tag
from fc.lanes import LaneMap, assign_lanes
from fc.matching.cascade import CascadeResult
from fc.matching.ledger_refs import LedgerRefIndex
from fc.matching.stages import StageRefusal, reference_is_truncated
from fc.models.exception_ import ExceptionCategory, RuleApplicationRef
from fc.models.match import MatchResult
from fc.models.money import fmt_inr
from fc.models.transaction import TransactionEvent
from fc.rules.apply import RuleOutcomeResult
from fc.rules.learner import amount_band as _amount_band
from fc.rules.learner import signature as _shape_signature

__all__ = ["Classified", "RuleGap", "classify_exceptions"]

#: §6.8's tree names a "timing lag" when a same-amount counterpart exists more
#: than this many days apart. Below it, ``fc.matching.stages.date_shift``
#: would already have matched the pair.
_TIMING_LAG_DAYS = 3


@dataclass(frozen=True)
class RuleGap:
    """One settlement-level gap the Rulebook was asked to explain (§6.7, S3).

    Built by the caller (:mod:`fc.pipeline`) from a ledger receipt and the
    gateway rows it settles — the same arithmetic as
    ``tests/eval/test_rules_corpus.py``'s ``Payout``: "sales were booked at
    gross, the bank paid the net, what happened to the difference." Kept
    separate from :class:`~fc.rules.apply.RuleOutcomeResult` because that
    model does not know which events produced it, and an exception needs to
    name them.
    """

    event_ids: tuple[str, ...]
    outcome: RuleOutcomeResult
    counterparty_norm: str | None
    rail: str | None


@dataclass(frozen=True)
class Classified:
    """One §6.8 finding: a category, the events it concerns, and the facts
    :mod:`.cluster`, :mod:`.tier`, :mod:`.priority`, :mod:`.recommend` and
    :mod:`.consequence` each need to do their own job.

    Deliberately not :class:`fc.models.exception_.Exception_` — that model
    needs a tier, a priority score, a signature-derived id and a run/tenant
    stamp, none of which classification is entitled to invent (the same
    reason ``StageRefusal`` is not an ``Exception_`` either).
    """

    event_ids: tuple[str, ...]
    category: ExceptionCategory
    amount_paise: int
    residual_paise: int
    reason: str
    confidence: Decimal
    counterparty_norm: str | None = None
    rail: str | None = None
    gross_paise: int = 0
    gap_paise: int = 0
    rules_applied: tuple[RuleApplicationRef, ...] = ()
    match_id: str | None = None
    expected_resolution_date: date | None = None
    #: Overrides ``amount_paise`` for :func:`fc.exceptions.priority.priority_score`
    #: only — display and clustering still read the real amount. ``None`` means
    #: "use ``amount_paise``". Exists for findings where real rupees are
    #: involved but none of them are actually at risk (an order-attribution
    #: question inside a settlement whose cash is already proven, not a cash
    #: question at all), so the ranking weight should not be driven by a
    #: number that has nothing to do with what makes the item urgent.
    priority_amount_paise: int | None = None

    @property
    def priority_amount(self) -> int:
        if self.priority_amount_paise is not None:
            return self.priority_amount_paise
        return self.amount_paise

    @property
    def signature(self) -> str:
        """§8.8's shape hash, stored on ``exceptions.signature`` for 3x learning."""
        return _shape_signature(
            category=self.category,
            counterparty_norm=self.counterparty_norm,
            rail=self.rail,
            amount_paise=self.amount_paise,
            gap_paise=self.gap_paise or self.residual_paise,
            gross_paise=self.gross_paise or self.amount_paise,
        )

    @property
    def amount_band(self) -> str:
        return _amount_band(self.amount_paise)


def classify_exceptions(
    events: Sequence[TransactionEvent],
    cascade: CascadeResult,
    *,
    rule_gaps: Sequence[RuleGap] = (),
    lanes: LaneMap | None = None,
) -> tuple[Classified, ...]:
    """Turn cascade leftovers, rule gaps and unbooked disputes into findings.

    Every event lands in at most one :class:`Classified`. Once an event is
    accounted for by a more specific finding — a chargeback sweep hit, a
    stage's own refusal, a rule gap — the rest of its match group is not also
    given a second, vaguer exception for the same money: the group's story is
    already told by the specific finding, and doubling it would inflate the
    "~41 exceptions" the pipeline promises down to something a human cannot
    trust the count of.
    """
    by_id = {event.event_id: event for event in events}
    lanes = lanes if lanes is not None else assign_lanes(events)
    match_of: dict[str, MatchResult] = {
        event_id: match for match in cascade.matches for event_id in match.event_ids
    }
    covered: set[str] = set()
    #: Ids the rule-gap loop decided were not a Rulebook question at all
    #: (``considered == 0``) or were fully explained by one
    #: (``may_auto_close``) — real conclusions about the *arithmetic*, but
    #: neither is a claim that a bank row was ever found for the money. Kept
    #: separate from ``covered`` so the fallback sweep below does not raise
    #: a second, individual finding for them (the original reason this set
    #: exists), while ``_settled_without_bank_credit`` — which asks a
    #: different question, "did the credit arrive" — still gets to fire.
    silenced: set[str] = set()
    found: list[Classified] = []

    for chargeback in _unrecorded_chargebacks(events, cascade.ledger_refs):
        found.append(chargeback)
        covered.update(chargeback.event_ids)

    # A stage refusal is a more specific question than order attribution — a
    # credit ambiguous between two whole settlements already explains why
    # those settlements' orders can't be told apart individually; asking the
    # narrower question again would raise the same money as two unrelated
    # findings instead of one.
    refused_ids = frozenset(
        event_id for refusal in cascade.refusals for event_id in refusal.event_ids
    )
    for attribution in _ambiguous_order_attribution(
        events, match_of, cascade.ledger_refs, exclude=refused_ids
    ):
        found.append(attribution)
        covered.update(attribution.event_ids)

    for refusal in cascade.refusals:
        ids = tuple(event_id for event_id in refusal.event_ids if event_id in by_id)
        if not ids or any(event_id in covered for event_id in ids):
            continue
        found.append(_from_refusal(refusal, ids, by_id, match_of))
        covered.update(ids)

    for gap in rule_gaps:
        ids = tuple(event_id for event_id in gap.event_ids if event_id in by_id)
        if not ids or any(event_id in covered or event_id in silenced for event_id in ids):
            continue
        if gap.outcome.may_auto_close:
            covered.update(ids)
            continue
        if gap.outcome.considered == 0:
            # Fully explained, or no rule was ever scoped to this counterparty
            # at all (``considered == 0``) — own-store settlements land here,
            # since every rule in the starter pack that could apply to a
            # batch-level ledger receipt is scoped by ``method``, which a
            # batch event never carries (CLAUDE.md: "there is no single MDR
            # rate for a batch, so there is no batch-level rule" for
            # own-store). That gap is not unexplained; it was never the
            # Rulebook's question to answer — fc.matching's fee_adjusted
            # stage already proved the same batch per-transaction, using the
            # observed fee_paise/tax_paise the cash bridge also reads. A rule
            # that was *considered* and failed is a finding; a counterparty
            # with zero rules scoped to it is silence, not a finding, and
            # treating it as one is what produced 58 false amount_variance
            # exceptions on the real corpus before this guard existed.
            silenced.update(ids)
            continue
        found.append(_from_rule_gap(gap, ids))
        covered.update(ids)

    for match in cascade.matches:
        if match.auto_closed or any(event_id in covered for event_id in match.event_ids):
            continue
        if _nothing_to_report(match):
            covered.update(match.event_ids)
            continue
        found.append(_from_match(match, by_id))
        covered.update(match.event_ids)

    # A sweep, not a leftover, for the same reason chargebacks are one: a
    # settlement Razorpay has released the hold on and no stage ever
    # attributed a bank row to must always be raised, regardless of why
    # nothing else raised it. Run last, after matches and rule gaps have
    # had their chance, so a settlement with a genuine, more specific
    # finding (a real amount_variance the Rulebook was actually asked
    # about, a stage refusal) keeps that finding — this only fires on what
    # survives every other mechanism untouched. It ran into exactly that
    # gap once when tried earlier in this function: a settlement with no
    # rule scoped to its counterparty reads as `considered == 0` to the
    # rule-gap loop above, which correctly treats "nobody asked a Rulebook
    # question" as silence and marks it covered — which then also silenced
    # the one thing that should never be silent, the settlement never
    # reaching the bank at all.
    for missing in _settled_without_bank_credit(events, cascade, covered=covered):
        found.append(missing)
        covered.update(missing.event_ids)

    for held in _booked_but_never_settled(events, cascade.ledger_refs, covered=covered):
        found.append(held)
        covered.update(held.event_ids)

    for event_id in cascade.unmatched_event_ids:
        if event_id in covered or event_id in silenced:
            continue
        found.append(_from_unmatched(by_id[event_id], events, lanes))
        covered.add(event_id)

    return tuple(found)


def _unrecorded_chargebacks(
    events: Sequence[TransactionEvent], ledger_refs: LedgerRefIndex
) -> tuple[Classified, ...]:
    """Dispute rows with no ledger leg booking them — regardless of match state.

    ``fc.ingest.tally``'s "Disputes" journal narrates ``Chargeback order
    {order_id}``, so the order id it books is exactly what
    :func:`fc.matching.ledger_refs.index_ledger_refs` already extracted. A
    Razorpay dispute row whose order id is not among them is unrecorded — a
    fact readable from production fields alone, with no ground truth involved.
    """
    booked_order_ids: set[str] = set()
    for event in events:
        if event.source == "ledger" and event.ledger_account == "Disputes":
            booked_order_ids.update(ledger_refs.for_event(event.event_id).order_ids)

    out: list[Classified] = []
    for event in events:
        # A dispute row is a chargeback only when it debits the settlement.
        # The same txn_type on a credit is the reversal — money already back
        # in the merchant's favour, not a loss needing a human decision, and
        # nothing to "record" against a ledger that never needed to know
        # about a chargeback that got undone before it was ever booked.
        if event.source != "razorpay" or event.txn_type != "dispute" or event.direction != "debit":
            continue
        if event.order_id and event.order_id in booked_order_ids:
            continue
        dispute_id = event.raw.get("dispute_id") if isinstance(event.raw, dict) else None
        amount = abs(event.amount_paise)
        out.append(
            Classified(
                event_ids=(event.event_id,),
                category="chargeback_unrecorded",
                amount_paise=amount,
                residual_paise=amount,
                reason=(
                    f"dispute {dispute_id or event.event_id} debited {fmt_inr(amount)} and no "
                    "ledger leg records it"
                ),
                confidence=Decimal(1),
                counterparty_norm=event.counterparty_norm,
                rail=event.rail,
                gross_paise=amount,
                gap_paise=amount,
            )
        )
    return tuple(out)


def _settled_without_bank_credit(
    events: Sequence[TransactionEvent], cascade: CascadeResult, *, covered: set[str]
) -> tuple[Classified, ...]:
    """A settlement whose hold has released, with no bank row ever
    attributed to it by any stage — the batch's whole payout, not any one
    of its rows, since "missing_in_bank" is a claim about the credit that
    never arrived, not about a line item.

    ``on_hold`` is the field this build has for "settled" (PRD's Razorpay
    row carries its own ``settled`` boolean, but nothing propagates it onto
    ``TransactionEvent`` today, and adding a column is a schema change this
    fix does not need): a row still on hold has not settled yet by
    definition, so it is excluded rather than flagged as a settlement that
    should have reached the bank and did not.

    Scoped to whole settlements, not individual rows, because a partially-
    matched settlement (some of its rows folded into a group, some not) is
    a different, narrower question already covered by whatever claimed the
    matched rows — this only fires when *none* of a settlement's rows were
    ever attributed anywhere.
    """
    # A bank leg, not a match. A settlement whose gateway rows joined only a
    # ledger receipt is matched, at confidence 1.00, and proves nothing about
    # whether the money arrived: the processor's report and the merchant's
    # books are both statements of what *should* have happened, and this sweep
    # asks whether it did. Keying on ``matched_event_ids`` let a payout with no
    # bank credit at all close silently on gateway-and-books agreement, which
    # is the one outcome this function exists to prevent.
    bank_backed: set[str] = set()
    for match in cascade.matches:
        if "bank" in match.sources_covered:
            bank_backed.update(match.event_ids)

    # A settlement whose UTR appears on a bank row was paid, whatever the
    # matcher made of it. It may have arrived short, or landed in a credit two
    # settlements could each claim — both are real findings, and both are
    # raised elsewhere, by the stage that can see the amount. Neither is "the
    # payout never came", which is what this sweep exists to say and what makes
    # its output the thing a controller chases the processor about.
    banked_references = {e.utr for e in events if e.source == "bank" and e.utr}
    banked_references |= {e.rrn for e in events if e.source == "bank" and e.rrn}

    by_settlement: dict[str, list[TransactionEvent]] = {}
    for event in events:
        if event.source == "razorpay" and event.settlement_id and not event.on_hold:
            by_settlement.setdefault(event.settlement_id, []).append(event)

    out: list[Classified] = []
    for settlement_id, rows in sorted(by_settlement.items()):
        if any(row.event_id in bank_backed or row.event_id in covered for row in rows):
            continue
        banked = [row for row in rows if row.utr and row.utr in banked_references]
        if banked:
            # The credit arrived, and it did not agree. Saying "no bank credit
            # was attributed" would be false, and saying nothing would leave a
            # short-paid settlement with no finding of its own — which is how a
            # ₹18,475.40 shortfall came to be described only as an orphan bank
            # row on one side and an unmatched receipt on the other, with
            # nothing naming the settlement they are both about.
            net = sum(-r.amount_paise if r.direction == "debit" else r.amount_paise for r in rows)
            received = sum(
                e.bank_signed_paise
                for e in events
                if e.source == "bank" and e.utr and e.utr in {r.utr for r in banked}
            )
            shortfall = abs(net) - received
            if shortfall:
                rows = sorted(rows, key=lambda r: r.event_id)
                out.append(
                    Classified(
                        event_ids=tuple(r.event_id for r in rows),
                        category="amount_variance",
                        amount_paise=abs(shortfall),
                        residual_paise=abs(shortfall),
                        reason=(
                            f"settlement {settlement_id} released {fmt_inr(abs(net))} and the "
                            f"bank credited {fmt_inr(received)} against the same UTR; "
                            f"{fmt_inr(abs(shortfall))} of the payout is unaccounted for"
                        ),
                        confidence=Decimal(1),
                        counterparty_norm=rows[0].counterparty_norm,
                        rail=rows[0].rail,
                        gross_paise=abs(net),
                        gap_paise=abs(shortfall),
                    )
                )
            continue
        rows = sorted(rows, key=lambda r: r.event_id)
        net = sum(-r.amount_paise if r.direction == "debit" else r.amount_paise for r in rows)
        amount = abs(net)
        utrs = sorted({r.utr for r in rows if r.utr})
        settled_date = max((r.effective_date for r in rows), default=None)
        utr_note = f", UTR {utrs[0]}" if utrs else ""
        date_note = f" (settled {settled_date.isoformat()})" if settled_date else ""
        out.append(
            Classified(
                event_ids=tuple(r.event_id for r in rows),
                category="missing_in_bank",
                amount_paise=amount,
                residual_paise=amount,
                reason=(
                    f"settlement {settlement_id} net {fmt_inr(amount)}{utr_note} released by "
                    f"Razorpay{date_note}, no bank credit was attributed to it by any stage"
                ),
                confidence=Decimal(1),
                counterparty_norm=rows[0].counterparty_norm,
                rail=rows[0].rail,
                gross_paise=amount,
                gap_paise=amount,
                expected_resolution_date=settled_date,
            )
        )
    return tuple(out)


def _booked_but_never_settled(
    events: Sequence[TransactionEvent],
    ledger_refs: LedgerRefIndex,
    *,
    covered: set[str],
) -> tuple[Classified, ...]:
    """Revenue in the books against money the processor is still holding.

    A payment captured with ``on_hold`` set has not settled and may never; it
    is deliberately excluded from :func:`_settled_without_bank_credit`, because
    a payout that was never released is not a payout that went missing. But the
    sales invoice for it is already booked, and that is a cut-off problem with
    a real answer — hold the revenue or reverse it — which nothing else in the
    tree can see, since a held row simply never reaches the bank and so never
    becomes a leftover anybody asks about.

    Fires only where the books have actually recognised the order, so it is
    evidence and not a lecture about the ``on_hold`` flag.
    """
    booked_order_ids: set[str] = set()
    for event in events:
        if event.source == "ledger":
            booked_order_ids.update(ledger_refs.for_event(event.event_id).order_ids)

    out: list[Classified] = []
    for event in sorted(events, key=lambda e: e.event_id):
        if event.source != "razorpay" or not event.on_hold or event.event_id in covered:
            continue
        if not event.order_id or event.order_id not in booked_order_ids:
            continue
        amount = abs(event.amount_paise) + (event.fee_paise or 0)
        out.append(
            Classified(
                event_ids=(event.event_id,),
                category="revenue_booked_not_settled",
                amount_paise=amount,
                residual_paise=amount,
                reason=(
                    f"order {event.order_id} is booked as a sale for {fmt_inr(amount)} but the "
                    "payment is still on hold at the gateway and has never settled; the "
                    "revenue is recognised against cash that has not been collected"
                ),
                confidence=Decimal(1),
                counterparty_norm=event.counterparty_norm,
                rail=event.rail,
                gross_paise=amount,
                gap_paise=amount,
            )
        )
    return tuple(out)


def _ambiguous_order_attribution(
    events: Sequence[TransactionEvent],
    match_of: Mapping[str, MatchResult],
    ledger_refs: LedgerRefIndex,
    *,
    exclude: frozenset[str] = frozenset(),
) -> tuple[Classified, ...]:
    """Two orders whose ledger Sales leg cannot be told apart — inside a
    settlement whose *cash* is otherwise fully proven.

    ``exclude`` is the event ids a stage refusal already named — an order
    named there is already part of a broader "which settlement" ambiguity,
    a question this function's narrower "which order within one settlement"
    framing does not apply to and must not re-ask.

    Two separate claims, and this function exists to keep them separate: the
    settlement auto-closes (the bank credit, the gateway rows and the
    ledger's total all agree to the paise — nothing here challenges that),
    but if two orders in it settled the same gross with a ledger Sales
    narration that names neither, no evidence anywhere says which order the
    which voucher belongs to. That is a bookkeeping question, not a cash one,
    so it is scoped to just the ambiguous orders and given no priority weight
    for money that was never actually at risk (:attr:`Classified.priority_amount_paise`).

    This is what actually happened to the 10 ``ambiguous_multi_candidate``
    events CLAUDE.md's carry-forward note found sitting inside auto-closed
    matches: not a matching bug, but a real, separate, smaller finding the
    pipeline used to have no way to raise at all.
    """
    named_order_ids: set[str] = set()
    for event in events:
        if event.source == "ledger":
            named_order_ids.update(ledger_refs.for_event(event.event_id).order_ids)

    buckets: dict[tuple[str | None, int], list[TransactionEvent]] = {}
    for event in events:
        if event.source != "razorpay" or event.txn_type != "payment" or not event.order_id:
            continue
        if event.order_id in named_order_ids or event.event_id in exclude:
            continue
        gross = event.amount_paise + (event.fee_paise or 0)
        match = match_of.get(event.event_id)
        key = (match.match_id if match is not None else None, gross)
        buckets.setdefault(key, []).append(event)

    out: list[Classified] = []
    for (_match_id, gross), members in sorted(
        buckets.items(), key=lambda item: (item[0][0] or "", item[0][1])
    ):
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda event: event.event_id)
        order_ids = ", ".join(event.order_id or "" for event in members)
        out.append(
            Classified(
                event_ids=tuple(event.event_id for event in members),
                category="ambiguous_multi_candidate",
                amount_paise=gross,
                residual_paise=0,
                reason=(
                    f"{len(members)} orders ({order_ids}) settled the same {fmt_inr(gross)} "
                    "gross and none of their ledger Sales vouchers names an order; the "
                    "settlement's cash is proven, only which order is which is not"
                ),
                confidence=Decimal(1),
                counterparty_norm=_common(event.counterparty_norm for event in members),
                rail=_common(event.rail for event in members),
                gross_paise=gross,
                gap_paise=0,
                priority_amount_paise=0,
            )
        )
    return tuple(out)


def _from_refusal(
    refusal: StageRefusal,
    ids: tuple[str, ...],
    by_id: Mapping[str, TransactionEvent],
    match_of: Mapping[str, MatchResult],
) -> Classified:
    members = [by_id[event_id] for event_id in ids]
    confidences = [match_of[event_id].confidence for event_id in ids if event_id in match_of]
    match_ids = {match_of[event_id].match_id for event_id in ids if event_id in match_of}
    amount = abs(refusal.amount_paise)
    return Classified(
        event_ids=ids,
        category=refusal.category,
        amount_paise=amount,
        residual_paise=amount,
        reason=refusal.reason,
        confidence=min(confidences) if confidences else Decimal(1),
        counterparty_norm=_common(m.counterparty_norm for m in members),
        rail=_common(m.rail for m in members),
        gross_paise=amount,
        gap_paise=amount,
        match_id=next(iter(match_ids)) if len(match_ids) == 1 else None,
    )


def _from_rule_gap(gap: RuleGap, ids: tuple[str, ...]) -> Classified:
    outcome = gap.outcome
    return Classified(
        event_ids=ids,
        category="amount_variance",
        amount_paise=abs(outcome.residual_paise),
        residual_paise=abs(outcome.residual_paise),
        reason=outcome.narrative(),
        confidence=outcome.confidence_ceiling,
        counterparty_norm=gap.counterparty_norm,
        rail=gap.rail,
        gross_paise=abs(outcome.gross_paise),
        gap_paise=abs(outcome.gap_before_paise),
        rules_applied=outcome.as_exception_refs(),
    )


def _nothing_to_report(match: MatchResult) -> bool:
    """A group that did not auto-close but has nothing wrong with it.

    Outside the gateway lane a movement has two sides, not three: a rent
    payment, a POS terminal settlement and a marketplace payout are proven by
    the statement and the daybook agreeing, and there is no third file to ask.
    Such a group matched on amount, date and counterparty is a *fuzzy* match by
    construction, so it is capped at 0.75 and may never auto-close (CLAUDE.md,
    enforced by assertion) — and that cap is a statement about how the group
    was proven, not a defect in it.

    Treating the cap as a defect put 21 exactly-agreeing rent, salary, ad-spend
    and vendor payments into a human queue with the category ``unknown``, which
    is both untrue and the fastest way to make a queue unreadable. So a group
    is passed over when it disagrees about nothing: no residual, no date shift
    past the timing window, one candidate, and no gateway leg whose absence a
    third source could have contradicted.

    A gateway group is deliberately excluded from this and keeps the old
    behaviour exactly: there a third file does exist, and a group that fails to
    close there has a missing leg worth naming.
    """
    if "razorpay" in match.sources_covered:
        return False
    if match.residual_paise != 0:
        return False
    if max((leg.date_shift_days for leg in match.evidence), default=0) > _TIMING_LAG_DAYS:
        return False
    return max((leg.candidates_considered for leg in match.evidence), default=1) <= 1


def _from_match(match: MatchResult, by_id: Mapping[str, TransactionEvent]) -> Classified:
    """A group that formed but did not clear the auto-close bar.

    Category follows the same tree, applied to what the match's own evidence
    already proved: a date shift beyond the timing window, a nonzero residual,
    or candidates the forming stage itself counted as more than one.
    """
    members = [by_id[event_id] for event_id in match.event_ids if event_id in by_id]
    max_shift = max((leg.date_shift_days for leg in match.evidence), default=0)
    max_candidates = max((leg.candidates_considered for leg in match.evidence), default=1)

    if max_shift > _TIMING_LAG_DAYS:
        category: ExceptionCategory = "timing_lag"
    elif match.residual_paise != 0:
        category = "amount_variance"
    elif max_candidates > 1:
        category = "ambiguous_multi_candidate"
    else:
        category = "unknown"

    amount = abs(match.residual_paise) or max((abs(m.amount_paise) for m in members), default=0)
    expected_resolution = max((m.effective_date for m in members), default=None)
    return Classified(
        event_ids=tuple(match.event_ids),
        category=category,
        amount_paise=amount,
        residual_paise=abs(match.residual_paise),
        reason=(
            f"matched at {match.stage} stage, confidence {match.confidence} below the "
            "auto-close threshold"
        ),
        confidence=match.confidence,
        counterparty_norm=_common(m.counterparty_norm for m in members),
        rail=_common(m.rail for m in members),
        gross_paise=max((abs(m.amount_paise) for m in members), default=amount),
        gap_paise=abs(match.residual_paise),
        match_id=match.match_id,
        expected_resolution_date=expected_resolution if category == "timing_lag" else None,
    )


def _from_unmatched(
    event: TransactionEvent, all_events: Sequence[TransactionEvent], lanes: LaneMap
) -> Classified:
    category, reason, expected = _classify_unmatched_event(event, all_events, lanes)
    amount = abs(event.amount_paise)
    return Classified(
        event_ids=(event.event_id,),
        category=category,
        amount_paise=amount,
        residual_paise=amount,
        reason=reason,
        confidence=Decimal(1),
        counterparty_norm=event.counterparty_norm,
        rail=event.rail,
        gross_paise=amount,
        gap_paise=amount,
        expected_resolution_date=expected,
    )


def _classify_unmatched_event(
    event: TransactionEvent, all_events: Sequence[TransactionEvent], lanes: LaneMap
) -> tuple[ExceptionCategory, str, date | None]:
    """What a leftover row means, asked of the counterpart its lane actually has.

    ``missing_in_gateway`` is a real finding for a bank credit that should have
    a settlement behind it and does not. Asked of a rent RTGS, a GST challan or
    a salary NACH it is nonsense — the gateway never had them, and saying so
    put 61 rows into one queue where the six that mattered could not be seen.
    So the question is scoped by lane: outside the gateway lane the counterpart
    is the daybook, and a bank row with no daybook entry behind it is a
    *booking that has not been made*, not money that has gone missing.
    """
    lane = lanes.lane(event.event_id)

    # A batch line, not a single mandate. The tag is what says so: NACH names a
    # sponsor-bank batch covering hundreds of mandates that no file here can
    # decompose, while ACH names one direct debit, which has a counterpart in
    # the books like any other payment and must not be excused as unexplodable.
    if event.source == "bank" and narration_tag(event.raw_narration or "").startswith("NACH"):
        return (
            "nach_batch_unexploded",
            "NACH batch line; mandates are not decomposed by design",
            None,
        )
    if event.source == "razorpay" and event.txn_type == "refund":
        return (
            "partial_refund",
            f"refund of {fmt_inr(abs(event.amount_paise))} has no matching bank leg",
            None,
        )

    candidate = _timing_candidate(event, all_events)
    if candidate is not None:
        days = abs((event.effective_date - candidate.effective_date).days)
        later = max(event.effective_date, candidate.effective_date)
        return (
            "timing_lag",
            f"same amount as a {candidate.source} row {days} days apart",
            later,
        )

    if event.source == "bank" and reference_is_truncated(event):
        return (
            "reference_truncated",
            "narration truncated; the reference cannot be trusted for matching",
            None,
        )

    if event.source == "razorpay":
        return "missing_in_bank", "settled by Razorpay; no matching bank credit found", None

    if event.source == "bank":
        if lane == "gateway":
            return "missing_in_gateway", "bank credit has no Razorpay settlement row", None
        party = event.counterparty_norm or "an unnamed counterparty"
        # Direction decides which finding this is, and the two are genuinely
        # different work. Money that *arrived* and that no voucher, gateway row
        # or reference accounts for cannot be resolved from the files at all —
        # somebody has to be asked where it came from, and until they answer
        # the amount is sitting safely in the account, not exposed. Money that
        # *left* and was never written down is a booking that has not been made
        # yet: the evidence is complete, the entry just does not exist, and the
        # agent can propose it. Folding the two together is what made a
        # ₹2,86,440 inward remittance read as exposure.
        if event.direction == "credit":
            return (
                "unidentified_inflow",
                f"{fmt_inr(abs(event.amount_paise))} arrived from {party} and nothing in "
                "the gateway file or the daybook says what it settles",
                None,
            )
        return (
            "unbooked_bank_entry",
            f"the statement paid {fmt_inr(abs(event.amount_paise))} to {party} in the "
            f"{lane} lane and the daybook has no voucher for it",
            None,
        )

    return "missing_in_bank", "ledger entry has no bank leg behind it", None


def _timing_candidate(
    event: TransactionEvent, all_events: Sequence[TransactionEvent]
) -> TransactionEvent | None:
    """The nearest same-amount row in the opposite source, more than the
    timing window apart — cheaper stages would already have claimed anything
    closer, so a same-amount pair surviving to here says the money is right
    and only the date is wrong."""
    if event.source == "razorpay":
        opposite = "bank"
    elif event.source == "bank":
        opposite = "razorpay"
    else:
        return None

    amount = abs(event.amount_paise)
    best: TransactionEvent | None = None
    best_days = 0
    for other in all_events:
        if other.source != opposite or other.event_id == event.event_id:
            continue
        if abs(other.amount_paise) != amount:
            continue
        days = abs((event.effective_date - other.effective_date).days)
        if days <= _TIMING_LAG_DAYS:
            continue
        if best is None or days < best_days:
            best, best_days = other, days
    return best


def _common(values: Iterable[str | None]) -> str | None:
    found = {value for value in values if value}
    return next(iter(found)) if len(found) == 1 else None
