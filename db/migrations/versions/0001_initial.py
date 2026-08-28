"""initial schema: 12 tables, indexes, app role, RLS, rule immutability trigger

Implements PRD §4.3 (schema), §4.4 (row-level security) and §4.5 (indexing) in
one migration. The schema is frozen as of 27 Aug 2026 (§0.4); changes after
28 Aug require the "stop and ask" rule in CLAUDE.md.

Three things here are load-bearing and easy to lose in a refactor:

* ``ix_te_block`` is an *expression* index on ``(amount_paise/100000)``. It is
  what turns the O(n^2) candidate comparison into a bucketed scan (§4.5).
* ``rules_immutable()`` makes the replay story true rather than aspirational —
  the database itself refuses to rewrite an active rule (§4.3.6).
* RLS binds only on a non-owner role, so ``fc_app`` / ``fc_app_user`` are
  created here and ``FORCE ROW LEVEL SECURITY`` is applied after the grants.
  Migrations keep running as the owner; the API connects as ``fc_app_user``.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-28
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every tenant-scoped table carries RLS (§4.4). ``tenants`` is deliberately not
#: in this list: it is the table the tenant id is resolved *from*.
RLS_TABLES: tuple[str, ...] = (
    "transaction_events",
    "matches",
    "exceptions",
    "clusters",
    "rules",
    "runs",
    "audit_events",
    "counterparty_aliases",
    "eval_results",
    "users",
)

#: Indexes that Alembic cannot express: expression indexes, DESC ordering,
#: partial uniqueness and the pgvector access method. §4.5, in table order.
RAW_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_te_run_src",
        "CREATE INDEX ix_te_run_src ON transaction_events (run_id, source)",
    ),
    (
        # THE blocking index. The division expression is the point of it; a
        # plain column index here would not serve the bucketed scan at all.
        "ix_te_block",
        "CREATE INDEX ix_te_block ON transaction_events "
        "(run_id, txn_date, ((amount_paise / 100000)))",
    ),
    (
        "ix_te_utr",
        "CREATE INDEX ix_te_utr ON transaction_events (utr) WHERE utr IS NOT NULL",
    ),
    (
        "ix_te_rrn",
        "CREATE INDEX ix_te_rrn ON transaction_events (rrn) WHERE rrn IS NOT NULL",
    ),
    (
        "ix_te_order",
        "CREATE INDEX ix_te_order ON transaction_events (order_id) WHERE order_id IS NOT NULL",
    ),
    (
        "ix_te_settlement",
        "CREATE INDEX ix_te_settlement ON transaction_events (settlement_id) "
        "WHERE settlement_id IS NOT NULL",
    ),
    (
        # Tally idempotency: one voucher GUID per tenant.
        "ix_te_guid",
        "CREATE UNIQUE INDEX ix_te_guid ON transaction_events (tenant_id, voucher_guid) "
        "WHERE voucher_guid IS NOT NULL",
    ),
    (
        # narration_vec is CUT from the build (§0.1) but ships so that layering
        # embeddings on later needs no migration.
        "ix_te_vec",
        "CREATE INDEX ix_te_vec ON transaction_events USING hnsw (narration_vec vector_cosine_ops)",
    ),
    ("ix_m_run", "CREATE INDEX ix_m_run ON matches (run_id)"),
    ("ix_m_stage", "CREATE INDEX ix_m_stage ON matches (run_id, stage)"),
    (
        # THE triage queue index. DESC matters: the queue reads highest first.
        "ix_exc_queue",
        "CREATE INDEX ix_exc_queue ON exceptions (run_id, status, priority_score DESC)",
    ),
    (
        "ix_exc_sig",
        "CREATE INDEX ix_exc_sig ON exceptions (tenant_id, signature, status)",
    ),
    (
        "ix_exc_recheck",
        "CREATE INDEX ix_exc_recheck ON exceptions (recheck_at) WHERE status = 'monitoring'",
    ),
    (
        "ix_exc_cluster",
        "CREATE INDEX ix_exc_cluster ON exceptions (cluster_id) WHERE cluster_id IS NOT NULL",
    ),
    (
        "ix_rules_active",
        "CREATE INDEX ix_rules_active ON rules (tenant_id, status, effective_from, priority DESC)",
    ),
    (
        "ix_audit_subject",
        "CREATE INDEX ix_audit_subject ON audit_events (subject_type, subject_id, seq)",
    ),
    (
        "ix_runs_tenant_time",
        "CREATE INDEX ix_runs_tenant_time ON runs (tenant_id, started_at DESC)",
    ),
    (
        "ix_users_tenant",
        "CREATE INDEX ix_users_tenant ON users (tenant_id) WHERE status = 'active'",
    ),
    ("ix_llm_run", "CREATE INDEX ix_llm_run ON llm_calls (run_id, purpose)"),
)


def upgrade() -> None:
    _create_extensions()
    _create_tables()
    _create_indexes()
    _create_app_role()
    _enable_rls()
    _create_rules_immutable_trigger()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_rules_immutable ON rules")
    op.execute("DROP FUNCTION IF EXISTS rules_immutable()")
    # Tables first. Dropping them takes their RLS policies and every grant
    # fc_app holds with them, which is what lets DROP ROLE succeed below.
    op.drop_table("transaction_events")
    op.drop_table("matches")
    op.drop_table("exceptions")
    op.drop_table("eval_results")
    op.drop_table("clusters")
    op.drop_table("runs")
    op.drop_table("rules")
    op.drop_table("counterparty_aliases")
    op.drop_table("users")
    op.drop_table("tenants")
    op.drop_table("llm_calls")
    op.drop_table("audit_events")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM fc_app")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM fc_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM fc_app")
    op.execute("DROP ROLE IF EXISTS fc_app_user")
    op.execute("DROP ROLE IF EXISTS fc_app")


def _create_extensions() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def _create_tables() -> None:
    op.create_table(
        "audit_events",
        sa.Column("seq", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ruleset_hash", sa.Text(), nullable=True),
        sa.Column("prev_hash", sa.Text(), nullable=False),
        sa.Column("this_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("seq"),
    )
    op.create_table(
        "llm_calls",
        sa.Column("call_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("ladder_position", sa.Integer(), nullable=False),
        sa.Column("prompt_hash", sa.Text(), nullable=False),
        sa.Column("cached", sa.Boolean(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("thinking_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("call_id"),
    )
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("legal_name", sa.Text(), nullable=True),
        sa.Column("gstin", sa.Text(), nullable=True),
        sa.Column("pan", sa.Text(), nullable=True),
        sa.Column("base_currency", sa.Text(), server_default=sa.text("'INR'"), nullable=False),
        sa.Column(
            "fiscal_year_start_month",
            sa.SmallInteger(),
            server_default=sa.text("4"),
            nullable=False,
        ),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
    )
    op.create_table(
        "users",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("auth_subject", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_table(
        "counterparty_aliases",
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("canonical", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("confirmed_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("tenant_id", "alias"),
    )
    op.create_table(
        "rules",
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("version_hash", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deductions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tolerance", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("priority", sa.Integer(), server_default=sa.text("100"), nullable=False),
        sa.Column(
            "effective_confidence",
            sa.Numeric(precision=5, scale=4),
            server_default=sa.text("0.95"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activated_by", sa.Text(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backtest_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["activated_by"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("rule_id", "version"),
    )
    op.create_table(
        "runs",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("triggered_by", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("ruleset_hash", sa.Text(), nullable=False),
        sa.Column("input_hashes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("runtime_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("parent_run_id", sa.Text(), nullable=True),
        sa.Column("replay_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["parent_run_id"], ["runs.run_id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.user_id"]),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_table(
        "clusters",
        sa.Column("cluster_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("grouping_key", sa.Text(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("total_paise", sa.BigInteger(), nullable=False),
        sa.Column("max_tier", sa.Text(), nullable=False),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("cluster_id"),
    )
    op.create_table(
        "eval_results",
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("true_positive", sa.Integer(), nullable=False),
        sa.Column("false_positive", sa.Integer(), nullable=False),
        sa.Column("true_negative", sa.Integer(), nullable=False),
        sa.Column("false_negative", sa.Integer(), nullable=False),
        sa.Column("precision_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("recall_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("f1", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("abstention_pct", sa.Numeric(precision=6, scale=3), nullable=True),
        sa.Column("false_auto_resolutions", sa.Integer(), nullable=False),
        sa.Column("auto_threshold", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("coverage_curve", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("by_category", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("by_stage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_table(
        "exceptions",
        sa.Column("exception_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("event_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("residual_paise", sa.BigInteger(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Numeric(precision=8, scale=4), nullable=False),
        sa.Column("cluster_id", sa.Text(), nullable=True),
        sa.Column(
            "rules_applied",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column("consequence", sa.Text(), nullable=True),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("recheck_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recheck_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("resolved_by_user", sa.Text(), nullable=True),
        sa.Column("resolved_via", sa.Text(), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("resolution_category", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("tier IN ('auto','monitor','escalate')", name="ck_exc_tier"),
        sa.ForeignKeyConstraint(["resolved_by_user"], ["users.user_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("exception_id"),
    )
    op.create_table(
        "matches",
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("group_key", sa.Text(), nullable=False),
        sa.Column("event_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("sources_covered", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("residual_paise", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("rule_version_hash", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("auto_closed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_matches_confidence"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("match_id"),
    )
    op.create_table(
        "transaction_events",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_row_id", sa.Text(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), server_default=sa.text("'INR'"), nullable=False),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("utr", sa.Text(), nullable=True),
        sa.Column("rrn", sa.Text(), nullable=True),
        sa.Column("settlement_id", sa.Text(), nullable=True),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("payment_id", sa.Text(), nullable=True),
        sa.Column("voucher_number", sa.Text(), nullable=True),
        sa.Column("voucher_guid", sa.Text(), nullable=True),
        sa.Column("counterparty", sa.Text(), nullable=True),
        sa.Column("counterparty_norm", sa.Text(), nullable=True),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("rail", sa.Text(), nullable=True),
        sa.Column("txn_type", sa.Text(), nullable=True),
        sa.Column("raw_narration", sa.Text(), nullable=True),
        sa.Column("narration_vec", pgvector.sqlalchemy.Vector(dim=768), nullable=True),
        sa.Column("fee_paise", sa.BigInteger(), nullable=True),
        sa.Column("tax_paise", sa.BigInteger(), nullable=True),
        sa.Column("on_hold", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ledger_account", sa.Text(), nullable=True),
        sa.Column("voucher_type", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("gt_match_group", sa.Text(), nullable=True),
        sa.Column("gt_label", sa.Text(), nullable=True),
        sa.CheckConstraint("amount_paise >= 0", name="ck_te_amount_nonneg"),
        sa.CheckConstraint("direction IN ('credit','debit')", name="ck_te_direction"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.tenant_id"]),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("run_id", "source", "source_row_id", name="uq_te_run_source_row"),
    )


def _create_indexes() -> None:
    for _name, statement in RAW_INDEXES:
        op.execute(statement)


def _create_app_role() -> None:
    """Create the non-owner role the API connects as.

    RLS policies do not apply to a table's owner, so without this role the §4.4
    policies would be decorative. Alembic keeps running as the owner; only the
    application uses ``fc_app_user``.
    """
    password = os.environ.get("FC_APP_PASSWORD", "").strip()
    if not password:
        raise RuntimeError(
            "FC_APP_PASSWORD is not set. It is the login password for fc_app_user, "
            "the non-owner role that row-level security binds on."
        )
    if "'" in password or "\\" in password:
        raise RuntimeError("FC_APP_PASSWORD must not contain a quote or a backslash")

    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fc_app') THEN
            CREATE ROLE fc_app NOLOGIN;
          END IF;
        END $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO fc_app")
    op.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO fc_app")
    op.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO fc_app")

    # After the blanket grant, not before: GRANT ... ON ALL TABLES hands fc_app
    # UPDATE on audit_events, which would quietly reopen the append-only ledger.
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM PUBLIC")
    op.execute("REVOKE UPDATE, DELETE ON audit_events FROM fc_app")

    # The blanket grant also covered alembic_version, which the application has
    # no business touching and which would block DROP ROLE on downgrade.
    op.execute("REVOKE ALL ON alembic_version FROM fc_app")

    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fc_app_user') THEN
            CREATE ROLE fc_app_user LOGIN PASSWORD '{password}' IN ROLE fc_app;
          END IF;
        END $$
        """
    )


def _enable_rls() -> None:
    """§4.4. FORCE is applied only now, after fc_app exists and holds grants."""
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # Without FORCE, the table owner bypasses every policy below.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
              USING (tenant_id = current_setting('app.tenant_id', true))
            """
        )

    # Auditors read everything in their tenant and write nothing.
    op.execute(
        """
        CREATE POLICY auditor_readonly ON exceptions
          FOR SELECT
          USING (tenant_id = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        CREATE POLICY no_write_for_auditor ON exceptions
          FOR UPDATE
          USING (
            tenant_id = current_setting('app.tenant_id', true)
            AND current_setting('app.role', true) <> 'auditor'
          )
        """
    )
    # Audit ledger: insert only. UPDATE and DELETE are revoked above as well.
    op.execute(
        """
        CREATE POLICY audit_append_only ON audit_events
          FOR INSERT WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def _create_rules_immutable_trigger() -> None:
    """§4.3.6. The database itself refuses to let rule history be rewritten."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION rules_immutable() RETURNS trigger AS $$
        BEGIN
          IF OLD.status = 'active' AND (
               NEW.scope      IS DISTINCT FROM OLD.scope
            OR NEW.deductions IS DISTINCT FROM OLD.deductions
            OR NEW.tolerance  IS DISTINCT FROM OLD.tolerance) THEN
            RAISE EXCEPTION 'Active rules are immutable. Create a new version.';
          END IF;
          RETURN NEW;
        END $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rules_immutable BEFORE UPDATE ON rules
          FOR EACH ROW EXECUTE FUNCTION rules_immutable()
        """
    )
