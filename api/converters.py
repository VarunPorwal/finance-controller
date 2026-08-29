"""SQLAlchemy row -> engine Pydantic model, one direction only.

Routers serialise with FastAPI's ``response_model``, and every response model
in this API is a Pydantic model (never a bare dict — a dict response
round-trips through ``/openapi.json`` as ``any``, which is exactly what
Prompt 10's generated TypeScript client is supposed to prevent). Where the
engine already has the right Pydantic model (``TransactionEvent``,
``MatchResult``, ``Exception_``, ``Cluster``, ``Rule``), routers reuse it
directly rather than defining a parallel API-only DTO; these functions are
the seam between a database row and that model.
"""

from __future__ import annotations

from db.models import Cluster as ClusterRow
from db.models import ExceptionRow, TransactionEventRow
from db.models import Match as MatchRow
from db.models import Rule as RuleRow
from fc.models.exception_ import Cluster, Exception_, RuleApplicationRef
from fc.models.match import MatchEvidence, MatchResult
from fc.models.rule import Deduction, Rule, Scope, Tolerance
from fc.models.transaction import TransactionEvent

__all__ = [
    "cluster_from_row",
    "event_from_row",
    "exception_from_row",
    "match_from_row",
    "rule_from_row",
]


def event_from_row(row: TransactionEventRow) -> TransactionEvent:
    return TransactionEvent(
        event_id=row.event_id,
        run_id=row.run_id,
        tenant_id=row.tenant_id,
        source=row.source,  # type: ignore[arg-type]
        source_row_id=row.source_row_id,
        amount_paise=row.amount_paise,
        direction=row.direction,  # type: ignore[arg-type]
        currency=row.currency,
        txn_date=row.txn_date,
        value_date=row.value_date,
        settled_at=row.settled_at,
        utr=row.utr,
        rrn=row.rrn,
        settlement_id=row.settlement_id,
        order_id=row.order_id,
        payment_id=row.payment_id,
        voucher_number=row.voucher_number,
        voucher_guid=row.voucher_guid,
        counterparty=row.counterparty,
        counterparty_norm=row.counterparty_norm,
        method=row.method,
        rail=row.rail,
        txn_type=row.txn_type,
        raw_narration=row.raw_narration,
        fee_paise=row.fee_paise,
        tax_paise=row.tax_paise,
        on_hold=row.on_hold,
        ledger_account=row.ledger_account,
        voucher_type=row.voucher_type,
        raw=row.raw,
        ingested_at=row.ingested_at,
        gt_match_group=row.gt_match_group,
        gt_label=row.gt_label,
    )


def match_from_row(row: MatchRow) -> MatchResult:
    return MatchResult(
        match_id=row.match_id,
        run_id=row.run_id,
        tenant_id=row.tenant_id,
        group_key=row.group_key,
        event_ids=list(row.event_ids),
        sources_covered=list(row.sources_covered),  # type: ignore[arg-type]
        stage=row.stage,  # type: ignore[arg-type]
        confidence=row.confidence,
        residual_paise=row.residual_paise,
        rule_version_hash=row.rule_version_hash,
        evidence=[MatchEvidence.model_validate(leg) for leg in row.evidence],
        auto_closed=row.auto_closed,
        created_at=row.created_at,
    )


def exception_from_row(row: ExceptionRow) -> Exception_:
    return Exception_(
        exception_id=row.exception_id,
        run_id=row.run_id,
        tenant_id=row.tenant_id,
        event_ids=list(row.event_ids),
        category=row.category,  # type: ignore[arg-type]
        amount_paise=row.amount_paise,
        residual_paise=row.residual_paise,
        confidence=row.confidence,
        tier=row.tier,  # type: ignore[arg-type]
        priority_score=row.priority_score,
        cluster_id=row.cluster_id,
        rules_applied=[RuleApplicationRef.model_validate(r) for r in row.rules_applied],
        recommended_action=row.recommended_action,
        consequence=row.consequence,
        deadline=row.deadline,
        recheck_at=row.recheck_at,
        recheck_count=row.recheck_count,
        status=row.status,  # type: ignore[arg-type]
        resolved_by=row.resolved_by,  # type: ignore[arg-type]
        resolved_by_user=row.resolved_by_user,
        resolved_via=row.resolved_via,
        resolution_reason=row.resolution_reason,
        resolution_category=row.resolution_category,
        resolved_at=row.resolved_at,
        signature=row.signature,
        created_at=row.created_at,
    )


def cluster_from_row(row: ClusterRow) -> Cluster:
    return Cluster(
        cluster_id=row.cluster_id,
        run_id=row.run_id,
        tenant_id=row.tenant_id,
        root_cause=row.root_cause,
        label=row.label,
        grouping_key=row.grouping_key,
        member_count=row.member_count,
        total_paise=row.total_paise,
        max_tier=row.max_tier,  # type: ignore[arg-type]
        suggested_fix=row.suggested_fix,
        created_at=row.created_at,
    )


def rule_from_row(row: RuleRow) -> Rule:
    return Rule(
        rule_id=row.rule_id,
        version=row.version,
        tenant_id=row.tenant_id,
        version_hash=row.version_hash,
        name=row.name,
        description=row.description,
        scope=Scope.model_validate(row.scope),
        deductions=[Deduction.model_validate(d) for d in row.deductions],
        tolerance=Tolerance.model_validate(row.tolerance),
        priority=row.priority,
        effective_confidence=row.effective_confidence,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        status=row.status,  # type: ignore[arg-type]
        origin=row.origin,  # type: ignore[arg-type]
        created_by=row.created_by,
        created_at=row.created_at,
        activated_by=row.activated_by,
        activated_at=row.activated_at,
        backtest_result=row.backtest_result,
    )
