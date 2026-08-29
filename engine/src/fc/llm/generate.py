"""Post-run prose — PRD §7.10, off the critical path.

Three calls per run, batched: one narrative, one request covering every cluster
label, one covering every escalated exception's explanation. One call per
cluster would have been simpler to write and would have put fifteen calls on a
run that is supposed to fit in six (§7.11).

Everything here is cosmetic by construction. The narrative is handed the
figures and forbidden to compute new ones; the cluster label is a rephrasing of
a grouping key that already decided membership; the explanation restates an
evidence pack. Each has a deterministic renderer underneath it, which is passed
in as the terminal fallback — so with ``LLM_MODE=off`` this module returns the
same shape with the same facts in plainer words, and nothing downstream can
tell the difference except a reader.

Called after ``run_pipeline`` returns. Never on the path to a number.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from fc.llm.client import LLMClient, load_prompt
from fc.llm.injection import wrap_untrusted
from fc.llm.schemas import (
    STRUCTURED,
    ClusterLabel,
    ClusterLabelsOut,
    Explanation,
    ExplanationsOut,
    NarrativeOut,
)
from fc.models.exception_ import Cluster, Exception_
from fc.models.money import fmt_inr

__all__ = ["RunFacts", "generate_cluster_labels", "generate_explanations", "generate_narrative"]

#: §7.11's budget, and what this module is allowed to spend of it.
CALLS_PER_RUN = 3


@dataclass(frozen=True)
class RunFacts:
    """Every number the narrative may use. There are no others.

    Pre-formatted where it is money, so the model reproduces a string rather
    than rendering an integer — one fewer thing it can get wrong, and it makes
    a fabricated figure obvious rather than plausible.
    """

    record_count: int
    matched_count: int
    rule_resolved_count: int
    exception_count: int
    cluster_count: int
    escalate_count: int
    monitor_count: int
    gross_collected: str
    expected_net: str
    actual_bank: str
    unexplained: str
    largest_exception: str | None = None
    largest_exception_category: str | None = None
    largest_cluster_label: str | None = None
    largest_cluster_size: int = 0

    def as_prompt(self) -> str:
        return json.dumps(self.__dict__, indent=2, sort_keys=True)


async def generate_narrative(
    facts: RunFacts,
    *,
    client: LLMClient,
    tenant_id: str,
    run_id: str,
    fallback: str,
) -> str:
    """One paragraph about the run. ``fallback`` is the deterministic headline."""
    result = await client.call(
        "narrative",
        prompt=f"Figures for this run:\n{facts.as_prompt()}",
        system=load_prompt("narrative"),
        tenant_id=tenant_id,
        run_id=run_id,
        schema=NarrativeOut,
        requires=STRUCTURED,
        fallback=json.dumps({"narrative": fallback}),
    )
    return NarrativeOut.model_validate_json(result.text).narrative


async def generate_cluster_labels(
    clusters: Sequence[Cluster],
    *,
    client: LLMClient,
    tenant_id: str,
    run_id: str,
) -> dict[str, str]:
    """Rephrase every cluster's label, in one call. Membership never reads this.

    The deterministic label from ``fc.exceptions.cluster`` is both the fallback
    and the thing being rephrased, so the worst case is that the label stays as
    it was.
    """
    if not clusters:
        return {}
    fallback = ClusterLabelsOut(
        labels=[ClusterLabel(cluster_id=c.cluster_id, label=c.label) for c in clusters]
    )
    payload = [
        {
            "cluster_id": c.cluster_id,
            "current_label": c.label,
            "root_cause": c.root_cause,
            "member_count": c.member_count,
            "total": fmt_inr(c.total_paise),
            "max_tier": c.max_tier,
        }
        for c in clusters
    ]
    result = await client.call(
        "cluster_label",
        prompt=(
            "Rewrite each cluster's label as one short phrase a finance operator "
            "would recognise. Keep the count and the subject; do not invent a cause "
            "the root_cause field does not state; do not change any number. Return a "
            "label for every cluster_id given, and no others.\n\n"
            f"{json.dumps(payload, indent=2)}"
        ),
        tenant_id=tenant_id,
        run_id=run_id,
        schema=ClusterLabelsOut,
        requires=STRUCTURED,
        fallback=fallback.model_dump_json(),
    )
    known = {c.cluster_id for c in clusters}
    labelled = ClusterLabelsOut.model_validate_json(result.text)
    # A label for a cluster that does not exist is discarded rather than
    # created: the model may rename, never add.
    return {row.cluster_id: row.label for row in labelled.labels if row.cluster_id in known}


async def generate_explanations(
    exceptions: Sequence[Exception_],
    *,
    client: LLMClient,
    tenant_id: str,
    run_id: str,
    limit: int = 20,
) -> dict[str, str]:
    """Plain-English "why is this here" for the items a human has to look at.

    Restricted to the escalate tier, and capped, because this is the third of
    three calls and the queue can be long. The recommended action — which is
    template-generated from real values in ``fc.exceptions.recommend`` — is both
    the input and the fallback.
    """
    escalated = [e for e in exceptions if e.tier == "escalate"][:limit]
    if not escalated:
        return {}
    fallback = ExplanationsOut(
        explanations=[
            Explanation(exception_id=e.exception_id, explanation=e.recommended_action)
            for e in escalated
        ]
    )
    payload = [
        {
            "exception_id": e.exception_id,
            "category": e.category,
            "amount": fmt_inr(e.amount_paise),
            "unexplained": fmt_inr(e.residual_paise),
            "recommended_action": e.recommended_action,
            "consequence": e.consequence,
            "deadline": e.deadline.isoformat() if e.deadline else None,
            "rules_applied": [r.rule_id for r in e.rules_applied],
        }
        for e in escalated
    ]
    result = await client.call(
        "explanation",
        prompt=(
            "For each exception, write one or two sentences saying why it is "
            "unresolved and what would settle it. Use only the fields given — every "
            "amount here is already formatted, reproduce it exactly, and do not "
            "compute a new one. Do not restate the category name as an explanation.\n\n"
            + wrap_untrusted(json.dumps(payload, indent=2), source="exception_queue")
        ),
        tenant_id=tenant_id,
        run_id=run_id,
        schema=ExplanationsOut,
        requires=STRUCTURED,
        fallback=fallback.model_dump_json(),
    )
    known = {e.exception_id for e in escalated}
    written = ExplanationsOut.model_validate_json(result.text)
    return {
        row.exception_id: row.explanation
        for row in written.explanations
        if row.exception_id in known
    }
