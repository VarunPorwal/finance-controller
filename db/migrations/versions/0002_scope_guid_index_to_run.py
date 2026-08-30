"""scope ix_te_guid to the run, not the tenant

``0001_initial`` created ``ix_te_guid`` as ``UNIQUE (tenant_id, voucher_guid)``.
That encodes the wrong invariant and it is the reason ``POST /ingest/ledger``
returned a 500 in production for every Tally upload after the first.

**Why the original scope was wrong — do not widen it back.**

A ``voucher_guid`` is unique *within a Tally day book*. It is not a statement
that a voucher may be booked into only one reconciliation run, ever, for the
whole tenant. Re-uploading the same day book into a new run is the normal
thing a finance operator does — it is how you reconcile the same period again
after fixing a bank statement — and under the tenant-wide index the second
upload raised ``UniqueViolationError`` before a single row landed.

PRD §"Idempotency" is explicit about the mechanism:

    | Tally | voucher_guid |
    "Unique constraint on (run_id, source, source_row_id) makes re-upload
     safe by construction."

``parse_tally_csv`` already sets ``source_row_id = voucher_guid``, so
``uq_te_run_source_row`` was always the constraint the spec meant. The
tenant-wide index was a second, stricter rule nobody asked for. Scoping it to
``run_id`` keeps a genuine guarantee — one row per voucher per run, so a
double-submit inside one run cannot double-book — while letting two runs each
hold their own view of the same day book.

Idempotency of a *repeat* upload into the *same* run is handled in
``api/routers/ingest.py::_persist``, which inserts with ``ON CONFLICT DO
NOTHING`` against exactly these two constraints and reports the skipped count.
The index defines identity; the ON CONFLICT makes re-upload a no-op instead of
an error. Both halves are needed — removing either brings the 500 back.

Reversible: ``downgrade()`` restores the tenant-wide index. It will fail if any
tenant has by then booked the same ``voucher_guid`` into two different runs,
which is precisely the state the tenant-wide index cannot represent. That is
expected, not a bug in the downgrade.

Revision ID: 0002_scope_guid_index_to_run
Revises: 0001_initial
Create Date: 2026-08-30
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_scope_guid_index_to_run"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_te_guid")
    op.execute(
        "CREATE UNIQUE INDEX ix_te_guid ON transaction_events (run_id, voucher_guid) "
        "WHERE voucher_guid IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_te_guid")
    op.execute(
        "CREATE UNIQUE INDEX ix_te_guid ON transaction_events (tenant_id, voucher_guid) "
        "WHERE voucher_guid IS NOT NULL"
    )
