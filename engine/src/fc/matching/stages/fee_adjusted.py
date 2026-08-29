"""Stage 2, fee-adjusted — PRD §6.3. Base confidence 0.97.

``abs(gross - net - deductions) <= tol``, evaluated over a settlement rather
than a row pair. On a real settlement file a bank credit is never one gateway
payment: it is the batch, net of the deduction stack. Read row-to-row the
predicate is unfalsifiable here - the generated corpus has no settlement with
fewer than two payments - and the ``n_txns * rounding_drift_paise`` term in
§6.5 only means anything when the fee being compared is a sum of per-transaction
roundings. So the settlement is the unit.

This is the stage that closes what stage 1 must refuse: a settlement whose bank
narration was truncated, transposed or never carried the UTR at all still has
arithmetic, and arithmetic does not care what the narration says.

**Tax is not subtracted separately.** ``fee_and_tax`` in the source data returns
``(mdr_base + gst, gst)`` and the payment row's ``credit`` is ``amount - fee``,
so ``tax_paise`` is a *component of* ``fee_paise``, not a further deduction.
Subtracting it again double-counts the GST and makes every batch miss by the
GST amount.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from fc.config import Config
from fc.matching.stages import StageMatch, StageOutput, StageRefusal, trusted_bank_reference
from fc.matching.tolerance import tolerance_terms
from fc.models.money import fmt_inr
from fc.models.transaction import TransactionEvent

__all__ = [
    "BASE_CONFIDENCE",
    "BASE_CONFIDENCE_RATIONALE",
    "SettlementArithmetic",
    "find_matches",
    "settlement_arithmetic",
]

#: §6.3's table. Note this is not derived from anything - see the rationale below.
BASE_CONFIDENCE = Decimal("0.97")

#: The one input to §6.6 that is a judgement rather than a measurement, stated
#: in the evidence pack so a reader is never asked to take the number on trust.
#: The other five factors are arithmetic over the events themselves.
BASE_CONFIDENCE_RATIONALE = (
    "base 0.97, a judgement: settlement arithmetic reconciles to the paise, but no "
    "reference agreement was proven - the batch could in principle belong to another "
    "settlement of identical net."
)

_PAYMENT = "payment"


@dataclass(frozen=True)
class SettlementArithmetic:
    """The deduction stack of one settlement, decomposed for display.

    ``expected_net_paise`` is computed as a signed sum over the settlement's own
    rows - credits minus debits - so it needs no knowledge of MDR rates, TDS
    percentages or reserve terms. The decomposition below exists only to render
    the sum for a human; it never enters the predicate.
    """

    settlement_id: str
    #: Every UTR the settlement's own rows carry. A credit quoting a usable
    #: reference that is not one of these is not this batch, whatever the
    #: arithmetic says.
    utrs: frozenset[str]
    gross_paise: int
    fee_paise: int
    gst_within_fee_paise: int
    deductions: tuple[tuple[str, int], ...]  # (label, paise), all positive
    additions: tuple[tuple[str, int], ...]  # (label, paise), all positive
    expected_net_paise: int
    n_txns: int

    def format_arithmetic(self, *, observed_net_paise: int, tolerance_paise: int) -> str:
        parts = [f"{fmt_inr(self.gross_paise)} gross"]
        if self.fee_paise:
            gst = f" (MDR incl. {fmt_inr(self.gst_within_fee_paise)} GST)"
            parts.append(
                f"- {fmt_inr(self.fee_paise)} fee{gst if self.gst_within_fee_paise else ''}"
            )
        parts.extend(f"- {fmt_inr(amount)} {label}" for label, amount in self.deductions)
        parts.extend(f"+ {fmt_inr(amount)} {label}" for label, amount in self.additions)
        delta = observed_net_paise - self.expected_net_paise
        return (
            f"{' '.join(parts)} = {fmt_inr(self.expected_net_paise)} "
            f"vs bank credit {fmt_inr(observed_net_paise)} "
            f"(delta {fmt_inr(delta)}, tolerance {fmt_inr(tolerance_paise)} "
            f"over {self.n_txns} txns). {BASE_CONFIDENCE_RATIONALE}"
        )


def settlement_arithmetic(
    settlement_id: str, gateway_events: Sequence[TransactionEvent]
) -> SettlementArithmetic:
    """Decompose one settlement's gateway rows into its deduction stack."""
    gross = 0
    fee = 0
    gst = 0
    n_txns = 0
    deductions: list[tuple[str, int]] = []
    additions: list[tuple[str, int]] = []

    for event in sorted(gateway_events, key=lambda e: e.event_id):
        if event.txn_type == _PAYMENT and event.direction == "credit":
            row_fee = event.fee_paise or 0
            gross += event.amount_paise + row_fee
            fee += row_fee
            gst += event.tax_paise or 0
            n_txns += 1
            continue
        label = _label(event)
        if event.direction == "debit":
            deductions.append((label, event.amount_paise))
        else:
            additions.append((label, event.amount_paise))

    expected = (
        gross
        - fee
        - sum(amount for _, amount in deductions)
        + sum(amount for _, amount in additions)
    )
    return SettlementArithmetic(
        settlement_id=settlement_id,
        utrs=frozenset(e.utr for e in gateway_events if e.utr),
        gross_paise=gross,
        fee_paise=fee,
        gst_within_fee_paise=gst,
        deductions=tuple(deductions),
        additions=tuple(additions),
        expected_net_paise=expected,
        n_txns=n_txns,
    )


def find_matches(
    events: Sequence[TransactionEvent], *, unmatched: frozenset[str], cfg: Config
) -> StageOutput:
    """Reconcile each unmatched bank credit against a settlement's arithmetic.

    The settlement sums are computed over **all** its gateway rows, including
    ones an earlier stage already grouped. A batch's arithmetic is a property of
    the batch; recomputing it from whatever happens to be left over would make
    the total depend on what stage 1 did, and a partial batch never reconciles.
    Only the bank credit is being decided here, so only it is an anchor.

    Abstains when two or more settlements reconcile to the same credit. Two
    valid answers is not a reason to pick one (CLAUDE.md hard rule 4); it is an
    ``ambiguous_multi_candidate`` for the exception pipeline to raise.
    """
    by_settlement: dict[str, list[TransactionEvent]] = {}
    for event in events:
        if event.source == "razorpay" and event.settlement_id:
            by_settlement.setdefault(event.settlement_id, []).append(event)

    arithmetic = {
        sid: settlement_arithmetic(sid, rows) for sid, rows in sorted(by_settlement.items())
    }
    credits = sorted(
        (
            e
            for e in events
            if e.source == "bank" and e.direction == "credit" and e.event_id in unmatched
        ),
        key=lambda e: e.event_id,
    )

    matches: list[StageMatch] = []
    refusals: list[StageRefusal] = []
    bindings: dict[str, int] = {}
    contradicted = 0
    for credit in credits:
        reference = trusted_bank_reference(credit)
        reconciling: list[tuple[str, int, int]] = []  # (settlement_id, delta, tolerance)
        for sid, sums in arithmetic.items():
            # Arithmetic rescues a credit whose reference is unusable; it does
            # not get to overrule one that is usable and disagrees. A standalone
            # direct NEFT quoting its own UTR will occasionally reconcile to
            # some batch's net by coincidence, and without this it is silently
            # absorbed into that batch instead of being raised as
            # missing_in_gateway. A transposed UTR fails here too, correctly:
            # the digits do not match and a human should see it.
            if reference is not None and sums.utrs and reference not in sums.utrs:
                contradicted += 1
                continue
            terms = tolerance_terms(sums.gross_paise, sums.n_txns, cfg)
            delta = credit.amount_paise - sums.expected_net_paise
            if abs(delta) <= terms.value:
                reconciling.append((sid, delta, terms.value))
                bindings[terms.binding] = bindings.get(terms.binding, 0) + 1

        if not reconciling:
            continue
        if len(reconciling) > 1:
            refusals.append(
                StageRefusal(
                    category="ambiguous_multi_candidate",
                    event_ids=(credit.event_id,),
                    amount_paise=credit.amount_paise,
                    reason=(
                        f"{len(reconciling)} settlements reconcile to this credit within "
                        f"tolerance ({', '.join(sid for sid, _, _ in reconciling)}); "
                        "choosing one would be a guess"
                    ),
                )
            )
            continue

        sid, delta, tolerance = reconciling[0]
        sums = arithmetic[sid]
        members = tuple(sorted([credit.event_id, *(e.event_id for e in by_settlement[sid])]))
        matches.append(
            StageMatch(
                stage="fee_adjusted",
                group_key=f"settlement_net:{sid}",
                event_ids=members,
                base_confidence=BASE_CONFIDENCE,
                fields_agreed=("amount_paise",),
                fields_disagreed=(),
                arithmetic=sums.format_arithmetic(
                    observed_net_paise=credit.amount_paise, tolerance_paise=tolerance
                ),
                delta_paise=delta,
                amount_basis_paise=sums.gross_paise,
                candidates_considered=1,
                anchors=(credit.event_id,),
            )
        )

    diagnostics = {f"tolerance_binding_{name}": count for name, count in sorted(bindings.items())}
    diagnostics["settlements_considered"] = len(arithmetic)
    diagnostics["settlements_refused_on_contradicting_reference"] = contradicted
    diagnostics["bank_credits_considered"] = len(credits)
    return StageOutput(matches=tuple(matches), refusals=tuple(refusals), diagnostics=diagnostics)


def _label(event: TransactionEvent) -> str:
    """A human label for a non-payment leg, taken from the row itself.

    ``description`` is free text written by the gateway. It is used for display
    only and never reaches the predicate, so a wording change cannot alter what
    reconciles.
    """
    description = event.raw.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()
    return event.txn_type or "adjustment"
