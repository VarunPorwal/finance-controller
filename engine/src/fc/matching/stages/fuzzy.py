"""Stage 5, fuzzy — PRD §6.3. Weighted feature score, hard-capped at 0.75.

The last stage, and the dangerous one. Everything above it matched on something
it could *prove*: an identical reference, a settlement's arithmetic, a unique
completion. This one matches on resemblance, and resemblance is how a
reconciliation engine manufactures confident nonsense.

So stage 5 never closes anything. A fuzzy match is a *ranked suggestion for a
human*, which is why §6.3 caps it at 0.75 and excludes it from
``AUTO_CLOSABLE_STAGES``. The cap is enforced twice over and in neither place by
convention: :func:`fc.matching.confidence.derive` applies it before the number is
stored, and :class:`fc.models.match.MatchResult` refuses to validate a fuzzy
match above it or an auto-closed group holding a fuzzy leg.

Renormalising the §6.3 weights
------------------------------
§6.3 gives five weighted features summing to 1.00. Two of them cannot be
computed for every pair, and not because the data is dirty - because of the
shape of the sources:

* ``counterparty_similarity`` needs ``counterparty_norm``, which ``fc/ingest/``
  populates for bank and ledger rows. Razorpay's recon export carries no
  counterparty at all, so the feature is undefined for **every** gateway↔bank
  pair - the commonest pair in the corpus.
* ``method_agreement`` compares a gateway ``method`` with a bank ``rail``. Only
  razorpay rows carry ``method`` and only bank rows carry ``rail``, so it is
  undefined for bank↔ledger.

Scoring an undefined feature as zero would penalise a pair for a schema fact
rather than an evidence fact, and would cap every gateway↔bank pair at 0.85 of
the available weight before any evidence was read. So the score is renormalised
over the weights that were actually defined, and :meth:`FuzzyScore.explain` names
which those were, so the evidence pack shows a renormalised number and says so.
A pair with too little defined evidence is not scored low - it is not scored, and
that is an abstention rather than a weak match.

Ties abstain
------------
Two candidates within :data:`TIE_MARGIN` of each other produce no match and an
``ambiguous_multi_candidate`` refusal. Exact-tie-only would be a rounding
artefact away from being wrong: 0.7001 against 0.7000 is two valid answers, not
one clear winner.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from fc.config import Config
from fc.matching.blocking import BlockIndex, candidate_pairs, reference_values
from fc.matching.ledger_refs import LedgerRefIndex
from fc.matching.stages import StageMatch, StageOutput, StageRefusal, reference_is_truncated
from fc.models.transaction import TransactionEvent

__all__ = [
    "DATE_HORIZON_DAYS",
    "IDENTIFYING_FEATURES",
    "MIN_DEFINED_WEIGHT",
    "MIN_SCORE",
    "TIE_MARGIN",
    "WEIGHTS",
    "FeatureScore",
    "FuzzyScore",
    "find_matches",
    "jaro_winkler",
    "score_pair",
]

#: §6.3 verbatim. Decimal, never float: this module is inside the AST scan that
#: forbids float in the money path, and a weighted score that drifts by 1e-17
#: would make "same seed, byte-identical output" false in the fourth decimal.
WEIGHTS: Mapping[str, Decimal] = {
    "amount_proximity": Decimal("0.35"),
    "date_proximity": Decimal("0.20"),
    "reference_similarity": Decimal("0.25"),
    "counterparty_similarity": Decimal("0.15"),
    "method_agreement": Decimal("0.05"),
}

#: §6.3: ``1 - days/7``, so seven days is where date proximity reaches zero.
DATE_HORIZON_DAYS = 7

#: Below this much defined weight there is not enough to score on at all.
MIN_DEFINED_WEIGHT = Decimal("0.55")

#: At least one of these must be defined, whatever the weights add up to.
#:
#: Amount and date say two rows are *the same size on the same day*. That is what
#: blocking already selected for, so a pair with nothing else defined scores a
#: perfect 1.0 on a coincidence - and scenario 16 ("same amount, same day, two
#: different orders") is that coincidence occurring on purpose. Only a reference
#: or a counterparty can say two rows are *the same money*, so one of them has to
#: be present before a score means anything.
IDENTIFYING_FEATURES = frozenset({"reference_similarity", "counterparty_similarity"})

#: A suggestion worth a human's attention. Not tuned against the corpus - stage 5
#: has almost nothing to score there, so any corpus-fitted value would be
#: measuring noise (CLAUDE.md: don't tune constants to improve headline numbers).
MIN_SCORE = Decimal("0.60")

#: Two candidates this close are two valid answers.
TIE_MARGIN = Decimal("0.05")

_QUANTUM = Decimal("0.0001")
_ONE = Decimal(1)
_ZERO = Decimal(0)

#: Gateway ``method`` to the bank ``rail`` a settlement of it may arrive on.
#: Card, netbanking, wallet and EMI never reach the merchant on their own rail -
#: they are aggregated into a batch credit over NEFT/RTGS. ``nach`` and
#: ``internal`` appear in no set: a NACH batch line is never a gateway
#: settlement, which is why scenario 8 is unresolvable by design.
_RAIL_COMPATIBILITY: Mapping[str, frozenset[str]] = {
    "upi": frozenset({"upi", "imps"}),
    "card": frozenset({"neft", "rtgs"}),
    "netbanking": frozenset({"neft", "rtgs"}),
    "wallet": frozenset({"neft", "rtgs"}),
    "emi": frozenset({"neft", "rtgs"}),
}


def jaro_winkler(left: str, right: str) -> Decimal:
    """Jaro-Winkler similarity in ``[0, 1]``, as ``Decimal``.

    Hand-written because the stack is fixed and free-tier only, and adding
    ``rapidfuzz`` or ``jellyfish`` for one function would need asking first
    (CLAUDE.md). References are at most 26 characters, so the quadratic match
    scan costs nothing.
    """
    if left == right:
        return _ONE if left else _ZERO
    if not left or not right:
        return _ZERO

    a, b = left.upper(), right.upper()
    window = max(max(len(a), len(b)) // 2 - 1, 0)

    a_matched = [False] * len(a)
    b_matched = [False] * len(b)
    matches = 0
    for i, char in enumerate(a):
        for j in range(max(0, i - window), min(len(b), i + window + 1)):
            if b_matched[j] or b[j] != char:
                continue
            a_matched[i] = b_matched[j] = True
            matches += 1
            break
    if matches == 0:
        return _ZERO

    transpositions = 0
    j = 0
    for i, flag in enumerate(a_matched):
        if not flag:
            continue
        while not b_matched[j]:
            j += 1
        if a[i] != b[j]:
            transpositions += 1
        j += 1

    m = Decimal(matches)
    jaro = (
        m / Decimal(len(a)) + m / Decimal(len(b)) + (m - Decimal(transpositions // 2)) / m
    ) / Decimal(3)

    prefix = 0
    for x, y in zip(a[:4], b[:4], strict=False):
        if x != y:
            break
        prefix += 1
    return _quantize(jaro + Decimal(prefix) * Decimal("0.1") * (_ONE - jaro))


@dataclass(frozen=True)
class FeatureScore:
    """One §6.3 feature. ``value is None`` means undefined for this pair."""

    name: str
    value: Decimal | None
    weight: Decimal


@dataclass(frozen=True)
class FuzzyScore:
    """The weighted score, and the working behind it."""

    features: tuple[FeatureScore, ...]
    defined_weight: Decimal
    score: Decimal

    def explain(self) -> str:
        parts = [f"{f.name} {f.value} x {f.weight}" for f in self.features if f.value is not None]
        undefined = [f.name for f in self.features if f.value is None]
        text = " + ".join(parts) + f" = {self.score}"
        if undefined:
            text += f" (renormalised over {self.defined_weight} of weight; "
            text += f"undefined here: {', '.join(undefined)})"
        return text


def references_for(
    event: TransactionEvent, ledger_refs: LedgerRefIndex | None = None
) -> tuple[str, ...]:
    """Every reference the row carries, including ones only its narration holds.

    Tally exports put no gateway identifier in a field, so a ledger row's
    ``reference_values`` are empty and a similarity computed from them would
    always be undefined - leaving bank↔ledger pairs scored on amount and date
    alone, which is the weakest possible basis for a match and exactly what
    blocking already selected for. ``ledger_refs`` supplies what the narration
    yielded, so the strongest feature available is actually used.
    """
    found = reference_values(event)
    if found or ledger_refs is None or event.source != "ledger":
        return found
    claims = ledger_refs.for_event(event.event_id)
    return (
        *claims.order_ids,
        *claims.settlement_ids,
        *claims.payment_ids,
        *claims.refund_ids,
    )


def score_pair(
    left: TransactionEvent,
    right: TransactionEvent,
    *,
    ledger_refs: LedgerRefIndex | None = None,
) -> FuzzyScore | None:
    """Score one candidate pair, or ``None`` when too little is defined."""
    features = (
        FeatureScore(
            "amount_proximity", _amount_proximity(left, right), WEIGHTS["amount_proximity"]
        ),
        FeatureScore("date_proximity", _date_proximity(left, right), WEIGHTS["date_proximity"]),
        FeatureScore(
            "reference_similarity",
            _reference_similarity(left, right, ledger_refs),
            WEIGHTS["reference_similarity"],
        ),
        FeatureScore(
            "counterparty_similarity",
            _counterparty_similarity(left, right),
            WEIGHTS["counterparty_similarity"],
        ),
        FeatureScore(
            "method_agreement", _method_agreement(left, right), WEIGHTS["method_agreement"]
        ),
    )

    defined = sum((f.weight for f in features if f.value is not None), _ZERO)
    if defined < MIN_DEFINED_WEIGHT:
        return None
    if not any(f.name in IDENTIFYING_FEATURES and f.value is not None for f in features):
        return None

    weighted = sum((f.weight * f.value for f in features if f.value is not None), _ZERO)
    return FuzzyScore(
        features=features,
        defined_weight=defined,
        score=_quantize(weighted / defined),
    )


def find_matches(
    events: Sequence[TransactionEvent],
    *,
    index: BlockIndex,
    ledger_refs: LedgerRefIndex,
    cfg: Config,
) -> StageOutput:
    """Score the residual, match the clear winners, refuse the ties.

    Candidates come from blocking rather than from a fresh scan. That is a
    precision decision, not a speed one: without it stage 5 would happily compare
    a direct NEFT credit to an unrelated ledger row four times its size and, with
    only two features defined, could clear the threshold on date proximity alone.
    Restricting the candidate set structurally is worth more than any threshold
    tuned after the fact.
    """
    del cfg
    by_id: Mapping[str, TransactionEvent] = {e.event_id: e for e in events}

    #: anchor -> [(score, other id)], best first
    ranked: dict[str, list[tuple[Decimal, str]]] = {}
    considered = 0
    unscorable = 0
    for left_id, right_id in candidate_pairs(index, by_id):
        considered += 1
        scored = score_pair(by_id[left_id], by_id[right_id], ledger_refs=ledger_refs)
        if scored is None:
            unscorable += 1
            continue
        if scored.score < MIN_SCORE:
            continue
        ranked.setdefault(left_id, []).append((scored.score, right_id))
        ranked.setdefault(right_id, []).append((scored.score, left_id))

    matches: list[StageMatch] = []
    refusals: list[StageRefusal] = []
    claimed: set[str] = set()
    ties = 0

    for anchor in sorted(ranked):
        if anchor in claimed:
            continue
        # Sorted by descending score, then by id so equal scores order stably.
        options = sorted(ranked[anchor], key=lambda pair: (-pair[0], pair[1]))
        options = [(score, other) for score, other in options if other not in claimed]
        if not options:
            continue

        best_score, best_other = options[0]
        if len(options) > 1 and best_score - options[1][0] < TIE_MARGIN:
            ties += 1
            refusals.append(
                StageRefusal(
                    category="ambiguous_multi_candidate",
                    event_ids=(anchor,),
                    amount_paise=by_id[anchor].amount_paise,
                    reason=(
                        f"{len(options)} candidates score within {TIE_MARGIN} of each "
                        f"other (best {best_score}, next {options[1][0]}); resemblance "
                        "this close identifies none of them"
                    ),
                )
            )
            continue

        left, right = by_id[anchor], by_id[best_other]
        scored = score_pair(left, right, ledger_refs=ledger_refs)
        if scored is None:
            continue

        delta = left.amount_paise - right.amount_paise
        basis = max(abs(left.amount_paise), abs(right.amount_paise))
        days = abs(left.effective_date.toordinal() - right.effective_date.toordinal())
        truncated = reference_is_truncated(left) or reference_is_truncated(right)

        matches.append(
            StageMatch(
                stage="fuzzy",
                group_key=f"fuzzy:{min(anchor, best_other)}",
                event_ids=tuple(sorted((anchor, best_other))),
                base_confidence=scored.score,
                fields_agreed=tuple(
                    f.name for f in scored.features if f.value is not None and f.value > _ZERO
                ),
                # A truncated reference is usable *here* and nowhere earlier
                # (§12.2 scenario 6), but it is recorded as a disagreement so the
                # §6.6 agreement factor shows why the number came out low.
                fields_disagreed=("reference_truncated",) if truncated else (),
                arithmetic=scored.explain(),
                delta_paise=delta,
                amount_basis_paise=basis,
                date_shift_days=days,
                candidates_considered=len(options),
                grouped_by=None,
            )
        )
        claimed.update((anchor, best_other))

    return StageOutput(
        matches=tuple(matches),
        refusals=tuple(refusals),
        diagnostics={
            "pairs_considered": considered,
            "pairs_below_min_defined_weight": unscorable,
            "pairs_above_min_score": len(ranked),
            "ties_refused": ties,
            "matched": len(matches),
        },
    )


def _amount_proximity(left: TransactionEvent, right: TransactionEvent) -> Decimal | None:
    basis = max(abs(left.amount_paise), abs(right.amount_paise))
    if basis == 0:
        return None
    delta = abs(abs(left.amount_paise) - abs(right.amount_paise))
    return _clamp(_ONE - Decimal(delta) / Decimal(basis))


def _date_proximity(left: TransactionEvent, right: TransactionEvent) -> Decimal | None:
    days = abs(left.effective_date.toordinal() - right.effective_date.toordinal())
    return _clamp(_ONE - Decimal(days) / Decimal(DATE_HORIZON_DAYS))


def _reference_similarity(
    left: TransactionEvent, right: TransactionEvent, ledger_refs: LedgerRefIndex | None = None
) -> Decimal | None:
    """Best Jaro-Winkler over every reference either side carries.

    Uses the raw references, not :func:`trusted_bank_reference`. §6.3 says a
    truncated reference is "excluded from stage 1 and downgraded to
    partial-similarity in stage 5" - downgrading it is this stage's whole job, so
    withholding it here would leave scenario 6 with nothing to match on at all.
    """
    theirs = references_for(right, ledger_refs)
    if not theirs:
        return None
    mine = references_for(left, ledger_refs)
    if not mine:
        return None
    return max(jaro_winkler(a, b) for a in mine for b in theirs)


def _counterparty_similarity(left: TransactionEvent, right: TransactionEvent) -> Decimal | None:
    """Similarity after ingest's alias normalisation.

    Reads ``counterparty_norm``, which ``fc/ingest/aliases.py`` already resolved,
    rather than importing the alias table - that would drag a YAML read into the
    matching package for a value the event already carries.
    """
    if not left.counterparty_norm or not right.counterparty_norm:
        return None
    return jaro_winkler(left.counterparty_norm, right.counterparty_norm)


def _method_agreement(left: TransactionEvent, right: TransactionEvent) -> Decimal | None:
    """1.0 when the gateway method could settle over the bank rail seen."""
    for gateway, bank in ((left, right), (right, left)):
        if gateway.method and bank.rail:
            compatible = _RAIL_COMPATIBILITY.get(gateway.method, frozenset())
            return _ONE if bank.rail in compatible else _ZERO
    return None


def _clamp(value: Decimal) -> Decimal:
    return max(_ZERO, min(_ONE, value))


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_QUANTUM, rounding=ROUND_HALF_UP)
