"""rules: grant DELETE so a never-activated draft can be removed

Schema/permission change after the 28 Aug freeze — explicit user sign-off
obtained (session 31 Aug 2026) alongside 0004_ingested_files, for the same
"bulk-importing rules for testing needs an easy way to clear the ones that
didn't pan out" request.

``fc_app`` was never granted DELETE on any table (0001's blanket grant is
SELECT/INSERT/UPDATE only), so hard-deleting a rule was impossible at the
database layer regardless of application code. This grants it narrowly on
``rules`` only. It does **not** relax ``rules_immutable()`` — that trigger
still refuses to rewrite an active row's scope/deductions/tolerance, and
the API layer (not this migration) is what refuses to DELETE a row whose
``status`` is not ``draft``. A rule that was ever active keeps existing
only through ``/retire`` (a status change, never a row removal), so its
audit trail and any exception that cited it stay intact.

Revision ID: 0005_rules_draft_delete
Revises: 0004_ingested_files
Create Date: 2026-08-31
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_rules_draft_delete"
down_revision: str | None = "0004_ingested_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT DELETE ON rules TO fc_app")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON rules FROM fc_app")
