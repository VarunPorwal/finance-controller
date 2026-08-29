"""PRD §5.8. Split and merge are cut per §0.1 ("No demo moment") — this
router implements list, members and apply only.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit_log import append_audit
from api.converters import cluster_from_row, exception_from_row
from api.deps import AuthenticatedUser, current_user, db_session, finish
from api.errors import ApiError
from api.pagination import DEFAULT_LIMIT, MAX_LIMIT, Page, decode_cursor, encode_cursor
from db.models import Cluster as ClusterRow
from db.models import ExceptionRow
from fc.models.exception_ import Cluster, Exception_

router = APIRouter(prefix="/clusters", tags=["clusters"])

_RESOLVABLE_FROM = frozenset({"open", "monitoring", "snoozed", "escalated"})


class ClusterMembersOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster: Cluster
    exceptions: list[Exception_]


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class ApplyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster: Cluster
    resolved_exception_ids: list[str]
    skipped_exception_ids: list[str]


@router.get("", response_model=Page[Cluster])
async def list_clusters(
    run_id: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, le=MAX_LIMIT, gt=0),
    cursor: str | None = None,
    session: AsyncSession = Depends(db_session),
) -> Page[Cluster]:
    stmt = select(ClusterRow).order_by(ClusterRow.total_paise.desc(), ClusterRow.cluster_id.desc())
    if run_id is not None:
        stmt = stmt.where(ClusterRow.run_id == run_id)
    if cursor is not None:
        after_total, _, after_id = decode_cursor(cursor).partition("\0")
        stmt = stmt.where(
            (ClusterRow.total_paise < int(after_total))
            | ((ClusterRow.total_paise == int(after_total)) & (ClusterRow.cluster_id < after_id))
        )
    rows = (await session.scalars(stmt.limit(limit + 1))).all()
    items = [cluster_from_row(r) for r in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.total_paise}\0{last.cluster_id}")
    return Page(items=items, next_cursor=next_cursor)


async def _load(session: AsyncSession, cluster_id: str) -> ClusterRow:
    row = await session.get(ClusterRow, cluster_id)
    if row is None:
        raise ApiError(404, "not found", f"no cluster {cluster_id}")
    return row


@router.get("/{cluster_id}/members", response_model=ClusterMembersOut)
async def get_cluster_members(
    cluster_id: str, session: AsyncSession = Depends(db_session)
) -> ClusterMembersOut:
    cluster = await _load(session, cluster_id)
    members = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.cluster_id == cluster_id))
    ).all()
    return ClusterMembersOut(
        cluster=cluster_from_row(cluster), exceptions=[exception_from_row(m) for m in members]
    )


@router.post("/{cluster_id}/apply", response_model=ApplyOut)
async def apply_cluster(
    cluster_id: str,
    body: ApplyRequest,
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> ApplyOut:
    """Resolve every member this cluster's own root cause explains, in one
    human decision instead of one click per exception. Members already past
    the resolvable statuses (already resolved/written off) are skipped, not
    errored — applying a cluster to a queue a human has partly worked through
    already is the common case, not the exceptional one.
    """
    cluster = await _load(session, cluster_id)
    members = (
        await session.scalars(select(ExceptionRow).where(ExceptionRow.cluster_id == cluster_id))
    ).all()
    now = datetime.now(UTC)
    resolved: list[str] = []
    skipped: list[str] = []
    for member in members:
        if member.status not in _RESOLVABLE_FROM:
            skipped.append(member.exception_id)
            continue
        member.status = "resolved"
        member.resolved_by = "human"
        member.resolved_by_user = user.user_id
        member.resolved_via = body.reason
        member.resolution_reason = body.reason
        member.resolution_category = "cluster_applied"
        member.resolved_at = now
        resolved.append(member.exception_id)
    await session.flush()

    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="cluster.apply",
        subject_type="cluster",
        subject_id=cluster_id,
        payload={
            "root_cause": cluster.root_cause,
            "resolved_exception_ids": resolved,
            "skipped_exception_ids": skipped,
            "reason": body.reason,
            "dry_run": dry_run,
        },
        created_at=now,
        run_id=cluster.run_id,
    )
    result = ApplyOut(
        cluster=cluster_from_row(cluster),
        resolved_exception_ids=resolved,
        skipped_exception_ids=skipped,
    )
    await finish(session, dry_run=dry_run)
    return result
