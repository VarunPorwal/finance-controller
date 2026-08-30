"""Which run's ``transaction_events`` describe a given run.

A replay deliberately does not re-persist source rows. ``event_id`` is a bare
primary key — one row per event, ever, not per run — so a replayed run cites
its parent's events rather than copying them, and ``diff_exceptions`` depends
on exactly that: it matches "the same underlying transaction" across two runs
by comparing ``event_ids`` verbatim. Copying would break the diff.

The cost of that choice is that ``run_id`` alone stops being a usable key for
"the events this run reconciled". Every consumer that asked the question that
way got zero rows for a replay: the cash bridge answered 404, the run summary
reported ``event_count: 0`` under a ``record_count`` of 1571, and the app —
which opens on the newest run — opened on a replay and showed neither.

This module is the one place that resolves it. ``event_source_run_id`` walks
the ``parent_run_id`` lineage until it finds a run that actually owns rows.
Every consumer of events-by-run calls it instead of filtering on ``run_id``
directly, so the "cite the parent" model is followed in one place rather than
rediscovered in six.

A run that owns rows resolves to itself, so an ordinary run costs one extra
``EXISTS`` and nothing else. A run with no events anywhere in its lineage
resolves to itself too, so callers that treat "no events" as an error still
raise the error they always raised.
"""

from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Run, TransactionEventRow

__all__ = ["event_source_run_id"]

#: Belt and braces against a cycle in ``parent_run_id``. The column is a
#: self-referential FK with nothing stopping A -> B -> A, and an audit is not
#: the place to discover that as a hung request.
_MAX_LINEAGE_DEPTH = 64


async def event_source_run_id(session: AsyncSession, run_id: str) -> str:
    """Return the run whose ``transaction_events`` rows describe ``run_id``.

    ``run_id`` itself when it owns rows; otherwise the nearest ancestor that
    does; otherwise ``run_id`` unchanged, so "genuinely has no events" stays
    distinguishable from "cites a parent".
    """
    current: str | None = run_id
    seen: set[str] = set()
    for _ in range(_MAX_LINEAGE_DEPTH):
        if current is None or current in seen:
            break
        seen.add(current)
        owns = await session.scalar(select(exists().where(TransactionEventRow.run_id == current)))
        if owns:
            return current
        parent = await session.scalar(select(Run.parent_run_id).where(Run.run_id == current))
        current = parent
    return run_id
