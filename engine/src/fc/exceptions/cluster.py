"""Clustering — PRD §6.8. "One root cause, not 41 separate exceptions."

Two steps, and only one of them decides anything:

1. **Deterministic key**: ``(category, counterparty_norm, rail,
   rule_gap_signature, amount_band)``. Membership is entirely this — two
   exceptions with the same key are the same root cause, full stop.
2. **Label**: cosmetic, built from the same fields the key already commits
   to. PRD §6.8's "LLM writes the cluster label" is a narrative rewrite of
   something already true, not a decision, and wiring a live model into a
   path that ``make eval`` must run with no network and byte-identical output
   (CLAUDE.md hard rules 6 and 9) buys a cuter sentence at the cost of both.
   This label is deterministic for that reason; nothing here stops a later
   pass from asking an LLM to rephrase it, as long as membership never reads
   the result back (§6.8: "cosmetic only, never affects membership").

Embeddings are cut per §0.1: the ``unknown``-only embedding assist never
shipped, so an ``unknown`` exception clusters on the same deterministic key as
everything else, or not at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fc.exceptions.classify import Classified
from fc.models.exception_ import Tier
from fc.rules.learner import gap_shape

__all__ = ["ClusterGroup", "cluster_exceptions", "grouping_key"]

_SEP = "\x1f"
_TIER_RANK: dict[Tier, int] = {"auto": 0, "monitor": 1, "escalate": 2}

#: A cluster of one is not a root cause shared by several exceptions - it's
#: just the exception, and giving it a cluster_id would inflate "6 root
#: causes" with singletons that never needed grouping.
_MIN_CLUSTER_SIZE = 2


@dataclass(frozen=True)
class ClusterGroup:
    """One root cause, and the members (by index into the input sequence) it explains."""

    grouping_key: str
    root_cause: str
    label: str
    member_indices: tuple[int, ...]
    total_paise: int
    max_tier: Tier
    suggested_fix: str | None = None


def grouping_key(classified: Classified) -> str:
    """§6.8's deterministic key, joined on a separator none of its parts can contain."""
    parts = (
        classified.category,
        classified.counterparty_norm or "-",
        classified.rail or "-",
        gap_shape(
            classified.gap_paise or classified.residual_paise,
            classified.gross_paise or classified.amount_paise,
        ),
        classified.amount_band,
    )
    return _SEP.join(parts)


def cluster_exceptions(
    classified: Sequence[Classified],
    tiers: Sequence[Tier],
) -> tuple[ClusterGroup, ...]:
    """Group by the deterministic key; sorted so output order is a pure
    function of the key, not of dict insertion order (hard rule 9)."""
    if len(classified) != len(tiers):
        raise ValueError(f"{len(classified)} classified items but {len(tiers)} tiers")

    groups: dict[str, list[int]] = {}
    for index, item in enumerate(classified):
        groups.setdefault(grouping_key(item), []).append(index)

    clusters: list[ClusterGroup] = []
    for key, indices in sorted(groups.items()):
        if len(indices) < _MIN_CLUSTER_SIZE:
            continue
        members = [classified[i] for i in indices]
        member_tiers = [tiers[i] for i in indices]
        clusters.append(
            ClusterGroup(
                grouping_key=key,
                root_cause=members[0].category,
                label=_label(members),
                member_indices=tuple(indices),
                total_paise=sum(m.amount_paise for m in members),
                max_tier=max(member_tiers, key=lambda t: _TIER_RANK[t]),
                suggested_fix=_suggested_fix(members),
            )
        )
    return tuple(clusters)


def _label(members: Sequence[Classified]) -> str:
    sample = members[0]
    subject = sample.counterparty_norm or sample.rail or "multiple counterparties"
    return f"{len(members)}× {sample.category.replace('_', ' ')} — {subject}"


def _suggested_fix(members: Sequence[Classified]) -> str | None:
    rule_ids = {ref.rule_id for member in members for ref in member.rules_applied}
    if len(rule_ids) == 1:
        return f"Review the {next(iter(rule_ids))} rule; it consistently under-explains this shape."
    if members[0].category == "timing_lag":
        return "No fix needed; these resolve on their own recheck."
    return None
