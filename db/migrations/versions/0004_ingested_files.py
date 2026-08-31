"""ingested_files: store raw uploaded file bytes for reuse

Schema change after the 28 Aug freeze — explicit user sign-off obtained
(session 31 Aug 2026) before adding this. Every source upload
(``POST /ingest/{source}``) previously read the file into memory, parsed
it, and discarded the bytes; only the parsed ``TransactionEvent`` rows
survived. That made "reconcile again against a file I already uploaded"
impossible — the file was simply gone. This table keeps the original
bytes per tenant so Data Sources can list past uploads and re-ingest one
into a new run without asking the user to find the file again.

Not tied to any one ``run_id``: the same stored file can be re-ingested
into several runs over time, which is the whole point of keeping it.

``fc_app`` gets SELECT/INSERT/DELETE here (not UPDATE — an uploaded file
is immutable once stored; re-uploading the same content makes a new row).
The blanket grant in 0001 only covers tables that existed when it ran, so
this table needs its own grants and its own RLS policy.

Revision ID: 0004_ingested_files
Revises: 0003_eval_gates_and_failures
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_ingested_files"
down_revision: str | None = "0003_eval_gates_and_failures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingested_files",
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),  # razorpay|bank|ledger
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('razorpay','bank','ledger')", name="ck_if_source"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("file_id"),
    )
    op.execute(
        "CREATE INDEX ix_if_tenant_source_time ON ingested_files "
        "(tenant_id, source, uploaded_at DESC)"
    )

    op.execute("GRANT SELECT, INSERT, DELETE ON ingested_files TO fc_app")

    op.execute("ALTER TABLE ingested_files ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ingested_files FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON ingested_files
          USING (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ingested_files")
    op.drop_index("ix_if_tenant_source_time", table_name="ingested_files")
    op.drop_table("ingested_files")
