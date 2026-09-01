"""The reconciliation bridge — PRD §6.8.7 / §13.4.

::

    GROSS COLLECTED                        (gateway lane, held payments excluded)
      - MDR - GST on MDR - TDS 194-O - Refunds settled - Chargebacks
      - Rolling reserve
      = EXPECTED NET
           vs BANK CREDITED
           ─────────────────
           UNEXPLAINED

"The artifact a finance person draws by hand on paper" (§13.4), so every
figure here is read straight off the Razorpay recon report and the bank
statement — no rule engine, no LLM (CLAUDE.md hard rule 2, and this package
is one of ``test_architecture.py``'s four scanned decision modules), and every
amount is int paise, never float (hard rule 1, and this package is one of the
three money-arithmetic trees the AST scan covers).

**The bridge is one lane's story.** "Gross minus MDR minus GST equals what the
bank credited" is arithmetic about payment-gateway money. A marketplace payout
nets its commission at source, a POS terminal settles on its own cycle and a
rent debit obeys no such stack at all — running all four through one bridge
produces a bottom line that is the sum of four unrelated questions. So the
bridge reads the gateway lane (:mod:`fc.lanes`) and nothing else, while the
lanes it does not draw are still reconciled, still surfaced, and summarised
beside it in :class:`LaneTotals`.

Each segment carries the ``event_ids`` that make it up and the
``exception_ids`` raised on exactly those rows, so the bridge in the UI can be
clicked straight into the queue and the rows that come back add up to the
heading they came from.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from fc.exceptions.action import ActionGroup, action_group
from fc.lanes import LANES, LaneMap, assign_lanes
from fc.models.exception_ import Exception_
from fc.models.match import MatchResult
from fc.models.money import already_paise, to_paise
from fc.models.transaction import TransactionEvent, is_bank_account

__all__ = [
    "AT_RISK_CATEGORIES",
    "BooksVsBank",
    "BridgeSegment",
    "CashAtRisk",
    "CashBridge",
    "LaneTotals",
    "compute_cash_bridge",
]

#: Substrings ``fc.generator.razorpay_gen`` writes into a settlement-line-item
#: adjustment row's ``description`` (PRD §4.1.7). Matched here rather than
#: mapped onto its own ``TransactionEvent`` field because ``description`` was
#: never promoted off ``raw`` (CLAUDE.md: "if either side changes ... change
#: the other side in the same commit" — this is that other side, for now).
#: Compared case-insensitively (see ``_describes``). A settlement adjustment's
#: description is prose written by whoever produced the export -- "TDS 194-O",
#: "tds 194o", "Rolling Reserve Hold" -- and matching it exactly meant one
#: report's capitalisation silently dropped a whole deduction out of the bridge
#: and into the unexplained line.
_TDS_MARKER = "tds"
_RESERVE_RELEASE_MARKER = "reserve release"
_RESERVE_HOLD_MARKER = "reserve hold"

#: Categories a bridge reader would recognise as "the gap": nothing else in
#: the deduction stack already accounts for them.
_UNEXPLAINED_CATEGORIES = frozenset(
    {"missing_in_bank", "missing_in_gateway", "amount_variance", "unknown"}
)

#: The only two ways money on this screen can still be *lost*, as opposed to
#: merely being somewhere nobody has looked yet.
#:
#: ``missing_in_bank`` is a payout the processor released and the bank never
#: received: there is a support window, and past it the claim goes stale.
#: ``chargeback_unrecorded`` is a dispute inside its RBI contest window: fail
#: to contest and the money is gone by default.
#:
#: Everything else in the queue is a question about *where money is*, not a
#: countdown to losing it. Cash at risk used to read "every escalated exception
#: that happens to carry a deadline", which on a real statement summed a salary
#: NACH, a rent RTGS, ad spend and a GST challan into a figure headed "at risk"
#: — none of it gateway money, none of it losable, ₹27.5L of pure alarm. A
#: number a controller acts on has to name the action and when it expires.
AT_RISK_CATEGORIES: frozenset[str] = frozenset({"missing_in_bank", "chargeback_unrecorded"})

#: Categories that are always about a deduction, whatever raised them. See
#: :func:`_is_deduction_finding` for the one that needs more than its category.
_DEDUCTION_CATEGORIES: frozenset[str] = frozenset({"partial_refund", "chargeback_unrecorded"})


def _is_deduction_finding(exception: Exception_) -> bool:
    """Whether a finding is about *what was deducted*, not about the payout.

    Category alone is not enough. ``amount_variance`` is raised both by the
    Rulebook, which is a statement about a fee, and by the settlement sweep,
    which is a statement about a payout arriving short — and the second one
    names the whole settlement, so attributing by category put a ₹18,475.40
    shortfall on the MDR, GST *and* TDS lines at once, three times over,
    describing a fee dispute that does not exist.

    ``rules_applied`` is what tells them apart: a Rulebook finding carries the
    rule version that produced it, and a sweep finding carries nothing.
    """
    if exception.category in _DEDUCTION_CATEGORIES:
        return True
    return exception.category == "amount_variance" and bool(exception.rules_applied)


@dataclass(frozen=True)
class BridgeSegment:
    """One row of the bridge: a label, an amount, and what proves it.

    ``amount_paise`` and ``attributed_paise`` are two different questions and
    the segment carries both because conflating them produced a wrong figure on
    screen. ``amount_paise`` is the segment's place in the bridge arithmetic —
    for "Unexplained" that is ``expected_net - actual_bank``, the balancing
    residual the whole bridge must sum to. ``attributed_paise`` is what the
    exceptions named in ``exception_ids`` actually total.

    They are not the same number and cannot be made the same: the residual is
    net over the corpus after MDR, GST, TDS, refunds, chargebacks and reserve
    have come out, while the exceptions are gross per-discrepancy amounts that
    overlap those same deductions. Carrying both means whichever number a
    reader clicks, the rows they get sum to it.

    Attribution is deliberately *not* clipped to the segment. The chargeback
    line is why the two can legitimately diverge: its amount is a net of debits
    less reversals (₹46,878.50) while the exceptions on it are two gross
    unrecorded disputes (₹70,493.50), one later reversed. Both are right.
    Clipping was tried, and it was worse — it dropped any exception larger than
    its segment, which on a ₹959.64 TDS line is all of them, so four segments
    silently read ₹0.00.
    """

    label: str
    amount_paise: int
    event_ids: tuple[str, ...]
    exception_ids: tuple[str, ...] = ()
    #: Sum of ``amount_paise`` over ``exception_ids``. Always reconciles with
    #: them, because :func:`_attribute` computes the pair together.
    attributed_paise: int = 0


@dataclass(frozen=True)
class BooksVsBank:
    """The bank reconciliation statement, in the shape an accountant reads it.

    Movement per the books, movement per the bank, the difference between
    them, and — underneath — what the still-open items add up to, grouped by
    the three reasons a difference is ever legitimate: it has not landed yet,
    it happened in the account and nobody wrote it down, or somebody is still
    working out what it was.

    The three totals are *sums of open items*, deliberately not a decomposition
    of ``difference_paise``, and they will not add up to it. They cannot: the
    difference is one signed net over the period while an exception is a gross
    per-discrepancy amount, and several of them describe the same money seen
    from two sides. Subtracting the three from the difference and calling the
    remainder "unexplained" produced −₹13,94,254.68 against a difference of
    −₹3,35,254.77, which is not a residual, it is a units error. The honest
    unexplained figure is the gateway bridge's own, which balances by
    construction and is asserted to.

    Movement, not balance: a balance needs an opening figure the files do not
    always carry, while both sides state their own movements exactly.
    """

    #: The balance both sides start from, read off the statement's own first
    #: row (its closing balance less that row's movement). The daybook states
    #: no opening balance of its own, so this is what makes the two sides
    #: comparable as *balances* rather than only as movements.
    opening_balance_paise: int
    #: Closing balance per the books: opening plus what the daybook moved.
    books_balance_paise: int
    #: Closing balance per the statement, read from the ``closing_balance``
    #: column of the last row -- not reconstructed by summing deposits less
    #: withdrawals. Summing is how a statement that closes at +₹9,19,977.27
    #: came to be displayed as -₹7,34,610: that figure is the period's *net
    #: movement*, which is a different quantity and is not what "per the bank"
    #: means at the top of a reconciliation statement.
    bank_balance_paise: int
    books_movement_paise: int
    bank_movement_paise: int
    difference_paise: int
    #: The four below are a true decomposition: they are *signed contributions
    #: to* ``difference_paise`` and they sum to it exactly, which
    #: :func:`_books_vs_bank` asserts. They are not sums of exception amounts.
    #: That distinction is the whole bug this replaced -- "under investigation"
    #: read ₹9,98,737 against a difference of ₹3,35,255, because an exception
    #: is a gross per-discrepancy figure and several of them describe the same
    #: money seen from the bank side and the books side at once. A component of
    #: a difference cannot exceed the difference; a sum of exceptions can, and
    #: did.
    #:
    #: Rows the system expects to settle themselves.
    timing_paise: int
    #: Rows the statement moved and the daybook has no entry for, or the wrong
    #: one: the part of the difference a voucher closes.
    unrecorded_in_books_paise: int
    #: Rows somebody is still working out, including what no file can settle.
    under_investigation_paise: int
    #: Credits nobody could attribute. Money in the account, not exposure --
    #: kept out of the three above so none of them reads as a loss.
    unidentified_inflow_paise: int
    #: What reconciled and still contributes: rounding inside a matched group,
    #: a short credit against a group that otherwise agrees. Should be small;
    #: a large value here means matching is closing groups that do not balance.
    matched_residual_paise: int
    #: The gateway bridge's own residual — ``expected_net - actual_bank``, the
    #: figure every segment above is asserted to sum to. Not a subtraction of
    #: the three totals above; see the class docstring.
    unexplained_paise: int


@dataclass(frozen=True)
class CashAtRisk:
    """Money that can still be lost, and when the window closes."""

    amount_paise: int
    item_count: int
    earliest_deadline: date | None
    exception_ids: tuple[str, ...]

    def headline(self, *, as_of: date | None = None) -> str:
        if not self.item_count:
            return "Nothing at risk of being lost"
        if self.earliest_deadline is None or as_of is None:
            return f"At risk of being lost — {self.item_count} items"
        days = (self.earliest_deadline - as_of).days
        if days > 0:
            when = f"in {days} days"
        elif days == 0:
            when = "today"
        else:
            when = f"{-days} days ago"
        return f"At risk of being lost — {self.item_count} items, earliest deadline {when}"


@dataclass(frozen=True)
class LaneTotals:
    """One lane's own two-sided position, for the strip above the queue.

    The point is that the lanes are separate questions: a lane whose bank side
    and ledger side agree is finished whatever the others look like, and a
    controller can see at a glance which one is costing them the morning.
    """

    lane: str
    bank_in_paise: int
    bank_out_paise: int
    ledger_paise: int
    unreconciled_paise: int
    exception_count: int


@dataclass(frozen=True)
class CashBridge:
    gross_collected_paise: int
    #: The razorpay payment-credit rows that sum to `gross_collected_paise`.
    gross_event_ids: tuple[str, ...]
    deductions: tuple[BridgeSegment, ...]
    expected_net_paise: int
    actual_bank_paise: int
    #: The bank rows that sum to `actual_bank_paise` — only ones the matcher
    #: attributed to the gateway (part of a match whose `sources_covered`
    #: includes both "bank" and "razorpay").
    actual_bank_event_ids: tuple[str, ...]
    unexplained_paise: int
    #: Every deduction plus the terminal "Unexplained" line, in bridge order.
    segments: tuple[BridgeSegment, ...]
    cash_at_risk_paise: int
    reserve_pending_release_paise: int
    gst_input_credit_claimable_paise: int
    #: Captured but still held by the processor, so never collected and never
    #: part of gross. Carried so the screen can say so instead of leaving the
    #: money to reappear at the bottom as an unexplained gap.
    held_paise: int = 0
    held_event_ids: tuple[str, ...] = ()
    at_risk: CashAtRisk = field(default_factory=lambda: CashAtRisk(0, 0, None, ()))
    books_vs_bank: BooksVsBank = field(
        default_factory=lambda: BooksVsBank(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    )
    lanes: tuple[LaneTotals, ...] = ()
    #: Credits nobody could attribute to a counterparty or a document. Shown
    #: on their own because folding them into "cannot resolve" makes the total
    #: read as exposure when the money is sitting safely in the account.
    unidentified_inflow_paise: int = 0
    unidentified_inflow_exception_ids: tuple[str, ...] = ()


def _attribute(
    exceptions: Sequence[Exception_], predicate: Callable[[Exception_], bool]
) -> tuple[tuple[str, ...], int]:
    """The exceptions a segment is attributed to, and what they total.

    One function returns both halves so the ids and the total cannot drift
    apart — the ids were built by a comprehension and the total was never built
    at all, which is how a segment came to display a number no set of rows
    added up to.
    """
    selected = sorted((e for e in exceptions if predicate(e)), key=lambda e: e.exception_id)
    return tuple(e.exception_id for e in selected), sum(abs(e.amount_paise) for e in selected)


#: Vouchers that move money in or out of an account by definition — the same
#: set ``fc.pipeline`` uses to decide what the matcher may look at, and for the
#: same reason: a day book exported one row per *voucher* rather than one row
#: per *leg* writes a rent Payment as its ``Rent`` debit alone and never spells
#: out the bank credit that paid it.
_CASH_SIDE_VOUCHERS = frozenset({"Receipt", "Payment", "Contra"})


def _stated_gross_paise(event: TransactionEvent) -> int:
    """What the customer actually paid on one gateway payment row.

    The recon report states it directly, and reading it is the only way to be
    right about it, because ``fee`` does not mean the same thing in every
    export. One report writes ``amount = credit + fee`` with GST folded into
    the fee; another writes ``amount = credit + fee + tax`` with the two
    stated apart. Reconstructing gross as ``credit + fee`` therefore
    understates it by the whole GST on the second kind — ₹1,638.65 on the v2
    corpus — and computing MDR as ``fee - tax`` subtracts that GST a second
    time. The two errors cancel in ``expected_net``, which is why the bridge
    still balanced while the gross and MDR lines on screen were both wrong.

    ``amount_paise`` on the event is the *credit* — the money that moved —
    which is the right thing for matching and the wrong thing for this. Falls
    back to ``credit + fee`` when a row states no amount at all.

    Razorpay amounts are already integer paise; ``already_paise`` asserts that
    rather than converting (CLAUDE.md).
    """
    stated = event.raw.get("amount") if isinstance(event.raw, dict) else None
    if isinstance(stated, int) and stated > 0:
        return already_paise(stated)
    return event.amount_paise + (event.fee_paise or 0)


def _touches_bank(event: TransactionEvent) -> bool:
    """Whether a daybook row moves the bank account.

    Only such rows are comparable with a statement: a Sales invoice and a fee
    Journal change the books without moving the account, so counting them would
    make the two sides incomparable by construction.

    Both tests are needed. The account name catches a bank leg written down
    explicitly; the voucher type catches one that is only implied. Testing the
    name alone made the headline count every Receipt and no Payment — the books
    side saw ₹30,03,475 of money in and none of the money out, against a bank
    side that saw both, and the "difference" was then the whole outflow.
    """
    return is_bank_account(event.ledger_account) or (
        (event.voucher_type or "") in _CASH_SIDE_VOUCHERS
    )


def compute_cash_bridge(
    events: Sequence[TransactionEvent],
    exceptions: Sequence[Exception_],
    matches: Sequence[MatchResult],
    *,
    lanes: LaneMap | None = None,
    as_of: date | None = None,
) -> CashBridge:
    """Build the bridge for one run, over the gateway lane.

    The gross/deduction side is read straight off the ingested gateway rows —
    "sales were booked at gross, what did the gateway deduct" does not depend
    on what the matching cascade proved (CLAUDE.md: "the Rulebook's gap is not
    the cascade's gap" applies here too, for the same reason).

    ``actual_bank_paise`` is different: only bank rows the matcher actually
    attributed to the gateway — part of a match whose ``sources_covered``
    includes both ``bank`` and ``razorpay`` — count here.
    """
    lanes = lanes if lanes is not None else assign_lanes(events)

    gateway_matched_bank_ids: set[str] = set()
    for m in matches:
        if "bank" in m.sources_covered and "razorpay" in m.sources_covered:
            gateway_matched_bank_ids.update(m.event_ids)

    # Lane assignment reads the files; the matcher reads the evidence, and where
    # it has actually attributed a bank credit to a gateway settlement that
    # credit is gateway money whatever its narration managed to say about
    # itself. A statement whose settlement rows carry a truncated UTR and no
    # recognisable party name — which is the common case, and the reference
    # corpus's — lands every one of them outside the lane, and scoping the
    # bridge to the lane alone then dropped ₹71,136.23 of proven bank credit
    # out of "bank credited" and straight into the unexplained line.
    gateway = tuple(
        e
        for e in events
        if lanes.lane(e.event_id) == "gateway" or e.event_id in gateway_matched_bank_ids
    )

    gross_paise = 0
    mdr_paise = 0
    gst_paise = 0
    held_paise = 0
    payment_event_ids: list[str] = []
    held_event_ids: list[str] = []
    for event in gateway:
        is_payment_credit = (
            event.source == "razorpay"
            and event.txn_type == "payment"
            and event.direction == "credit"
        )
        if not is_payment_credit:
            continue
        # A payment the processor is still holding has not been collected. It
        # is real and it is not in the bridge: counting it overstates gross by
        # money no bank credit can ever be found for, and it then reappears at
        # the bottom as unexplained. Held money is a fact of its own.
        if event.on_hold:
            held_paise += _stated_gross_paise(event)
            held_event_ids.append(event.event_id)
            continue
        gross = _stated_gross_paise(event)
        gross_paise += gross
        # What the processor kept, split by what it kept it for. Derived from
        # the row's own identity rather than from a fee convention: the
        # deduction is gross less what was credited, GST is the row's stated
        # tax, and MDR is whatever is left.
        gst_paise += event.tax_paise or 0
        mdr_paise += gross - event.amount_paise - (event.tax_paise or 0)
        payment_event_ids.append(event.event_id)

    tds_paise, tds_ids = 0, []
    reserve_hold_paise, reserve_hold_ids = 0, []
    reserve_release_paise, reserve_release_ids = 0, []
    for event in gateway:
        if event.source != "razorpay" or event.txn_type != "adjustment":
            continue
        description = str(event.raw.get("description") or "").lower()
        if _TDS_MARKER in description:
            tds_paise += abs(event.amount_paise)
            tds_ids.append(event.event_id)
        elif _RESERVE_RELEASE_MARKER in description:
            reserve_release_paise += abs(event.amount_paise)
            reserve_release_ids.append(event.event_id)
        elif _RESERVE_HOLD_MARKER in description:
            reserve_hold_paise += abs(event.amount_paise)
            reserve_hold_ids.append(event.event_id)

    refund_paise, refund_ids = 0, []
    # Signed, not a magnitude: a dispute debit is a chargeback (subtracts from
    # net) and a dispute credit is its reversal — the money comes back, so it
    # must add back. Both are txn_type == "dispute"; direction is what tells
    # them apart, and filtering the loop to debits (as this once did) dropped
    # every reversal from the bridge, which is how a batch that nets out
    # correctly in the bank still showed a phantom gap of exactly one reversal.
    chargeback_paise, chargeback_ids = 0, []
    for event in gateway:
        if event.source != "razorpay":
            continue
        if event.txn_type == "refund" and event.direction == "debit":
            refund_paise += abs(event.amount_paise)
            refund_ids.append(event.event_id)
        elif event.txn_type == "dispute":
            sign = 1 if event.direction == "debit" else -1
            chargeback_paise += sign * abs(event.amount_paise)
            chargeback_ids.append(event.event_id)

    # Every bank row in the gateway lane, whether or not the matcher claimed
    # it. What the bank credited is a *fact about the statement*, not an
    # outcome of matching: a credit that arrived short, and a credit the
    # matcher correctly abstained on because two settlements could each be it,
    # are both money that landed. Counting only matched rows understated this
    # by ₹1,28,812.13 on the second corpus -- and, worse, moved that shortfall
    # into "unexplained", where it read as money missing rather than as money
    # present and unattributed.
    #
    # Filtering by match state was the right guard *before lanes*, when the
    # alternative was netting salary, rent and GST challans against gateway
    # gross. The lane does that job now, and does it on what the row is rather
    # than on whether a stage happened to succeed.
    actual_bank_paise = 0
    actual_bank_ids: list[str] = []
    for event in gateway:
        if event.source != "bank":
            continue
        sign = 1 if event.direction == "credit" else -1
        actual_bank_paise += sign * event.amount_paise
        actual_bank_ids.append(event.event_id)

    reserve_net_paise = reserve_hold_paise - reserve_release_paise
    expected_net_paise = (
        gross_paise
        - mdr_paise
        - gst_paise
        - tds_paise
        - refund_paise
        - chargeback_paise
        - reserve_net_paise
    )
    unexplained_paise = expected_net_paise - actual_bank_paise

    # Every segment attributes the exceptions raised on the rows that segment
    # is made of. That makes the relationship checkable rather than editorial —
    # the ids come from the segment's own ``event_ids`` — and it is why five of
    # the six deduction rows used to display ATTRIBUTED ₹0.00: the pair was
    # only ever computed for chargebacks and for the terminal residual, so a
    # reader clicking any other row got an empty drill-down and reasonably
    # concluded that attribution was not running at all.
    def _on_rows(row_ids: tuple[str, ...]) -> tuple[tuple[str, ...], int]:
        rows = set(row_ids)
        selected = sorted(
            (e for e in exceptions if _is_deduction_finding(e) and rows.intersection(e.event_ids)),
            key=lambda e: e.exception_id,
        )
        return (
            tuple(e.exception_id for e in selected),
            sum(abs(e.amount_paise) for e in selected),
        )

    def _segment(label: str, amount: int, row_ids: tuple[str, ...]) -> BridgeSegment:
        ids, attributed = _on_rows(row_ids)
        return BridgeSegment(label, amount, row_ids, exception_ids=ids, attributed_paise=attributed)

    deductions = (
        _segment("MDR", mdr_paise, tuple(payment_event_ids)),
        _segment("GST on MDR", gst_paise, tuple(payment_event_ids)),
        _segment("TDS 194-O", tds_paise, tuple(tds_ids)),
        _segment("Refunds settled", refund_paise, tuple(refund_ids)),
        _segment("Chargebacks", chargeback_paise, tuple(chargeback_ids)),
        _segment("Rolling reserve", reserve_net_paise, (*reserve_hold_ids, *reserve_release_ids)),
    )
    unexplained_ids, unexplained_attributed = _attribute(
        exceptions, lambda e: e.category in _UNEXPLAINED_CATEGORIES
    )
    unexplained_segment = BridgeSegment(
        "Unexplained",
        unexplained_paise,
        (),
        exception_ids=unexplained_ids,
        attributed_paise=unexplained_attributed,
    )
    segments = (*deductions, unexplained_segment)

    by_id = {e.exception_id: e for e in exceptions}
    for segment in segments:
        restated = sum(abs(by_id[i].amount_paise) for i in segment.exception_ids if i in by_id)
        if restated != segment.attributed_paise:
            raise ValueError(
                f"bridge segment {segment.label!r} attributes {segment.attributed_paise} paise "
                f"to {len(segment.exception_ids)} exception(s) that total {restated} paise"
            )
    # Deliberately no "attributed <= amount" check. The two are different
    # quantities and the chargeback segment is the proof: its amount is a *net*
    # of debits less reversals (₹46,878.50) while the exceptions on it are two
    # gross unrecorded disputes (₹70,493.50), one of which was later reversed.
    # Both figures are right. The invariant that does hold is the one above —
    # the ids and the total always describe the same set.

    total_paise = sum(segment.amount_paise for segment in segments)
    if total_paise != gross_paise - actual_bank_paise:
        raise ValueError(
            f"cash bridge segments sum to {total_paise} paise, expected gross - actual = "
            f"{gross_paise - actual_bank_paise} paise"
        )

    at_risk_items = sorted(
        (e for e in exceptions if _can_still_be_lost(e, events, as_of=as_of)),
        key=lambda e: e.exception_id,
    )
    at_risk = CashAtRisk(
        amount_paise=sum(abs(e.amount_paise) for e in at_risk_items),
        item_count=len(at_risk_items),
        earliest_deadline=min(
            (e.deadline for e in at_risk_items if e.deadline is not None), default=None
        ),
        exception_ids=tuple(e.exception_id for e in at_risk_items),
    )
    unidentified_ids, unidentified_paise = _attribute(
        exceptions, lambda e: e.category == "unidentified_inflow"
    )

    return CashBridge(
        gross_collected_paise=gross_paise,
        gross_event_ids=tuple(payment_event_ids),
        deductions=deductions,
        expected_net_paise=expected_net_paise,
        actual_bank_paise=actual_bank_paise,
        actual_bank_event_ids=tuple(actual_bank_ids),
        unexplained_paise=unexplained_paise,
        segments=segments,
        cash_at_risk_paise=at_risk.amount_paise,
        reserve_pending_release_paise=reserve_net_paise,
        gst_input_credit_claimable_paise=gst_paise,
        held_paise=held_paise,
        held_event_ids=tuple(held_event_ids),
        at_risk=at_risk,
        books_vs_bank=_books_vs_bank(
            events, exceptions, as_of=as_of, unexplained_paise=unexplained_paise
        ),
        lanes=_lane_totals(events, exceptions, lanes),
        unidentified_inflow_paise=unidentified_paise,
        unidentified_inflow_exception_ids=unidentified_ids,
    )


def _can_still_be_lost(
    exception: Exception_,
    events: Sequence[TransactionEvent],
    *,
    as_of: date | None,
) -> bool:
    """Whether this finding is money that can actually be lost before a date.

    Two shapes, and each needs more than its category to qualify.

    A ``missing_in_bank`` counts only when it names a *gateway* row: that is a
    payout the processor says it released, and the SLA is the window to claim
    it. The same category raised on a daybook row is the books describing a
    receipt the bank never made — a bookkeeping question, and counting it
    alongside the gateway row for the same settlement charged one shortfall
    twice.

    A ``chargeback_unrecorded`` counts only while its dispute window is still
    open. Past the deadline the money is already gone and no action recovers
    it; carrying it under a heading that says "at risk" claims a decision is
    still available when it is not.

    With no ``as_of`` the window cannot be judged, and an open window is
    assumed — the conservative reading, since the cost of showing a closed
    window is a wrong number and the cost of hiding an open one is a lost claim.
    """
    if exception.deadline is None or exception.category not in AT_RISK_CATEGORIES:
        return False
    if exception.category == "chargeback_unrecorded":
        return as_of is None or exception.deadline >= as_of
    named = set(exception.event_ids)
    return any(e.source == "razorpay" for e in events if e.event_id in named)


def _statement_balances(events: Sequence[TransactionEvent]) -> tuple[int, int]:
    """``(opening, closing)`` per the statement, read off its own column.

    The statement states its balance after every row, so the closing balance
    is a value to be *read*, not reconstructed. The opening balance is the
    first row's closing balance less that row's own movement — the one figure
    the file implies rather than states, and the one both sides need before
    they can be compared as balances at all.

    Returns ``(0, 0)`` when no bank row carries the column, which keeps the
    headline honest on a source that does not provide it rather than inventing
    a balance from movements.
    """
    rows = [e for e in events if e.source == "bank" and isinstance(e.raw, dict)]
    stated = [e for e in rows if str(e.raw.get("closing_balance") or "").strip()]
    if not stated:
        return 0, 0
    first, last = stated[0], stated[-1]
    opening = to_paise(str(first.raw["closing_balance"])) - first.bank_signed_paise
    return opening, to_paise(str(last.raw["closing_balance"]))


def _books_vs_bank(
    events: Sequence[TransactionEvent],
    exceptions: Sequence[Exception_],
    *,
    as_of: date | None,
    unexplained_paise: int,
) -> BooksVsBank:
    """The headline an accountant already knows how to read.

    Balances first, then the difference between them, then a decomposition of
    that difference which *sums to it*. The decomposition is taken over the
    rows themselves, not over the exceptions raised about them, and that is the
    correction: every row that moves either side contributes its signed amount
    to ``books - bank`` exactly once, and lands in exactly one bucket according
    to what the queue says should happen to it. A pair that reconciled
    contributes nothing, because the two sides cancel. Summing exception
    amounts instead double-counted every discrepancy visible from both sides
    and produced components larger than the difference they were components of.
    """
    opening, closing = _statement_balances(events)

    bank_movement = 0
    books_movement = 0
    #: event id -> its signed contribution to (books - bank).
    contribution: dict[str, int] = {}
    for event in events:
        if event.source == "bank":
            bank_movement += event.bank_signed_paise
            contribution[event.event_id] = -event.bank_signed_paise
        elif event.source == "ledger" and _touches_bank(event):
            books_movement += event.bank_signed_paise
            contribution[event.event_id] = event.bank_signed_paise

    group_of_event: dict[str, ActionGroup] = {}
    for exception in exceptions:
        group = action_group(
            exception.category,
            tier=exception.tier,
            deadline=exception.deadline,
            recheck_at=exception.recheck_at,
            as_of=as_of,
        )
        for event_id in exception.event_ids:
            group_of_event.setdefault(event_id, group)

    buckets = dict.fromkeys(
        ("waiting", "books_fix", "investigating", "unidentified_inflow", "matched"), 0
    )
    for event_id, signed in contribution.items():
        found = group_of_event.get(event_id)
        if found is None:
            buckets["matched"] += signed
        elif found in ("waiting", "books_fix", "unidentified_inflow"):
            buckets[found] += signed
        else:
            buckets["investigating"] += signed

    books_balance = opening + books_movement
    difference = books_movement - bank_movement
    total = sum(buckets.values())
    if total != difference:
        raise ValueError(
            f"books-vs-bank components sum to {total} paise against a difference of "
            f"{difference} paise; every row that moves either side must contribute to "
            "exactly one component"
        )

    return BooksVsBank(
        opening_balance_paise=opening,
        books_balance_paise=books_balance,
        bank_balance_paise=closing,
        books_movement_paise=books_movement,
        bank_movement_paise=bank_movement,
        difference_paise=difference,
        timing_paise=buckets["waiting"],
        unrecorded_in_books_paise=buckets["books_fix"],
        under_investigation_paise=buckets["investigating"],
        unidentified_inflow_paise=buckets["unidentified_inflow"],
        matched_residual_paise=buckets["matched"],
        unexplained_paise=unexplained_paise,
    )


def _lane_totals(
    events: Sequence[TransactionEvent],
    exceptions: Sequence[Exception_],
    lanes: LaneMap,
) -> tuple[LaneTotals, ...]:
    lane_of_exception: dict[str, str] = {}
    known = {e.event_id for e in events}
    for exception in exceptions:
        for event_id in exception.event_ids:
            if event_id in known:
                lane_of_exception[exception.exception_id] = lanes.lane(event_id)
                break

    out: list[LaneTotals] = []
    for lane in LANES:
        bank_in = bank_out = ledger = 0
        for event in events:
            if lanes.lane(event.event_id) != lane:
                continue
            if event.source == "bank":
                if event.direction == "credit":
                    bank_in += event.amount_paise
                else:
                    bank_out += event.amount_paise
            elif event.source == "ledger" and _touches_bank(event):
                ledger += event.bank_signed_paise
        in_lane = [e for e in exceptions if lane_of_exception.get(e.exception_id) == lane]
        out.append(
            LaneTotals(
                lane=lane,
                bank_in_paise=bank_in,
                bank_out_paise=bank_out,
                ledger_paise=ledger,
                unreconciled_paise=sum(abs(e.amount_paise) for e in in_lane),
                exception_count=len(in_lane),
            )
        )
    return tuple(out)
