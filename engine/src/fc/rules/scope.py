"""Rule scope matching and candidate ordering — PRD §6.7, Appendix D.

``scope_matches`` answers one question: does this rule speak about this
transaction, on this date? Every clause present in the scope must hold; a clause
that is absent constrains nothing. An absent clause is *not* a wildcard match
that scores — it lowers the rule's specificity, so a rule that names Blinkit
beats a rule that names nothing when the two carry equal priority.

Counterparty comparison goes through the same normaliser ingestion used
(:func:`fc.ingest.aliases.normalise_counterparty`). Writing a second one here
would let a rule saying ``Blinkit`` miss a row ingested as ``BLNKT/SETTL``,
which is precisely the failure the alias table exists to prevent.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from fc.ingest.aliases import AliasTable, normalise_counterparty
from fc.models.rule import Rule
from fc.models.transaction import TransactionEvent

__all__ = ["candidates", "effective_on", "specificity", "scope_matches"]


def scope_matches(
    rule: Rule,
    event: TransactionEvent,
    on_date: date,
    *,
    aliases: AliasTable | None = None,
) -> bool:
    """Whether ``rule`` applies to ``event`` as at ``on_date``.

    ``on_date`` is passed rather than read off the event because a replay of
    June must use June's rates even when run in July: the caller decides which
    date the books are being closed as at, and it is not always the event's own.
    """
    if not effective_on(rule, on_date):
        return False

    scope = rule.scope
    if scope.date_from > event.effective_date:
        return False
    if scope.date_to is not None and event.effective_date > scope.date_to:
        return False
    if scope.source is not None and event.source != scope.source:
        return False
    if scope.method is not None and event.method != scope.method:
        return False
    if scope.rail is not None and event.rail != scope.rail:
        return False

    amount = abs(event.amount_paise)
    if scope.amount_min_paise is not None and amount < scope.amount_min_paise:
        return False
    if scope.amount_max_paise is not None and amount > scope.amount_max_paise:
        return False

    if scope.counterparty_matches is not None and not _counterparty_hit(
        scope.counterparty_matches, event, aliases
    ):
        return False
    if scope.narration_contains is not None and not _narration_hit(scope.narration_contains, event):
        return False
    return True


def effective_on(rule: Rule, on_date: date) -> bool:
    """``effective_from <= on_date <= effective_to``, with an open upper bound.

    Effective dating is real, not decorative: a rate change on 1 April leaves
    every March transaction on the March rate for ever, including when March is
    re-reconciled in August.
    """
    if on_date < rule.effective_from:
        return False
    return rule.effective_to is None or on_date <= rule.effective_to


def specificity(rule: Rule) -> int:
    """How many clauses the scope constrains. Ties in priority break on this."""
    return rule.scope.specificity


def candidates(
    rules: Iterable[Rule],
    event: TransactionEvent,
    on_date: date,
    *,
    aliases: AliasTable | None = None,
    include_inactive: bool = False,
) -> tuple[Rule, ...]:
    """Matching rules in §6.7 order: priority DESC, specificity DESC, version DESC.

    ``rule_id`` is the final sort key. It never decides which rule wins — two
    rules identical in priority, specificity and version are interchangeable by
    construction — but without it the order would depend on the caller's
    iteration order, and "same seed, byte-identical output" would be false for a
    reason no one could see in the output.
    """
    matching: list[Rule] = [
        rule
        for rule in rules
        if (include_inactive or rule.status == "active")
        and scope_matches(rule, event, on_date, aliases=aliases)
    ]
    return tuple(
        sorted(
            matching,
            key=lambda r: (-r.priority, -specificity(r), -r.version, r.rule_id),
        )
    )


def _counterparty_hit(
    wanted: Sequence[str], event: TransactionEvent, aliases: AliasTable | None
) -> bool:
    """Any listed counterparty matching the event's, after normalisation.

    The event's own ``counterparty_norm`` is preferred when ingestion resolved
    one, because that is the value the alias table already canonicalised. The
    raw ``counterparty`` is normalised as a fallback so a rule still matches a
    source that carries a party but no resolved alias.
    """
    observed = {
        normalise_counterparty(value, aliases)
        for value in (event.counterparty_norm, event.counterparty)
        if value
    }
    if not observed:
        return False
    return any(normalise_counterparty(name, aliases) in observed for name in wanted)


def _narration_hit(needles: Sequence[str], event: TransactionEvent) -> bool:
    haystack = (event.raw_narration or "").upper()
    if not haystack:
        return False
    return any(needle.upper() in haystack for needle in needles)
