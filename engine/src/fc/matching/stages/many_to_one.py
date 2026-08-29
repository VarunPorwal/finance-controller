"""Stage 4, many-to-one — PRD §6.3. Base confidence 0.99 grouped, 0.88 by subset.

A T+2 settlement reaches the bank as **one** lumped NEFT credit covering every
order in the batch, net of fees, refunds, TDS and any rolling reserve. Matching
that credit back to the gateway rows behind it is the actual hard problem in
gateway reconciliation, and the stage that solves it is the one most likely to
solve it wrongly.

Two paths, and the order matters.

**Fast path.** If the credit names a settlement - the id survives in the bank
narration even when the UTR is mangled - and that settlement's rows sum to the
credit within tolerance, that is the answer. It is both cheaper and more certain
than any search: a settlement id is *proof that these rows belong together*,
whereas a subset that merely adds up is arithmetic that happens to fit. §6.3
grants auto-close to the grouped path alone, and
:func:`fc.models.match.stage_may_auto_close` enforces the distinction rather than
leaving it to the confidence threshold to imply.

**Slow path.** Otherwise a bounded subset-sum, and the only interesting thing
about it is what it does when it succeeds twice. One valid subset is a match.
*Several* valid subsets is not a match with a tie-break; it is
``ambiguous_multi_candidate``, because picking the first, the largest or the
closest would be guessing while appearing certain - the precise failure this
project exists to avoid (CLAUDE.md hard rule 4).

Bounding the search, and hard rule 9
------------------------------------
§6.3 specifies a 500 ms cap. A wall clock inside a matching decision makes the
output a function of machine speed: the same corpus would yield different
exceptions on a loaded CI box than on a developer laptop, breaking the §12.5
determinism gate intermittently, which is the worst way for a gate to break.

So the binding limit here is :data:`SUBSET_STEP_BUDGET`, a count of DP state
writes. It is a pure function of the input, so the same seed gives the same
answer on every machine. ``cfg.subset_timeout_ms`` is retained as a **backstop
only**: if it ever fires, the step budget was mis-calibrated and this run just
became non-deterministic, so it is logged at warning level naming the credit and
the step count, and counted as ``subset_sum_wall_clock_tripped`` rather than
quietly absorbed. Both limits produce the same outcome - no match, a refusal,
never a guess.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from fc.config import Config
from fc.matching.blocking import DAY_WINDOW
from fc.matching.ledger_refs import extract_refs
from fc.matching.stages import StageMatch, StageOutput, StageRefusal, trusted_bank_reference
from fc.matching.tolerance import tolerance_terms
from fc.models.transaction import TransactionEvent

__all__ = [
    "BASE_CONFIDENCE_GROUPED",
    "BASE_CONFIDENCE_SUBSET",
    "SUBSET_MAX_STATES",
    "SUBSET_STEP_BUDGET",
    "SubsetOutcome",
    "bounded_subset_sum",
    "find_matches",
    "settlement_net_paise",
    "signed_net_paise",
]

logger = logging.getLogger(__name__)

#: §6.3: grouped by settlement_id. The id is the proof, not the arithmetic.
BASE_CONFIDENCE_GROUPED = Decimal("0.99")

#: §6.3: a subset that adds up, with nothing naming it as a group.
BASE_CONFIDENCE_SUBSET = Decimal("0.88")

#: DP state writes permitted per credit. The binding limit - see the module
#: docstring on why this is a step count and not a clock.
SUBSET_STEP_BUDGET = 200_000

#: A second bound on the same search. The number of distinct reachable sums is
#: what actually drives cost, and capping it keeps memory bounded on inputs whose
#: step count would creep rather than blow up.
SUBSET_MAX_STATES = 50_000

_DEBIT = "debit"


def signed_net_paise(event: TransactionEvent) -> int:
    """What one gateway row contributes to the settlement's payout.

    §6.3's pseudocode names an ``r.net_paise`` that ``TransactionEvent`` does not
    have, and the tempting reading - gross minus fee minus tax - is wrong twice
    over. ``fc/ingest/razorpay.py`` already stores the *settlement leg* in
    ``amount_paise``: a payment row carries the recon file's ``credit``, which is
    ``amount - fee``, and a refund or dispute carries its ``debit``. And the fee
    already contains the GST, so ``tax_paise`` is a breakdown of ``fee_paise``,
    not a further deduction.

    Subtracting either again is the exact bug ``seed._check_settlement_arithmetic``
    was written to catch ("this must not subtract fee or tax again - the bug this
    catches is exactly that: a second, hidden deduction sneaking into either
    side"). So the net is the leg as stored, signed by direction; ``fee_paise``
    and ``tax_paise`` are evidence for the pack, not terms in this sum.
    """
    return -event.amount_paise if event.direction == _DEBIT else event.amount_paise


def settlement_net_paise(rows: Sequence[TransactionEvent]) -> int:
    """The payout a whole batch should produce, in integer paise."""
    return sum(signed_net_paise(row) for row in rows)


@dataclass(frozen=True)
class SubsetOutcome:
    """What the bounded search found, and what it cost to find it."""

    #: The single subset that fits, or ``None`` when none or several do.
    subset: tuple[str, ...] | None
    #: Distinct subsets landing inside the tolerance window, saturated at 2. Past
    #: two the exact count is irrelevant: the answer is already "cannot tell".
    answers: int
    steps_used: int
    budget_exhausted: bool = False
    wall_clock_tripped: bool = False

    @property
    def ambiguous(self) -> bool:
        return self.answers > 1


def bounded_subset_sum(
    values: Sequence[tuple[str, int]],
    *,
    target: int,
    tolerance: int,
    step_budget: int = SUBSET_STEP_BUDGET,
    timeout_ms: int | None = None,
) -> SubsetOutcome:
    """Find *the* subset summing into ``[target - tolerance, target + tolerance]``.

    Keyed on reachable **sums**, not on subsets. That is what makes the
    pathological case cheap: with 200 identical amounts the reachable set is
    ``{0, v, 2v, ...}`` bounded above by the target, so its size depends on the
    target and not on how many rows produced it. The combinatorial explosion
    lives in the *count* of subsets reaching each sum, and that saturates at two
    and is never enumerated.

    Every loop runs over a sorted key list and every witness is chosen by ``min``,
    so the answer never depends on dict ordering (hard rule 9).
    """
    low, high = target - tolerance, target + tolerance
    n = len(values)

    # What the untouched tail can still add or subtract, for exact pruning.
    suffix_positive = [0] * (n + 1)
    suffix_negative = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        value = values[i][1]
        suffix_positive[i] = suffix_positive[i + 1] + (value if value > 0 else 0)
        suffix_negative[i] = suffix_negative[i + 1] + (value if value < 0 else 0)

    #: reachable sum -> (subsets reaching it, saturated at 2; lowest witness)
    state: dict[int, tuple[int, tuple[int, ...]]] = {0: (1, ())}
    steps = 0
    started = time.monotonic() if timeout_ms is not None else None

    for i, (_event_id, value) in enumerate(values):
        additions: dict[int, tuple[int, tuple[int, ...]]] = {}
        for reached in sorted(state):
            count, witness = state[reached]
            moved = reached + value
            # Unreachable from here whatever the remaining rows do.
            if moved + suffix_positive[i + 1] < low:
                continue
            if moved + suffix_negative[i + 1] > high:
                continue

            steps += 1
            if steps > step_budget or len(state) + len(additions) > SUBSET_MAX_STATES:
                return SubsetOutcome(None, 0, steps, budget_exhausted=True)
            if (
                started is not None
                and timeout_ms is not None
                and (time.monotonic() - started) * 1000 > timeout_ms
            ):
                return SubsetOutcome(None, 0, steps, budget_exhausted=True, wall_clock_tripped=True)

            candidate = (*witness, i)
            seen_count, seen_witness = additions.get(moved, (0, candidate))
            additions[moved] = (min(2, seen_count + count), min(seen_witness, candidate))

        for moved in sorted(additions):
            count, witness = additions[moved]
            seen_count, seen_witness = state.get(moved, (0, witness))
            state[moved] = (min(2, seen_count + count), min(seen_witness, witness))

    answers = 0
    best: tuple[int, ...] | None = None
    for reached in sorted(state):
        if not low <= reached <= high:
            continue
        count, witness = state[reached]
        if not witness:
            # The empty subset sums to zero without asserting anything.
            continue
        answers = min(2, answers + count)
        if best is None:
            best = witness

    if answers != 1 or best is None:
        return SubsetOutcome(None, answers, steps)
    return SubsetOutcome(tuple(values[i][0] for i in best), 1, steps)


def find_matches(
    events: Sequence[TransactionEvent], *, unmatched: frozenset[str], cfg: Config
) -> StageOutput:
    """Decompose each unmatched bank credit into the gateway rows behind it.

    Takes *all* events with the unmatched set alongside, exactly as stage 2 does:
    a batch's payout must be summed over every row in it, including rows an
    earlier stage already claimed, while only the bank credit is newly decided.
    The cascade then extends the existing group rather than building a rival.
    """
    by_settlement: dict[str, list[TransactionEvent]] = {}
    for event in events:
        if event.source == "razorpay" and event.settlement_id:
            by_settlement.setdefault(event.settlement_id, []).append(event)
    for rows in by_settlement.values():
        rows.sort(key=lambda e: e.event_id)

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
    counters: dict[str, int] = {
        "settlement_claims_from_narration": 0,
        "grouped_by_settlement_id": 0,
        "subset_sum_invocations": 0,
        "subset_sum_matched": 0,
        "subset_sum_ambiguous": 0,
        "subset_sum_over_max_n": 0,
        "subset_sum_budget_exhausted": 0,
        "subset_sum_wall_clock_tripped": 0,
        "subset_sum_max_steps_used": 0,
    }

    for credit in credits:
        grouped = _grouped_match(credit, by_settlement, cfg=cfg, counters=counters)
        if grouped is not None:
            matches.append(grouped)
            continue

        candidates = _subset_candidates(credit, events, unmatched=unmatched)
        if not candidates:
            continue
        if len(candidates) > cfg.max_subset_n:
            # §6.3: fall through to fuzzy rather than search. Not a refusal - the
            # next stage still gets a look at it.
            counters["subset_sum_over_max_n"] += 1
            continue

        counters["subset_sum_invocations"] += 1
        terms = tolerance_terms(credit.amount_paise, len(candidates), cfg)
        outcome = bounded_subset_sum(
            [(e.event_id, signed_net_paise(e)) for e in candidates],
            target=credit.amount_paise,
            tolerance=terms.value,
            step_budget=SUBSET_STEP_BUDGET,
            timeout_ms=cfg.subset_timeout_ms,
        )
        counters["subset_sum_max_steps_used"] = max(
            counters["subset_sum_max_steps_used"], outcome.steps_used
        )

        if outcome.wall_clock_tripped:
            counters["subset_sum_wall_clock_tripped"] += 1
            logger.warning(
                "subset-sum hit the wall-clock backstop on credit %s after %d steps "
                "(budget %d): the step budget is mis-calibrated and this run is no "
                "longer deterministic",
                credit.event_id,
                outcome.steps_used,
                SUBSET_STEP_BUDGET,
            )
        if outcome.budget_exhausted:
            counters["subset_sum_budget_exhausted"] += 1
            refusals.append(
                StageRefusal(
                    category="ambiguous_multi_candidate",
                    event_ids=(credit.event_id,),
                    amount_paise=credit.amount_paise,
                    reason=(
                        f"subset-sum over {len(candidates)} candidates exhausted its "
                        f"{SUBSET_STEP_BUDGET}-step budget without reaching an answer"
                    ),
                )
            )
            continue

        if outcome.ambiguous:
            counters["subset_sum_ambiguous"] += 1
            refusals.append(
                StageRefusal(
                    category="ambiguous_multi_candidate",
                    event_ids=(credit.event_id,),
                    amount_paise=credit.amount_paise,
                    reason=(
                        f"more than one subset of {len(candidates)} candidate rows sums "
                        f"to this credit within {terms.value} paise; which one it is "
                        "cannot be told from the data"
                    ),
                )
            )
            continue

        if outcome.subset is None:
            continue

        found = set(outcome.subset)
        chosen = [e for e in candidates if e.event_id in found]
        # Re-check against the tolerance the *found* subset earns, not the loose
        # band the search ran under: the drift term scales with the batch size,
        # so searching at the widest band and verifying at the earned one is
        # conservative in the right direction.
        recheck = tolerance_terms(credit.amount_paise, len(chosen), cfg)
        net = settlement_net_paise(chosen)
        delta = credit.amount_paise - net
        if abs(delta) > recheck.value:
            continue

        counters["subset_sum_matched"] += 1
        matches.append(
            StageMatch(
                stage="many_to_one",
                group_key=f"subset:{credit.event_id}",
                event_ids=tuple(sorted([credit.event_id, *outcome.subset])),
                base_confidence=BASE_CONFIDENCE_SUBSET,
                fields_agreed=("amount_paise",),
                fields_disagreed=(),
                arithmetic=(
                    f"{len(chosen)} of {len(candidates)} candidate rows net to {net} "
                    f"paise against a credit of {credit.amount_paise} paise "
                    f"(delta {delta}, tolerance {recheck.value}); no other subset fits"
                ),
                delta_paise=delta,
                amount_basis_paise=credit.amount_paise,
                candidates_considered=1,
                # Nothing named these rows as a batch; they were found by search.
                # §6.3 withholds auto-close from exactly this case.
                grouped_by=None,
                anchors=(credit.event_id,),
            )
        )

    return StageOutput(matches=tuple(matches), refusals=tuple(refusals), diagnostics=counters)


def _grouped_match(
    credit: TransactionEvent,
    by_settlement: Mapping[str, list[TransactionEvent]],
    *,
    cfg: Config,
    counters: dict[str, int],
) -> StageMatch | None:
    """The §6.3 fast path: the credit names a settlement, and the sums agree.

    The id is read from the narration through
    :meth:`fc.matching.ledger_refs.LedgerRefs.identity_claims`, so a narration
    citing two settlements identifies itself with neither. Extraction is not
    attribution - the same rule that keeps stage 1 at 100% precision.
    """
    claims = extract_refs(credit.raw_narration).identity_claims().settlement_ids
    if len(claims) != 1:
        return None
    rows = by_settlement.get(claims[0])
    if not rows:
        return None

    settlement_id = claims[0]
    counters["settlement_claims_from_narration"] += 1
    expected = settlement_net_paise(rows)
    gross = sum(abs(row.amount_paise) for row in rows)
    terms = tolerance_terms(gross, len(rows), cfg)
    delta = credit.amount_paise - expected
    if abs(delta) > terms.value:
        return None

    # A credit whose own reference contradicts every UTR in the batch still
    # groups here - the settlement id says these rows belong together - but the
    # disagreement is recorded, and §6.6's field-agreement factor takes the
    # confidence down accordingly. That is the transposed-UTR case: matched,
    # evidenced, and deliberately not closed on its own.
    reference = trusted_bank_reference(credit)
    batch_utrs = {row.utr for row in rows if row.utr}
    contradicted = reference is not None and bool(batch_utrs) and reference not in batch_utrs

    counters["grouped_by_settlement_id"] += 1
    return StageMatch(
        stage="many_to_one",
        group_key=f"settlement_batch:{settlement_id}",
        event_ids=tuple(sorted([credit.event_id, *(row.event_id for row in rows)])),
        base_confidence=BASE_CONFIDENCE_GROUPED,
        fields_agreed=("settlement_id", "amount_paise"),
        fields_disagreed=("utr",) if contradicted else (),
        arithmetic=(
            f"{len(rows)} rows of {settlement_id} net to {expected} paise against a "
            f"credit of {credit.amount_paise} paise (delta {delta}, tolerance "
            f"{terms.value} bound by the {terms.binding} term)"
        ),
        delta_paise=delta,
        amount_basis_paise=gross,
        candidates_considered=1,
        grouped_by="settlement_id",
        anchors=(credit.event_id,),
    )


def _subset_candidates(
    credit: TransactionEvent, events: Sequence[TransactionEvent], *, unmatched: frozenset[str]
) -> list[TransactionEvent]:
    """Unclaimed gateway rows near the credit in time.

    Blocking is no help here and is deliberately not used: its key is
    ``(amount bucket, day)``, and a lumped credit sits dozens of amount buckets
    away from any single order composing it. The date window is reused from
    ``blocking`` so the two agree on what "near" means.
    """
    day = credit.effective_date.toordinal()
    return sorted(
        (
            event
            for event in events
            if event.source == "razorpay"
            and event.event_id in unmatched
            and abs(event.effective_date.toordinal() - day) <= DAY_WINDOW
        ),
        key=lambda e: (e.effective_date, e.event_id),
    )
