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
    match_of: dict[str, MatchResult] = {
        event_id: match for match in cascade.matches for event_id in match.event_ids
    }
    covered: set[str] = set()
    found: list[Classified] = []

    for chargeback in _unrecorded_chargebacks(events, cascade.ledger_refs):
        found.append(chargeback)
        covered.update(chargeback.event_ids)

    for attribution in _ambiguous_order_attribution(events, match_of, cascade.ledger_refs):
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
        if not ids or any(event_id in covered for event_id in ids):
            continue
        if gap.outcome.may_auto_close or gap.outcome.considered == 0:
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
            covered.update(ids)
            continue
        found.append(_from_rule_gap(gap, ids))
        covered.update(ids)

    for match in cascade.matches:
        if match.auto_closed or any(event_id in covered for event_id in match.event_ids):
            continue
        found.append(_from_match(match, by_id))
        covered.update(match.event_ids)

    for event_id in cascade.unmatched_event_ids:
        if event_id in covered:
            continue
        found.append(_from_unmatched(by_id[event_id], events))
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


def _ambiguous_order_attribution(
    events: Sequence[TransactionEvent],
    match_of: Mapping[str, MatchResult],
    ledger_refs: LedgerRefIndex,
) -> tuple[Classified, ...]:
    """Two orders whose ledger Sales leg cannot be told apart — inside a
    settlement whose *cash* is otherwise fully proven.

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
        if event.order_id in named_order_ids:
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


def _from_unmatched(event: TransactionEvent, all_events: Sequence[TransactionEvent]) -> Classified:
    category, reason, expected = _classify_unmatched_event(event, all_events)
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
    event: TransactionEvent, all_events: Sequence[TransactionEvent]
) -> tuple[ExceptionCategory, str, date | None]:
    if event.source == "bank" and event.rail == "nach":
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
        return "missing_in_gateway", "bank credit has no Razorpay settlement row", None
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
