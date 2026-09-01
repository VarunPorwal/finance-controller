"""Stage 1, exact reference — PRD §6.3. Base confidence 1.00.

``utr == utr``, ``rrn == rrn``, ``settlement_id == settlement_id`` or
``order_id == order_id``, **and not truncated**.

Two things about this stage are deliberate and easy to undo by accident.

*It does not go through blocking.* Blocking keys on amount and date; a bank
batch credit and the gateway rows composing it sit in different amount buckets
by construction. Running stage 1 through blocking would hide exactly the groups
it exists to find. It is a hash join over reference values, which is cheaper
than blocking anyway.

*A truncated reference never enters.* ``TransactionEvent`` carries no
``truncated`` field - ``fc/ingest/bank_csv.py`` computes it and drops it - so
the flag is re-derived here from ``raw_narration`` and ``rail`` using ingest's
own :func:`~fc.ingest.narration.base.is_truncated`. A truncated UTR that
happens to prefix-match another is a false positive waiting to happen, and
stage 1 is the one stage whose precision must be 100%.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from fc.config import Config
from fc.matching.ledger_refs import LedgerRefIndex
from fc.matching.stages import StageMatch, StageOutput, reference_is_truncated
from fc.matching.tolerance import tolerance_paise
from fc.models.transaction import TransactionEvent

__all__ = [
    "BASE_CONFIDENCE",
    "JOIN_FIELDS",
    "ReferenceFact",
    "find_matches",
    "order_side",
    "reference_is_truncated",
    "trusted_references",
]

BASE_CONFIDENCE = Decimal("1.00")

#: §6.3 names these four and only these four.
JOIN_FIELDS = ("utr", "rrn", "settlement_id", "order_id")

#: References that identify a *commercial order* rather than a money movement.
#:
#: One order can carry a payment, a partial refund and a chargeback. Those are
#: three separate flows of money that happen to quote the same order id, and in
#: the corpus a refund routinely settles in a different batch from its origin
#: payment (scenario 4, ``refund_lag``) - ground truth gives them different
#: match groups, correctly. Joining on the order id alone therefore asserts that
#: a payment and its refund are the same money, which is the exact conflation
#: the ``partial_refund`` and ``chargeback_unrecorded`` categories exist to keep
#: apart. A UTR or a settlement id needs no such qualification: each names one
#: movement by construction.
_ORDER_SCOPED_FIELDS = frozenset({"order_id"})

#: Which side of an order a row sits on. Gateway rows say so directly; a Tally
#: credit/debit note is the ledger's way of saying the same thing.
_REFUND_TXN_TYPES = frozenset({"refund", "dispute"})
_REFUND_VOUCHER_TYPES = frozenset({"Credit Note", "Debit Note"})


@dataclass(frozen=True)
class ReferenceFact:
    """One usable reference on one event, with the join key it produces."""

    field: str
    value: str
    #: Empty for references that name a money movement; "payment"/"refund" for
    #: order-scoped ones, which must not join across the two sides.
    side: str = ""

    @property
    def join_key(self) -> tuple[str, str, str]:
        return (self.field, self.value, self.side)


def order_side(event: TransactionEvent) -> str:
    """Which side of an order this row sits on - see ``_ORDER_SCOPED_FIELDS``."""
    if event.txn_type in _REFUND_TXN_TYPES:
        return "refund"
    if event.voucher_type in _REFUND_VOUCHER_TYPES:
        return "refund"
    return "payment"


def _fact(name: str, value: str, event: TransactionEvent) -> ReferenceFact:
    side = order_side(event) if name in _ORDER_SCOPED_FIELDS else ""
    return ReferenceFact(field=name, value=value, side=side)


def trusted_references(
    event: TransactionEvent, ledger_refs: LedgerRefIndex
) -> tuple[ReferenceFact, ...]:
    """The join-eligible references on one event, truncated ones removed."""
    if reference_is_truncated(event):
        return ()

    facts: list[ReferenceFact] = []
    for name in JOIN_FIELDS:
        value = getattr(event, name)
        if isinstance(value, str) and value:
            facts.append(_fact(name, value, event))

    if event.source == "ledger":
        found = ledger_refs.identity_for_event(event.event_id)
        facts.extend(_fact("settlement_id", v, event) for v in found.settlement_ids)
        facts.extend(_fact("order_id", v, event) for v in found.order_ids)

    return tuple(facts)


#: A group is only trusted on reference agreement alone when there is
#: nothing to check it against — a bank leg present means there is an
#: independent number (what actually hit the account) to compare the
#: gateway/ledger side's own net against. §6.5's tolerance model applies the
#: same way it does everywhere else; ``n_txns`` is the non-bank leg's own
#: row count, since that side is what the tolerance's rounding-drift term is
#: about.
def _net_paise(members: Sequence[TransactionEvent]) -> int:
    """Signed net using "money moving toward the account" as positive.

    The per-row convention, and why a ledger row is not simply inverted, lives
    on :attr:`TransactionEvent.bank_signed_paise`.
    """
    return sum(e.bank_signed_paise for e in members)


def _bank_side_balances(
    unique: Sequence[str], by_id: dict[str, TransactionEvent], cfg: Config
) -> bool:
    """Whether the bank leg agrees with the side that claims to *be* the money.

    Each source states the same movement independently; they do not add. So
    the check is bank-against-one-other-side, and which side is the right
    comparand is not a matter of taste: the gateway is the processor's own
    record of what it paid out, so where a gateway leg is present it is what
    the bank credit must agree with. The ledger is the merchant's *claim*
    about the same movement, and a claim that disagrees is the finding
    (:mod:`fc.matching.three_way`), not a reason to withhold the group — the
    duplicate-voucher case D7 exists for is precisely a group where bank and
    gateway agree perfectly and the books do not.

    This used to return ``True`` unconditionally as soon as the non-bank side
    spanned two sources, deferring to three-way resolution — which then had no
    balance check of its own for a group that arrived already three-way. The
    two gaps lined up exactly: a settlement whose bank credit was ₹18,475
    short of its gateway net, with a ledger receipt for the full amount,
    formed at confidence 1.00 with ``residual_paise`` 0 and auto-closed. A
    short payout is the one thing that must never close.
    """
    bank = [by_id[e] for e in unique if by_id[e].source == "bank"]
    if not bank:
        return True
    gateway = [by_id[e] for e in unique if by_id[e].source == "razorpay"]
    ledger = [by_id[e] for e in unique if by_id[e].source == "ledger"]
    comparand = gateway or ledger
    if not comparand:
        return True
    delta = _net_paise(bank) - _net_paise(comparand)
    tol = tolerance_paise(abs(_net_paise(comparand)), len(comparand), cfg)
    return abs(delta) <= tol


def find_matches(
    events: Sequence[TransactionEvent], *, ledger_refs: LedgerRefIndex, cfg: Config
) -> StageOutput:
    """Group events by transitive agreement on trusted reference values.

    Reference agreement is transitive, and the group is the unit of truth. One
    settlement is a bank credit, the gateway rows composing it and the ledger
    vouchers booking it; those are linked by different references - the credit
    to the batch by UTR, each payment to its sales voucher by order id, the
    receipt to the batch by settlement id - and no single key sees all of them.
    Emitting one group per key would answer "which rows share this reference"
    when the question is "which rows are this money".

    So edges are unioned into components. A component spanning two or more
    sources is one match, carrying one evidence entry per reference field that
    helped form it. Single-source components are not matches: two gateway rows
    sharing a settlement id are the same batch, not money crossing a boundary.

    A component that includes a bank leg is additionally required to
    *balance*: the bank side's net must agree with the other side's net
    within §6.5 tolerance. A reference hit proves these rows are talking
    about the same batch, not that every row of that batch is present — a
    bank credit consolidating two settlements but quoting only one UTR
    exact-matches that one settlement and nothing stops it from closing on
    a partial batch. Refusing to close it here (not raising it as a
    refusal — just declining to emit the match) returns every member to the
    unmatched pool so a grouping or subset-sum stage downstream can find the
    composition that actually accounts for the credit.
    """
    parent: dict[str, str] = {}
    fields_by_root: dict[str, set[str]] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    by_key: dict[tuple[str, str, str], list[str]] = {}
    for event in events:
        parent.setdefault(event.event_id, event.event_id)
        for fact in trusted_references(event, ledger_refs):
            by_key.setdefault(fact.join_key, []).append(event.event_id)

    edges: list[tuple[str, tuple[str, ...]]] = []
    for (name, _value, _side), members in sorted(by_key.items()):
        unique = tuple(sorted(set(members)))
        if len(unique) < 2:
            continue
        edges.append((name, unique))
        for other in unique[1:]:
            union(unique[0], other)

    for name, joined in edges:
        fields_by_root.setdefault(find(joined[0]), set()).add(name)

    components: dict[str, list[str]] = {}
    for event in events:
        components.setdefault(find(event.event_id), []).append(event.event_id)

    source_of = {event.event_id: event.source for event in events}
    by_id = {event.event_id: event for event in events}
    matches: list[StageMatch] = []
    for root, members in sorted(components.items()):
        unique = tuple(sorted(members))
        if len(unique) < 2 or len({source_of[e] for e in unique}) < 2:
            continue
        if not _bank_side_balances(unique, by_id, cfg):
            continue
        agreed = tuple(sorted(fields_by_root.get(root, set())))
        matches.append(
            StageMatch(
                stage="exact_ref",
                group_key=f"exact_ref:{root}",
                event_ids=unique,
                base_confidence=BASE_CONFIDENCE,
                fields_agreed=agreed,
                fields_disagreed=_disagreements(agreed, unique, events),
                arithmetic=(
                    f"{len(unique)} events linked by exact agreement on "
                    + ", ".join(agreed)
                    + "; no reference truncated, no competing candidate"
                ),
                # One, not the group size. §6.6's ambiguity_penalty divides by
                # the number of *competing* candidate matches the stage weighed
                # and discarded. An exact reference join admits no alternative:
                # the events either carry the same identifier or they do not.
                # Passing the group size here reads a 20-row settlement as
                # twenty rival answers and drives a proven match to 0.05.
                candidates_considered=1,
            )
        )

    withheld = sum(1 for e in events if reference_is_truncated(e))
    return StageOutput(
        matches=tuple(matches),
        diagnostics={"references_withheld_as_truncated": withheld},
    )


def _disagreements(
    joined_on: tuple[str, ...], event_ids: tuple[str, ...], events: Sequence[TransactionEvent]
) -> tuple[str, ...]:
    """Ladder fields that every member populates but on which they differ.

    A field only counts as disagreeing when all members have an opinion; a
    field absent from one source is missing evidence, not conflicting evidence.
    """
    members = [e for e in events if e.event_id in set(event_ids)]
    disagreed: list[str] = []
    for name in JOIN_FIELDS:
        if name in joined_on:
            continue
        values = [getattr(e, name) for e in members]
        if all(isinstance(v, str) and v for v in values) and len(set(values)) > 1:
            disagreed.append(name)
    return tuple(disagreed)
