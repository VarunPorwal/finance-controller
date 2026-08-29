"""Three-way resolution — PRD §6.4, differentiator D7.

Most builds reconcile gateway against bank. This one adds the ledger, because a
transaction can match the bank *perfectly* and still be wrong in the books. The
canonical case is a duplicate voucher: the money moved once, the books say twice,
and the bank agrees with the gateway all along. Two-way reconciliation is
structurally incapable of seeing it - there is nothing to disagree with.

Runs **after** two-way matching, over the groups the cascade formed, not instead
of it. Three things happen here.

**The duplicate audit, and why it looks inside groups.** §6.4 reads "two or more
found → duplicate_ledger_entry", which invites searching the *unmatched* pool for
a second leg. On real data that finds nothing: both duplicate receipts quote the
same settlement id, so stage 1 unions them into the group and neither is left
over. The duplicate has to be caught where it actually is - already inside an
auto-closing group, at confidence 1.0.

Nor can it be caught by counting ledger rows. A healthy settlement group holds a
Sales voucher per order, a Receipt, and Journals for MDR, GST, TDS and reserve:
groups of nine to forty-five ledger legs are normal here, and a naive
"more than one leg" test would condemn nearly every settlement in the corpus. So
duplication is judged on a *signature* - two legs are duplicates when they are
indistinguishable as money movements while carrying different voucher
identities.

**Attachment.** A gateway↔bank group with no ledger leg looks for one by order
id, then by narration identity claim, then by amount and date - §6.4's order,
most reliable first. Exactly one attaches and the group becomes three-way. None
is ``missing_in_ledger``. Two or more is ``duplicate_ledger_entry`` and nothing
is attached, because choosing between them would be the guess this stage exists
to refuse.

**No new stage.** ``MatchStage`` gains nothing. An attached leg is stamped with
the stage that actually proved it: ``exact_ref`` when a reference did, ``fuzzy``
when only amount and date did. The second is honest - an amount-and-date
attribution *is* a fuzzy one - and it inherits the 0.75 cap and the
never-auto-close rule from machinery that already exists, rather than needing a
parallel set of guarantees written for three-way alone.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from fc.config import Config
from fc.matching.confidence import ConfidenceInputs, derive
from fc.matching.ledger_refs import LedgerRefIndex
from fc.matching.stages import StageRefusal
from fc.matching.tolerance import tolerance_terms
from fc.models.match import MatchEvidence, MatchResult, MatchStage, group_confidence_cap
from fc.models.transaction import Source, TransactionEvent

__all__ = ["ThreeWayOutcome", "leg_signature", "resolve"]

#: The cash-side voucher: the one that claims to *be* the settlement's money
#: movement. Journals record its consequences (MDR, GST, TDS, reserve) and are
#: expected to be many; two Receipts for one movement are not.
_CASH_VOUCHERS = frozenset({"Receipt", "Payment", "Contra"})

_LEDGER: Source = "ledger"


@dataclass(frozen=True)
class ThreeWayOutcome:
    """What §6.4 changed about the cascade's groups."""

    matches: tuple[MatchResult, ...]
    refusals: tuple[StageRefusal, ...] = ()
    #: Ledger rows newly pulled into a group, so the cascade can claim them.
    attached_event_ids: frozenset[str] = field(default_factory=frozenset)
    bonus_applied: int = 0
    diagnostics: Mapping[str, int] = field(default_factory=dict)


def leg_signature(event: TransactionEvent) -> tuple[str, ...]:
    """What makes two ledger legs the same money movement.

    Deliberately excludes ``voucher_number`` and ``voucher_guid``: those are what
    make the two rows *different records*, and a duplicate voucher is precisely
    one money movement recorded under two identities. Includes the narration
    because a Sales voucher and a Receipt for the same rupee amount on the same
    day are two legitimate legs of one settlement, not a duplication.
    """
    return (
        event.voucher_type or "",
        event.direction,
        str(event.amount_paise),
        event.effective_date.isoformat(),
        (event.raw_narration or "").strip().upper(),
    )


def resolve(
    matches: Sequence[MatchResult],
    events: Sequence[TransactionEvent],
    *,
    claimed: frozenset[str],
    ledger_refs: LedgerRefIndex,
    cfg: Config,
) -> ThreeWayOutcome:
    """Audit each group for duplicate legs, then attach the missing ones."""
    by_id = {event.event_id: event for event in events}
    free_ledger = sorted(
        (e for e in events if e.source == _LEDGER and e.event_id not in claimed),
        key=lambda e: e.event_id,
    )

    resolved: list[MatchResult] = []
    refusals: list[StageRefusal] = []
    attached: set[str] = set()
    bonus_applied = 0
    counters = {
        "duplicate_legs_found": 0,
        "legs_attached_by_reference": 0,
        "legs_attached_by_amount_and_date": 0,
        "groups_missing_a_ledger_leg": 0,
        "groups_with_rival_legs": 0,
        "groups_already_three_way": 0,
    }

    for match in matches:
        members = [by_id[event_id] for event_id in match.event_ids if event_id in by_id]
        duplicates = _duplicate_legs(members)
        if duplicates:
            counters["duplicate_legs_found"] += 1
            refusals.append(
                StageRefusal(
                    category="duplicate_ledger_entry",
                    event_ids=duplicates,
                    amount_paise=sum(abs(by_id[e].amount_paise) for e in duplicates),
                    reason=(
                        f"{len(duplicates)} ledger legs in this group record the same "
                        "money movement under different voucher identities; the books "
                        "say it happened more than once and the bank says it happened "
                        "once"
                    ),
                )
            )
            # The group itself stands - the money did move, and the gateway and
            # bank agree about it. What it may not do is close on its own.
            resolved.append(match)
            continue

        if any(member.source == _LEDGER for member in members):
            counters["groups_already_three_way"] += 1
            resolved.append(match)
            continue

        candidates = _ledger_candidates(match, members, free_ledger, ledger_refs, cfg=cfg)
        if not candidates:
            counters["groups_missing_a_ledger_leg"] += 1
            refusals.append(
                StageRefusal(
                    category="missing_in_ledger",
                    event_ids=tuple(match.event_ids),
                    amount_paise=max((abs(m.amount_paise) for m in members), default=0),
                    reason=("gateway and bank agree on this movement but no ledger leg records it"),
                )
            )
            resolved.append(match)
            continue

        if len(candidates) > 1:
            counters["groups_with_rival_legs"] += 1
            refusals.append(
                StageRefusal(
                    category="duplicate_ledger_entry",
                    # Names the group as well as the rivals. The finding is about
                    # this movement's ledger attribution, and a refusal listing
                    # only the rows *outside* the group would leave the group
                    # itself free to close at full confidence.
                    event_ids=tuple(
                        sorted({*match.event_ids, *(e.event_id for e, _ in candidates)})
                    ),
                    amount_paise=sum(abs(event.amount_paise) for event, _ in candidates),
                    reason=(
                        f"{len(candidates)} ledger legs could each be this movement; "
                        "attaching one would assert something the books do not say"
                    ),
                )
            )
            resolved.append(match)
            continue

        leg, proof = candidates[0]
        counters[
            "legs_attached_by_reference"
            if proof == "exact_ref"
            else "legs_attached_by_amount_and_date"
        ] += 1
        extended, was_bonused = _attach(match, leg, proof=proof, members=members, cfg=cfg)
        bonus_applied += int(was_bonused)
        attached.add(leg.event_id)
        resolved.append(extended)

    return ThreeWayOutcome(
        matches=tuple(resolved),
        refusals=tuple(refusals),
        attached_event_ids=frozenset(attached),
        bonus_applied=bonus_applied,
        diagnostics=counters,
    )


def _duplicate_legs(members: Sequence[TransactionEvent]) -> tuple[str, ...]:
    """Ledger legs in one group that record the same movement twice.

    Restricted to cash-side vouchers. A settlement books one Receipt and many
    Journals; two Journals sharing a signature are the same deduction described
    twice, which the deduction stack already reconciles. Two Receipts are the
    books claiming the money arrived twice, which is D7's whole subject.
    """
    seen: dict[tuple[str, ...], list[str]] = {}
    for member in members:
        if member.source != _LEDGER:
            continue
        if (member.voucher_type or "") not in _CASH_VOUCHERS:
            continue
        seen.setdefault(leg_signature(member), []).append(member.event_id)

    duplicates = [ids for ids in seen.values() if len(ids) > 1]
    if not duplicates:
        return ()
    return tuple(sorted(event_id for ids in duplicates for event_id in ids))


def _ledger_candidates(
    match: MatchResult,
    members: Sequence[TransactionEvent],
    free_ledger: Sequence[TransactionEvent],
    ledger_refs: LedgerRefIndex,
    *,
    cfg: Config,
) -> list[tuple[TransactionEvent, MatchStage]]:
    """§6.4's lookup, most reliable first: order id, narration, then amount+date.

    Stops at the first path that yields anything. A reference that identifies one
    leg is not improved by also finding three legs of the right size, and mixing
    the two would let a weak signal add rivals to a strong one.
    """
    order_ids = {m.order_id for m in members if m.order_id}
    settlement_ids = {m.settlement_id for m in members if m.settlement_id}

    by_reference = [
        leg
        for leg in free_ledger
        if (leg.order_id and leg.order_id in order_ids)
        or _claims_any(ledger_refs, leg.event_id, order_ids, settlement_ids)
    ]
    if by_reference:
        return [(leg, "exact_ref") for leg in by_reference]

    anchor = max(members, key=lambda m: abs(m.amount_paise), default=None)
    if anchor is None:
        return []
    tolerance = tolerance_terms(abs(anchor.amount_paise), 1, cfg).value
    day = anchor.effective_date.toordinal()
    return [
        (leg, "fuzzy")
        for leg in free_ledger
        if abs(abs(leg.amount_paise) - abs(anchor.amount_paise)) <= tolerance
        and abs(leg.effective_date.toordinal() - day) <= 1
        and not _names_other_movements(ledger_refs, leg.event_id, order_ids, settlement_ids)
    ]


def _names_other_movements(
    ledger_refs: LedgerRefIndex,
    event_id: str,
    order_ids: set[str],
    settlement_ids: set[str],
) -> bool:
    """Whether the narration cites references, none of them this group's.

    Amount and date say two rows are the same size on the same day - the same
    coincidence stage 5 refuses to match on. A row that also *names* settlements,
    and names other people's, has said where it belongs, and attaching it here
    over its own narration would be inventing an attribution. This mirrors stage
    2's ``settlements_refused_on_contradicting_reference`` guard: a contradicting
    reference is evidence against, not absence of evidence.

    A row citing several ids of one kind is excluded too. ``identity_claims``
    already refuses to read such a narration as an identity - "Rolling reserve
    release settlement setl_B for setl_A" names one settlement it belongs to and
    one it refunds, and the text does not say which is which. Letting amount and
    date settle it would decide by the back door exactly what the reference rule
    declined to decide.

    A row citing nothing at all stays eligible - that is the case amount+date
    exists for.
    """
    cited = ledger_refs.for_event(event_id)
    named = {*cited.order_ids, *cited.settlement_ids}
    if not named:
        return False
    claimed = ledger_refs.identity_for_event(event_id)
    identity = {*claimed.order_ids, *claimed.settlement_ids}
    if not identity:
        return True
    return not (identity & {*order_ids, *settlement_ids})


def _claims_any(
    ledger_refs: LedgerRefIndex,
    event_id: str,
    order_ids: set[str],
    settlement_ids: set[str],
) -> bool:
    """Whether the row's narration claims to *be* one of this group's movements.

    ``identity_for_event`` drops any id kind the narration cited more than once,
    so a voucher naming two settlements contributes neither. Extraction is not
    attribution.
    """
    claims = ledger_refs.identity_for_event(event_id)
    return bool(
        (set(claims.order_ids) & order_ids) or (set(claims.settlement_ids) & settlement_ids)
    )


def _attach(
    match: MatchResult,
    leg: TransactionEvent,
    *,
    proof: MatchStage,
    members: Sequence[TransactionEvent],
    cfg: Config,
) -> tuple[MatchResult, bool]:
    """Add the ledger leg, re-deriving confidence with three sources covered."""
    del cfg
    anchor = max(members, key=lambda m: abs(m.amount_paise))
    delta = abs(anchor.amount_paise) - abs(leg.amount_paise)
    days = abs(leg.effective_date.toordinal() - anchor.effective_date.toordinal())

    outcome = derive(
        ConfidenceInputs(
            stage=proof,
            base=match.confidence,
            fields_agreed=1,
            fields_disagreed=0,
            amount_delta_paise=delta,
            amount_basis_paise=abs(anchor.amount_paise),
            days_shift=days,
            n_candidates=1,
            distinct_sources=3,
        )
    )
    evidence = MatchEvidence(
        stage=proof,
        fields_agreed=["order_id"] if proof == "exact_ref" else ["amount_paise", "effective_date"],
        fields_disagreed=[],
        arithmetic=(
            f"ledger leg {leg.voucher_number or leg.event_id} attached by "
            + ("reference" if proof == "exact_ref" else "amount and date")
            + f"; sources covered now gateway, bank and ledger (delta {delta} paise)"
        ),
        delta_paise=delta,
        date_shift_days=days,
        candidates_considered=1,
        grouped_by="three_way:order_id" if proof == "exact_ref" else "three_way:amount_date",
        confidence_derivation=outcome.derivation,
    )
    legs = [*match.evidence, evidence]
    sources: list[Source] = sorted({*match.sources_covered, _LEDGER})
    confidence = min(match.confidence, outcome.derivation.result, group_confidence_cap(legs))

    return (
        match.model_copy(
            update={
                "event_ids": sorted([*match.event_ids, leg.event_id]),
                "sources_covered": sources,
                "confidence": confidence,
                "evidence": legs,
                # Left false here on purpose. The cascade recomputes auto-close
                # across every leg once three-way and the NEVER_AUTO gate have
                # both reported, so the rule lives in exactly one place.
                "auto_closed": False,
            }
        ),
        outcome.bonus_was_load_bearing,
    )
