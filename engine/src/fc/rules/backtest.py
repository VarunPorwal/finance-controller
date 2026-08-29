"""Rule back-testing — PRD §2.6 D4, §5.9.

A wrong rule is worse than no rule. No rule leaves an exception in the queue
where a human eventually looks at it; a wrong rule closes it with a plausible
arithmetic story attached, and nobody looks again. So a rule is never promoted
on the strength of its author's confidence: it is replayed against history
first, and the number that decides is ``would_wrongly_close``.

``would_wrongly_close`` is judged against ground truth where the corpus has it
and against prior human resolutions otherwise, and — before either — against the
category itself. A ``chargeback_unrecorded`` whose 18% happens to land inside
tolerance is *arithmetically* explained and still must not close: the money is a
dispute the books never recorded, not a fee. That check needs no ground truth at
all, which matters, because the cases most dangerous to close are exactly the
ones a merchant has never resolved before.

Nothing here decides anything on its own. It produces the numbers a human
approves against (§8.8: "Never auto-activates").
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from fc.config import Config
from fc.ingest.aliases import AliasTable
from fc.models.exception_ import NEVER_AUTO, ExceptionCategory
from fc.models.money import fmt_inr
from fc.models.rule import Rule
from fc.models.transaction import TransactionEvent
from fc.rules.apply import apply_rules

__all__ = [
    "BacktestResult",
    "Bucket",
    "CaseTruth",
    "HistoricalCase",
    "Recommendation",
    "WrongClose",
    "backtest",
    "render",
]

Recommendation = Literal["activate", "adjust", "discard"]
TruthSource = Literal["category", "ground_truth", "human_resolution"]


@dataclass(frozen=True)
class CaseTruth:
    """What is actually known about how a historical case should have ended.

    ``closable_by_rule`` is the whole question: not "was this exception real"
    but "was deduction arithmetic the correct explanation for it". A partial
    refund is real *and* closable by a refund rule; a chargeback is real and is
    not closable by any deduction rule, because no deduction happened.
    """

    source: Literal["ground_truth", "human_resolution"]
    closable_by_rule: bool
    #: What the case actually was, in the words the back-test panel will quote.
    reason: str
    resolution_category: str | None = None


@dataclass(frozen=True)
class HistoricalCase:
    """One past exception, replayable against a candidate rule."""

    exception_id: str
    event: TransactionEvent
    on_date: date
    gap_paise: int
    gross_paise: int
    category: ExceptionCategory = "unknown"
    n_txns: int = 1
    truth: CaseTruth | None = None


@dataclass(frozen=True)
class Bucket:
    """A counted set of cases, with the money and the ids behind the count."""

    count: int = 0
    total_paise: int = 0
    exception_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WrongClose:
    """One case the rule would have closed that it must not have. And why."""

    exception_id: str
    amount_paise: int
    category: ExceptionCategory
    evidence: TruthSource
    why: str


@dataclass(frozen=True)
class BacktestResult:
    """The D4 panel, as data."""

    rule_id: str
    version: int
    version_hash: str
    would_explain: Bucket = field(default_factory=Bucket)
    would_wrongly_close: Bucket = field(default_factory=Bucket)
    would_partially_explain: Bucket = field(default_factory=Bucket)
    wrong_closes: tuple[WrongClose, ...] = ()
    net_recommendation: Recommendation = "discard"
    cases_considered: int = 0
    #: Cases the rule fully explains where nothing — not the category, not ground
    #: truth, not a prior human resolution — corroborates that closing them is
    #: right. Counted inside ``would_explain`` and reported separately, because
    #: "14 explained" reads very differently when 14 of them are unverified.
    unverified: int = 0

    def to_json(self) -> dict[str, Any]:
        """The ``rules.backtest_result`` JSONB payload (§4.3.6, §5.9)."""
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "version_hash": self.version_hash,
            "would_explain": _bucket_json(self.would_explain),
            "would_wrongly_close": {
                **_bucket_json(self.would_wrongly_close),
                "why": [
                    {
                        "exception_id": w.exception_id,
                        "amount_paise": w.amount_paise,
                        "category": w.category,
                        "evidence": w.evidence,
                        "why": w.why,
                    }
                    for w in self.wrong_closes
                ],
            },
            "would_partially_explain": _bucket_json(self.would_partially_explain),
            "net_recommendation": self.net_recommendation,
            "cases_considered": self.cases_considered,
            "unverified": self.unverified,
        }


def backtest(
    rule: Rule,
    cases: Iterable[HistoricalCase],
    *,
    cfg: Config | None = None,
    aliases: AliasTable | None = None,
) -> BacktestResult:
    """Replay one rule against history.

    The rule is applied **alone**, not alongside the active rulebook. The
    question a human is being asked is "what does adding this rule do", and
    answering it with the whole book's behaviour would credit this rule with
    explanations another rule already provides.
    """
    explained: list[HistoricalCase] = []
    partial: list[HistoricalCase] = []
    wrong: list[WrongClose] = []
    considered = 0
    unverified = 0

    for case in sorted(cases, key=lambda c: c.exception_id):
        considered += 1
        outcome = apply_rules(
            (rule,),
            event=case.event,
            on_date=case.on_date,
            gap_paise=case.gap_paise,
            gross_paise=case.gross_paise,
            n_txns=case.n_txns,
            cfg=cfg,
            aliases=aliases,
            # A rule being back-tested is by definition not active yet. This is
            # the only caller that may say so, and it decides nothing on its own.
            include_inactive=True,
        )
        if outcome.outcome == "not_applicable":
            continue
        if outcome.outcome == "partially_explained":
            # A partial explanation cannot close anything (see
            # ``RuleOutcomeResult.may_auto_close``), so it is never a wrong
            # close - it is a smaller exception, which is the point.
            partial.append(case)
            continue

        verdict = _must_not_close(case)
        if verdict is not None:
            evidence, why = verdict
            wrong.append(
                WrongClose(
                    exception_id=case.exception_id,
                    amount_paise=abs(case.gap_paise),
                    category=case.category,
                    evidence=evidence,
                    why=(
                        f"the rule accounts for {fmt_inr(outcome.explained_paise)} in full "
                        f"({outcome.applications[0].arithmetic}), but {why}"
                    ),
                )
            )
            continue
        if case.truth is None:
            unverified += 1
        explained.append(case)

    return BacktestResult(
        rule_id=rule.rule_id,
        version=rule.version,
        version_hash=rule.version_hash,
        would_explain=_bucket(explained),
        would_wrongly_close=Bucket(
            count=len(wrong),
            total_paise=sum(w.amount_paise for w in wrong),
            exception_ids=tuple(w.exception_id for w in wrong),
        ),
        would_partially_explain=_bucket(partial),
        wrong_closes=tuple(wrong),
        net_recommendation=_recommend(len(explained), len(wrong), len(partial)),
        cases_considered=considered,
        unverified=unverified,
    )


def _must_not_close(case: HistoricalCase) -> tuple[TruthSource, str] | None:
    """Whether closing this case by deduction arithmetic would be wrong, and why.

    The category is asked *first* and overrides a recorded resolution. A human
    who once resolved a chargeback by writing it off did not thereby licence a
    commission rule to close the next one silently, and ``NEVER_AUTO`` is not a
    preference that evidence can outvote (CLAUDE.md: "don't soften this to raise
    coverage").
    """
    if case.category in NEVER_AUTO:
        return "category", _NEVER_AUTO_REASONS.get(
            case.category, f"{case.category} escalates regardless of confidence"
        )
    if case.truth is not None and not case.truth.closable_by_rule:
        source: TruthSource = case.truth.source
        return source, case.truth.reason
    return None


#: Why each NEVER_AUTO category resists arithmetic, in the words the panel shows.
#: These are the sentences a human reads before deciding whether to activate, so
#: they say what the money actually is rather than naming the rule that blocked it.
_NEVER_AUTO_REASONS: dict[str, str] = {
    "chargeback_unrecorded": (
        "the money is a disputed debit the ledger never recorded, not a fee — closing it "
        "would hide a real loss behind a plausible commission calculation"
    ),
    "duplicate_ledger_entry": (
        "the gap is a voucher booked twice, not a deduction — the arithmetic matches "
        "because the duplicate is the same amount, which is the bug, not the explanation"
    ),
    "ambiguous_multi_candidate": (
        "more than one counterpart fits this item; a rule that explains the amount does "
        "not establish which one, and picking one would be a guess"
    ),
    "nach_batch_unexploded": (
        "the line is an unexploded NACH batch — the amount is a sum of unrelated mandates, "
        "so any rate applied to it explains a total that has no single counterpart"
    ),
    "unknown": "the category could not be established, and an unclassified item cannot be closed",
}


def _recommend(explained: int, wrong: int, partial: int) -> Recommendation:
    """The D4 verdict. A stated decision table, not a judgement call.

    Any wrong close discards the rule outright, whatever it would have explained
    — the trade "closes 14 correctly, closes 1 chargeback wrongly" is not a
    trade this system makes.
    """
    if wrong > 0:
        return "discard"
    if explained > 0:
        return "activate"
    if partial > 0:
        return "adjust"
    return "discard"


def _bucket(cases: Sequence[HistoricalCase]) -> Bucket:
    return Bucket(
        count=len(cases),
        total_paise=sum(abs(c.gap_paise) for c in cases),
        exception_ids=tuple(c.exception_id for c in cases),
    )


def _bucket_json(bucket: Bucket) -> dict[str, Any]:
    return {
        "count": bucket.count,
        "total_paise": bucket.total_paise,
        "exception_ids": list(bucket.exception_ids),
    }


def render(result: BacktestResult) -> str:
    """The §2.6 D4 panel as text, for the CLI and the back-test dialog."""
    lines = [
        f"Rule: {result.rule_id} v{result.version}  [{result.version_hash[:12]}]",
        f"  Would have explained            {result.would_explain.count:>4} exceptions   "
        f"({fmt_inr(result.would_explain.total_paise)})",
        f"  Would have wrongly closed       {result.would_wrongly_close.count:>4} items        "
        f"({fmt_inr(result.would_wrongly_close.total_paise)})",
        f"  Would have partially explained  {result.would_partially_explain.count:>4} more         "
        f"({fmt_inr(result.would_partially_explain.total_paise)})",
        f"  Unverified among the explained  {result.unverified:>4}",
        f"  Cases replayed                  {result.cases_considered:>4}",
    ]
    for wrong in result.wrong_closes:
        lines.append(
            f"    ! {wrong.exception_id} ({wrong.category}, {fmt_inr(wrong.amount_paise)}): "
            f"{wrong.why}"
        )
    lines.append(f"  -> {result.net_recommendation.upper()}")
    return "\n".join(lines)
