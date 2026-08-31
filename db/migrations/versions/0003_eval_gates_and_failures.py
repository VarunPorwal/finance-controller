"""eval_results: add gates and failures columns

The Evaluation screen (design handoff, 31 Aug 2026) needs two things
``eval_results`` had no column for: the §12.5 quality-gate pass/fail verdicts
(``check_gates()``) and the honest "what we got wrong" list
(``EvalReport.failures``). Both are pure functions of data the engine already
computes in ``fc.eval.report`` — this migration only adds storage for their
output, computed and written once per demo-mode run by
``api/routers/runs.py::create_run``.

Additive and nullable-safe (``NOT NULL DEFAULT '[]'``): existing rows, if
any, get an empty list rather than a null, so no backfill and no reader has
to special-case an old row.

Revision ID: 0003_eval_gates_and_failures
Revises: 0002_scope_guid_index_to_run
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003_eval_gates_and_failures"
down_revision: str | None = "0002_scope_guid_index_to_run"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_results",
        sa.Column("gates", JSONB, nullable=False, server_default="[]"),
    )
    op.add_column(
        "eval_results",
        sa.Column("failures", JSONB, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("eval_results", "failures")
    op.drop_column("eval_results", "gates")
