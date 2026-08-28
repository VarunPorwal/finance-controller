"""Reconciliation pipeline orchestration, stages 0-9 — PRD §3.3, §6.

Implemented in a later prompt. The module exists now so the stage vocabulary is
fixed alongside the schema: ``runs.config`` and ``matches.stage`` both key off
these names.
"""

from __future__ import annotations

from typing import Final

__all__ = ["PIPELINE_STAGES"]

PIPELINE_STAGES: Final[tuple[str, ...]] = (
    "ingest",
    "normalise",
    "block",
    "match_cascade",
    "three_way",
    "apply_rules",
    "classify_exceptions",
    "cluster",
    "tier_and_prioritise",
    "cash_bridge",
)
