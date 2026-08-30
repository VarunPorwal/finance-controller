"""Post-run prose, off the critical path — PRD §7.10, §7.11.

Three calls per run: one narrative, one for every cluster label, one for every
escalated exception's explanation. Batched, because one call per cluster would
put fifteen calls on a run budgeted for six.

Fire-and-forget, exactly like ``api.notify``. A model outage, a quota wall, a
timeout — none of it may fail the run that triggered it, because none of it
affects a single number. The run is already reconciled by the time this is
called; what is left is wording.

This module is the seam between the database and ``fc.llm.generate``, which is
pure and knows nothing about either. It reads rows, hands the engine plain
data, and writes back only the two cosmetic fields: ``clusters.label``, which
nothing reads back (membership comes from ``grouping_key``), and the narrative,
which lives in the LLM disk cache because ``runs`` has no column for it and the
schema is frozen.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.converters import cluster_from_row, exception_from_row
from api.run_scope import event_source_run_id
from db.models import Cluster as ClusterRow
from db.models import ExceptionRow, Run, TransactionEventRow
from db.models import Match as MatchRow
from fc.llm.client import LLMClient
from fc.llm.generate import (
    RunFacts,
    generate_cluster_labels,
    generate_explanations,
    generate_narrative,
)
from fc.llm.schemas import LLMResult
from fc.models.money import fmt_inr

__all__ = ["generate_for_run", "narrative_for_run"]

_LOG = logging.getLogger("fc.generation")


async def generate_for_run(
    session: AsyncSession, *, run_id: str, tenant_id: str, client: LLMClient
) -> dict[str, int]:
    """The whole post-run pass. Returns what it did, for the run summary.

    Never raises. Every failure inside is logged and skipped, and the
    deterministic label or template stays in place — which is the same outcome
    as ``LLM_MODE=off``, so the failure path is the one that is exercised on
    every offline run rather than only in an incident.
    """
    written = {"narrative": 0, "cluster_labels": 0, "explanations": 0}
    try:
        narrative, _ = await narrative_for_run(
            session, run_id=run_id, tenant_id=tenant_id, client=client
        )
        written["narrative"] = 1 if narrative else 0
    except Exception:  # noqa: BLE001 - prose must never fail a reconciliation
        _LOG.exception("run narrative generation failed for %s; template stands", run_id)

    try:
        rows = (await session.scalars(select(ClusterRow).where(ClusterRow.run_id == run_id))).all()
        labels = await generate_cluster_labels(
            [cluster_from_row(r) for r in rows],
            client=client,
            tenant_id=tenant_id,
            run_id=run_id,
        )
        for row in rows:
            label = labels.get(row.cluster_id)
            if label:
                # Cosmetic only. ``grouping_key`` decided membership before this
                # ran and nothing reads the label back (§6.8).
                row.label = label
                written["cluster_labels"] += 1
    except Exception:  # noqa: BLE001
        _LOG.exception("cluster labelling failed for %s; deterministic labels stand", run_id)

    try:
        escalated = (
            await session.scalars(
                select(ExceptionRow).where(
                    ExceptionRow.run_id == run_id, ExceptionRow.tier == "escalate"
                )
            )
        ).all()
        explanations = await generate_explanations(
            [exception_from_row(r) for r in escalated],
            client=client,
            tenant_id=tenant_id,
            run_id=run_id,
        )
        written["explanations"] = len(explanations)
    except Exception:  # noqa: BLE001
        _LOG.exception("explanation generation failed for %s; recommendations stand", run_id)

    return written


async def narrative_for_run(
    session: AsyncSession, *, run_id: str, tenant_id: str, client: LLMClient
) -> tuple[str, LLMResult]:
    """One paragraph about a run, generated on demand and cached on disk.

    The deterministic headline is computed first and passed down as the
    terminal fallback, so this returns real prose whether or not a model
    answers — and the numbers in it are the same either way, because they are
    the same numbers.
    """
    facts = await _run_facts(session, run_id=run_id)
    fallback = _headline(facts)
    narrative = await generate_narrative(
        facts, client=client, tenant_id=tenant_id, run_id=run_id, fallback=fallback
    )
    # The result of the call itself, for model_used/cached on the response.
    return narrative, LLMResult(
        text=narrative,
        purpose="narrative",
        provider="",
        model=client.cfg.llm_mode if client.cfg.llm_mode != "live" else "",
        tier="",
        ladder_position=0,
    )


async def _run_facts(session: AsyncSession, *, run_id: str) -> RunFacts:
    """Every figure the narrative may use, computed here in SQL.

    The model is handed these and forbidden to derive anything else. That is
    the whole arrangement: prose is generated, numbers are computed.
    """
    run = await session.get(Run, run_id)
    record_count = run.record_count if run and run.record_count is not None else 0
    # Gross and bank below sum source rows, which a replay does not own.
    event_run_id = await event_source_run_id(session, run_id)

    matched = (
        await session.scalar(
            select(func.count()).select_from(MatchRow).where(MatchRow.run_id == run_id)
        )
    ) or 0
    exception_count = (
        await session.scalar(
            select(func.count()).select_from(ExceptionRow).where(ExceptionRow.run_id == run_id)
        )
    ) or 0
    escalate = (
        await session.scalar(
            select(func.count())
            .select_from(ExceptionRow)
            .where(ExceptionRow.run_id == run_id, ExceptionRow.tier == "escalate")
        )
    ) or 0
    monitor = (
        await session.scalar(
            select(func.count())
            .select_from(ExceptionRow)
            .where(ExceptionRow.run_id == run_id, ExceptionRow.tier == "monitor")
        )
    ) or 0
    rule_resolved = (
        await session.scalar(
            select(func.count())
            .select_from(ExceptionRow)
            .where(
                ExceptionRow.run_id == run_id,
                ExceptionRow.resolved_by == "rule",
            )
        )
    ) or 0
    cluster_count = (
        await session.scalar(
            select(func.count()).select_from(ClusterRow).where(ClusterRow.run_id == run_id)
        )
    ) or 0

    gross = (
        await session.scalar(
            select(func.coalesce(func.sum(TransactionEventRow.amount_paise), 0)).where(
                TransactionEventRow.run_id == event_run_id,
                TransactionEventRow.source == "razorpay",
                TransactionEventRow.direction == "credit",
            )
        )
    ) or 0
    bank = (
        await session.scalar(
            select(func.coalesce(func.sum(TransactionEventRow.amount_paise), 0)).where(
                TransactionEventRow.run_id == event_run_id,
                TransactionEventRow.source == "bank",
                TransactionEventRow.direction == "credit",
            )
        )
    ) or 0
    unexplained = (
        await session.scalar(
            select(func.coalesce(func.sum(ExceptionRow.residual_paise), 0)).where(
                ExceptionRow.run_id == run_id,
                ExceptionRow.status.in_(["open", "monitoring", "snoozed", "escalated"]),
            )
        )
    ) or 0

    largest = (
        await session.scalars(
            select(ExceptionRow)
            .where(ExceptionRow.run_id == run_id)
            .order_by(ExceptionRow.amount_paise.desc())
            .limit(1)
        )
    ).first()
    biggest_cluster = (
        await session.scalars(
            select(ClusterRow)
            .where(ClusterRow.run_id == run_id)
            .order_by(ClusterRow.member_count.desc())
            .limit(1)
        )
    ).first()

    return RunFacts(
        record_count=record_count,
        matched_count=int(matched),
        rule_resolved_count=int(rule_resolved),
        exception_count=int(exception_count),
        cluster_count=int(cluster_count),
        escalate_count=int(escalate),
        monitor_count=int(monitor),
        gross_collected=fmt_inr(int(gross)),
        expected_net=fmt_inr(int(gross)),
        actual_bank=fmt_inr(int(bank)),
        unexplained=fmt_inr(int(unexplained)),
        largest_exception=fmt_inr(largest.amount_paise) if largest else None,
        largest_exception_category=largest.category if largest else None,
        largest_cluster_label=biggest_cluster.label if biggest_cluster else None,
        largest_cluster_size=biggest_cluster.member_count if biggest_cluster else 0,
    )


def _headline(facts: RunFacts) -> str:
    """The deterministic narrative. Also the terminal fallback for the generated
    one, which is why it has to be a real sentence rather than a placeholder."""
    parts = [
        f"{facts.record_count} records reconciled: {facts.matched_count} matched, "
        f"{facts.rule_resolved_count} explained by rules, {facts.exception_count} left open.",
    ]
    if facts.escalate_count:
        parts.append(
            f"{facts.escalate_count} need a person; {facts.monitor_count} are being watched."
        )
    if facts.largest_exception:
        parts.append(
            f"The largest open item is {facts.largest_exception} "
            f"({(facts.largest_exception_category or 'unknown').replace('_', ' ')})."
        )
    if facts.largest_cluster_size > 1 and facts.largest_cluster_label:
        parts.append(
            f"{facts.largest_cluster_size} of them share one root cause: "
            f"{facts.largest_cluster_label}."
        )
    parts.append(f"{facts.unexplained} remains unexplained against {facts.actual_bank} banked.")
    return " ".join(parts)
