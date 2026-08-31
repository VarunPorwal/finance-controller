"""SQLAlchemy 2.0 models mirroring PRD §4.3 — the 12 core tables.

Every money column is ``BIGINT`` paise. Never ``NUMERIC``, never ``DOUBLE``:
the arithmetic that matters happens in the engine over ``int`` and ``Decimal``,
and the database stores the result exactly.

``engine/`` never imports this module. It is for ``api/`` and Alembic only.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NARRATION_VEC_DIM = 768

_NOW = sa.text("now()")
_EMPTY_JSON = sa.text("'{}'::jsonb")
_EMPTY_JSON_ARRAY = sa.text("'[]'::jsonb")


class Base(DeclarativeBase):
    """Declarative base for every table in the schema."""


class Tenant(Base):
    __tablename__ = "tenants"

    tenant_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    legal_name: Mapped[str | None] = mapped_column(sa.Text)
    gstin: Mapped[str | None] = mapped_column(sa.Text)
    pan: Mapped[str | None] = mapped_column(sa.Text)
    base_currency: Mapped[str] = mapped_column(
        sa.Text, nullable=False, server_default=sa.text("'INR'")
    )
    fiscal_year_start_month: Mapped[int] = mapped_column(
        sa.SmallInteger, nullable=False, server_default=sa.text("4")
    )  # April, India
    # auto_threshold, typed_confirm_paise, tolerance_pct, recheck_interval_days,
    # default_mdr_rates
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default=sa.text("'active'"))


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        sa.Index("ix_users_tenant", "tenant_id", postgresql_where=sa.text("status = 'active'")),
    )

    user_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("tenants.tenant_id"), nullable=False
    )
    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    display_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    role: Mapped[str] = mapped_column(sa.Text, nullable=False)  # owner|finance_manager|
    # finance_exec|auditor|viewer
    auth_subject: Mapped[str | None] = mapped_column(sa.Text)  # OIDC sub / SAML NameID
    last_seen_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default=sa.text("'active'"))


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (sa.Index("ix_runs_tenant_time", "tenant_id", sa.text("started_at DESC")),)

    run_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("tenants.tenant_id"), nullable=False
    )
    triggered_by: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("users.user_id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)  # queued|running|complete|failed
    ruleset_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)  # snapshot of active rules
    input_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # {source: sha256}
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # thresholds at run time
    period_start: Mapped[date | None] = mapped_column(sa.Date)
    period_end: Mapped[date | None] = mapped_column(sa.Date)
    record_count: Mapped[int | None] = mapped_column(sa.Integer)
    runtime_ms: Mapped[int | None] = mapped_column(sa.Integer)
    error: Mapped[str | None] = mapped_column(sa.Text)
    parent_run_id: Mapped[str | None] = mapped_column(
        sa.Text, sa.ForeignKey("runs.run_id")
    )  # replay lineage
    replay_reason: Mapped[str | None] = mapped_column(sa.Text)


class TransactionEventRow(Base):
    __tablename__ = "transaction_events"
    __table_args__ = (
        sa.CheckConstraint("amount_paise >= 0", name="ck_te_amount_nonneg"),
        sa.CheckConstraint("direction IN ('credit','debit')", name="ck_te_direction"),
        sa.UniqueConstraint("run_id", "source", "source_row_id", name="uq_te_run_source_row"),
        # §4.5. Declared here as well as created in the migration so that
        # `alembic check` and any future autogenerate see them as intended —
        # otherwise autogenerate proposes dropping ix_te_block, which is the
        # single most performance-relevant index in the system.
        sa.Index("ix_te_run_src", "run_id", "source"),
        sa.Index("ix_te_block", "run_id", "txn_date", sa.text("((amount_paise / 100000))")),
        sa.Index("ix_te_utr", "utr", postgresql_where=sa.text("utr IS NOT NULL")),
        sa.Index("ix_te_rrn", "rrn", postgresql_where=sa.text("rrn IS NOT NULL")),
        sa.Index("ix_te_order", "order_id", postgresql_where=sa.text("order_id IS NOT NULL")),
        sa.Index(
            "ix_te_settlement",
            "settlement_id",
            postgresql_where=sa.text("settlement_id IS NOT NULL"),
        ),
        # Scoped to the run, not the tenant (migration 0002). A voucher_guid is
        # unique within a Tally day book, not across every run a tenant will ever
        # do — PRD §Idempotency names (run_id, source, source_row_id) as the
        # mechanism, and source_row_id *is* the voucher_guid for Tally. Widening
        # this back to tenant_id is what made every re-upload a 500.
        sa.Index(
            "ix_te_guid",
            "run_id",
            "voucher_guid",
            unique=True,
            postgresql_where=sa.text("voucher_guid IS NOT NULL"),
        ),
        sa.Index(
            "ix_te_vec",
            "narration_vec",
            postgresql_using="hnsw",
            postgresql_ops={"narration_vec": "vector_cosine_ops"},
        ),
    )

    event_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("tenants.tenant_id"), nullable=False
    )
    source: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_row_id: Mapped[str] = mapped_column(sa.Text, nullable=False)

    amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    direction: Mapped[str] = mapped_column(sa.Text, nullable=False)
    currency: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default=sa.text("'INR'"))

    txn_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    value_date: Mapped[date | None] = mapped_column(sa.Date)
    settled_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    utr: Mapped[str | None] = mapped_column(sa.Text)
    rrn: Mapped[str | None] = mapped_column(sa.Text)
    settlement_id: Mapped[str | None] = mapped_column(sa.Text)
    order_id: Mapped[str | None] = mapped_column(sa.Text)
    payment_id: Mapped[str | None] = mapped_column(sa.Text)
    voucher_number: Mapped[str | None] = mapped_column(sa.Text)
    voucher_guid: Mapped[str | None] = mapped_column(sa.Text)

    counterparty: Mapped[str | None] = mapped_column(sa.Text)
    counterparty_norm: Mapped[str | None] = mapped_column(sa.Text)
    method: Mapped[str | None] = mapped_column(sa.Text)
    rail: Mapped[str | None] = mapped_column(sa.Text)
    txn_type: Mapped[str | None] = mapped_column(sa.Text)
    raw_narration: Mapped[str | None] = mapped_column(sa.Text)
    # pgvector, nullable. CUT from the build per §0.1; the column and its HNSW
    # index ship anyway so layering embeddings on later breaks nothing.
    narration_vec: Mapped[Any | None] = mapped_column(Vector(NARRATION_VEC_DIM))

    fee_paise: Mapped[int | None] = mapped_column(sa.BigInteger)
    tax_paise: Mapped[int | None] = mapped_column(sa.BigInteger)
    on_hold: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )

    ledger_account: Mapped[str | None] = mapped_column(sa.Text)
    voucher_type: Mapped[str | None] = mapped_column(sa.Text)

    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )

    gt_match_group: Mapped[str | None] = mapped_column(sa.Text)
    gt_label: Mapped[str | None] = mapped_column(sa.Text)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_matches_confidence"),
        sa.Index("ix_m_run", "run_id"),
        sa.Index("ix_m_stage", "run_id", "stage"),
    )

    match_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    group_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    event_ids: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False)
    # ['razorpay','bank'] or all three
    sources_covered: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False)
    # exact_ref|fee_adjusted|date_shift|many_to_one|fuzzy|rule
    stage: Mapped[str] = mapped_column(sa.Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(sa.Numeric(5, 4), nullable=False)
    residual_paise: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    rule_version_hash: Mapped[str | None] = mapped_column(sa.Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    auto_closed: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )


class Rule(Base):
    """One version of one rule. Active versions are immutable — see the
    ``rules_immutable()`` trigger in the initial migration (§4.3.6)."""

    __tablename__ = "rules"
    __table_args__ = (
        sa.Index(
            "ix_rules_active",
            "tenant_id",
            "status",
            "effective_from",
            sa.text("priority DESC"),
        ),
    )

    rule_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    version: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("tenants.tenant_id"), nullable=False
    )
    version_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str | None] = mapped_column(sa.Text)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    deductions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    tolerance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    priority: Mapped[int] = mapped_column(sa.Integer, nullable=False, server_default=sa.text("100"))
    effective_confidence: Mapped[Decimal] = mapped_column(
        sa.Numeric(5, 4), nullable=False, server_default=sa.text("0.95")
    )
    effective_from: Mapped[date] = mapped_column(sa.Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(sa.Date)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)  # draft|active|retired
    origin: Mapped[str] = mapped_column(sa.Text, nullable=False)  # manual|learned|imported
    created_by: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("users.user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )
    activated_by: Mapped[str | None] = mapped_column(sa.Text, sa.ForeignKey("users.user_id"))
    activated_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    backtest_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class ExceptionRow(Base):
    __tablename__ = "exceptions"
    __table_args__ = (
        sa.CheckConstraint("tier IN ('auto','monitor','escalate')", name="ck_exc_tier"),
        # The triage queue reads highest priority first; DESC is load-bearing.
        sa.Index("ix_exc_queue", "run_id", "status", sa.text("priority_score DESC")),
        sa.Index("ix_exc_sig", "tenant_id", "signature", "status"),
        sa.Index("ix_exc_recheck", "recheck_at", postgresql_where=sa.text("status = 'monitoring'")),
        sa.Index(
            "ix_exc_cluster", "cluster_id", postgresql_where=sa.text("cluster_id IS NOT NULL")
        ),
    )

    exception_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    event_ids: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), nullable=False)
    category: Mapped[str] = mapped_column(sa.Text, nullable=False)
    amount_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    residual_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(sa.Numeric(5, 4), nullable=False)
    tier: Mapped[str] = mapped_column(sa.Text, nullable=False)
    priority_score: Mapped[Decimal] = mapped_column(sa.Numeric(8, 4), nullable=False)
    cluster_id: Mapped[str | None] = mapped_column(sa.Text)
    rules_applied: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=_EMPTY_JSON_ARRAY
    )
    recommended_action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    consequence: Mapped[str | None] = mapped_column(sa.Text)
    deadline: Mapped[date | None] = mapped_column(sa.Date)
    recheck_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    recheck_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    # open|monitoring|resolved|written_off|snoozed|escalated
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default=sa.text("'open'"))
    resolved_by: Mapped[str | None] = mapped_column(sa.Text)  # system|rule|recheck|human
    resolved_by_user: Mapped[str | None] = mapped_column(sa.Text, sa.ForeignKey("users.user_id"))
    resolved_via: Mapped[str | None] = mapped_column(sa.Text)  # verbatim human instruction
    resolution_reason: Mapped[str | None] = mapped_column(sa.Text)
    resolution_category: Mapped[str | None] = mapped_column(sa.Text)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    signature: Mapped[str] = mapped_column(sa.Text, nullable=False)  # shape hash for 3x learning
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )


class Cluster(Base):
    __tablename__ = "clusters"

    cluster_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    root_cause: Mapped[str] = mapped_column(sa.Text, nullable=False)
    label: Mapped[str] = mapped_column(sa.Text, nullable=False)  # LLM-written, cosmetic
    grouping_key: Mapped[str] = mapped_column(sa.Text, nullable=False)  # the deterministic key
    member_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    total_paise: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    max_tier: Mapped[str] = mapped_column(sa.Text, nullable=False)
    suggested_fix: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )


class AuditEvent(Base):
    """Append-only hash chain. UPDATE and DELETE are revoked in the migration."""

    __tablename__ = "audit_events"
    __table_args__ = (sa.Index("ix_audit_subject", "subject_type", "subject_id", "seq"),)

    seq: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(sa.Text)
    actor: Mapped[str] = mapped_column(sa.Text, nullable=False)  # system|scheduler|user:<user_id>
    action: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # event|match|exception|rule|cluster|run
    subject_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    subject_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ruleset_hash: Mapped[str | None] = mapped_column(sa.Text)
    prev_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    this_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )


class CounterpartyAlias(Base):
    """Only ``origin='confirmed'`` aliases participate in matching (§4.3.10)."""

    __tablename__ = "counterparty_aliases"

    tenant_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("tenants.tenant_id"), primary_key=True
    )
    alias: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    canonical: Mapped[str] = mapped_column(sa.Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(sa.Numeric(5, 4))
    origin: Mapped[str] = mapped_column(sa.Text, nullable=False)  # manual|embedding|confirmed
    confirmed_by: Mapped[str | None] = mapped_column(sa.Text, sa.ForeignKey("users.user_id"))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )


class LLMCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (sa.Index("ix_llm_run", "run_id", "purpose"),)

    call_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(sa.Text)
    run_id: Mapped[str | None] = mapped_column(sa.Text)
    purpose: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False)
    model: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tier: Mapped[str] = mapped_column(sa.Text, nullable=False)  # light|standard|deep
    ladder_position: Mapped[int] = mapped_column(sa.Integer, nullable=False)  # 0 = first choice
    prompt_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    cached: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(sa.Integer)
    output_tokens: Mapped[int | None] = mapped_column(sa.Integer)
    thinking_tokens: Mapped[int | None] = mapped_column(sa.Integer)
    latency_ms: Mapped[int | None] = mapped_column(sa.Integer)
    # ok|rate_limited|timeout|schema_fail|down
    outcome: Mapped[str] = mapped_column(sa.Text, nullable=False)
    verified: Mapped[bool | None] = mapped_column(sa.Boolean)  # did the deterministic check pass
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )


class EvalResult(Base):
    __tablename__ = "eval_results"

    run_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    true_positive: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    false_positive: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    true_negative: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    false_negative: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    precision_pct: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 3))
    recall_pct: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 3))
    f1: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 3))
    abstention_pct: Mapped[Decimal | None] = mapped_column(sa.Numeric(6, 3))
    false_auto_resolutions: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    auto_threshold: Mapped[Decimal] = mapped_column(sa.Numeric(5, 4), nullable=False)
    coverage_curve: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    by_category: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    by_stage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    #: §12.5 GateResult list — {name, passed, actual, threshold} — added
    #: 31 Aug 2026 (migration 0003) for the Evaluation screen's PASS/FAIL cards.
    gates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    #: EvalReport.failures — the honest "what we got wrong" list, added
    #: alongside gates in the same migration.
    failures: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=_NOW
    )
