"""PRD §5.4. Parses into an *existing* run (created via ``POST /runs``) rather
than an async job the frontend polls — see ``api/routers/runs.py``'s module
docstring for why: there is no job-status table in the frozen schema, and
CLAUDE.md forbids adding one after 28 Aug. ``job_id`` in the two GET routes
below is the ``run_id`` the ingest call was given; ``/rejections`` always
returns empty because a rejected row was never persisted anywhere to
re-fetch — the POST response itself is the one place rejections are visible,
same as every other adapter in this codebase already returns them inline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from api.audit_log import append_audit
from api.deps import AuthenticatedUser, current_user, db_session, finish
from api.errors import ApiError
from db.models import Run, TransactionEventRow
from fc.ingest.bank_csv import parse_bank_csv
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.ingest.razorpay import parse_razorpay_recon
from fc.ingest.tally import parse_tally_csv
from fc.ingest.validators import Rejection
from fc.models.ids import deterministic_factory
from fc.models.transaction import TransactionEvent

router = APIRouter(prefix="/ingest", tags=["ingest"])


class RejectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_row_id: str | None
    reason: str
    field_count: int


class IngestOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    event_count: int
    rejections: list[RejectionOut]


class IngestStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    record_count: int | None


class RejectionsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    rejections: list[RejectionOut]


def _rejection_out(r: Rejection) -> RejectionOut:
    return RejectionOut(source_row_id=r.source_row_id, reason=r.reason, field_count=len(r.fields))


async def _load_open_run(session: AsyncSession, run_id: str) -> Run:
    row = await session.get(Run, run_id)
    if row is None:
        raise ApiError(404, "not found", f"no run {run_id}")
    if row.status not in ("queued", "running"):
        raise ApiError(
            409, "invalid state", f"run {run_id} is {row.status!r}, not open for ingestion"
        )
    return row


async def _persist(
    session: AsyncSession, *, run: Run, tenant_id: str, events: tuple[TransactionEvent, ...]
) -> None:
    for event in events:
        session.add(
            TransactionEventRow(
                event_id=event.event_id,
                run_id=run.run_id,
                tenant_id=tenant_id,
                source=event.source,
                source_row_id=event.source_row_id,
                amount_paise=event.amount_paise,
                direction=event.direction,
                currency=event.currency,
                txn_date=event.txn_date,
                value_date=event.value_date,
                settled_at=event.settled_at,
                utr=event.utr,
                rrn=event.rrn,
                settlement_id=event.settlement_id,
                order_id=event.order_id,
                payment_id=event.payment_id,
                voucher_number=event.voucher_number,
                voucher_guid=event.voucher_guid,
                counterparty=event.counterparty,
                counterparty_norm=event.counterparty_norm,
                method=event.method,
                rail=event.rail,
                txn_type=event.txn_type,
                raw_narration=event.raw_narration,
                fee_paise=event.fee_paise,
                tax_paise=event.tax_paise,
                on_hold=event.on_hold,
                ledger_account=event.ledger_account,
                voucher_type=event.voucher_type,
                raw=event.raw,
                ingested_at=event.ingested_at,
            )
        )
    run.record_count = (run.record_count or 0) + len(events)
    await session.flush()


@router.post("/razorpay", response_model=IngestOut)
async def ingest_razorpay(
    file: UploadFile,
    run_id: str = Query(...),
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> IngestOut:
    run = await _load_open_run(session, run_id)
    raw = json.loads((await file.read()).decode("utf-8"))
    now = datetime.now(UTC)
    issue_id = deterministic_factory(seed=1, epoch_ms=int(now.timestamp() * 1000))
    result = parse_razorpay_recon(
        raw, run_id=run_id, tenant_id=user.tenant_id, issue_id=issue_id, ingested_at=now
    )
    await _persist(session, run=run, tenant_id=user.tenant_id, events=result.events)
    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="ingest.razorpay",
        subject_type="run",
        subject_id=run_id,
        payload={
            "event_count": len(result.events),
            "rejection_count": len(result.rejections),
            "dry_run": dry_run,
        },
        created_at=now,
        run_id=run_id,
    )
    await finish(session, dry_run=dry_run)
    return IngestOut(
        run_id=run_id,
        event_count=len(result.events),
        rejections=[_rejection_out(r) for r in result.rejections],
    )


@router.post("/bank", response_model=IngestOut)
async def ingest_bank(
    file: UploadFile,
    run_id: str = Query(...),
    opening_balance_paise: int = Query(...),
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> IngestOut:
    run = await _load_open_run(session, run_id)
    content = (await file.read()).decode("utf-8")
    now = datetime.now(UTC)
    issue_id = deterministic_factory(seed=2, epoch_ms=int(now.timestamp() * 1000))
    bank_result = parse_bank_csv(
        content,
        run_id=run_id,
        tenant_id=user.tenant_id,
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=opening_balance_paise,
        issue_id=issue_id,
        ingested_at=now,
    )
    result = bank_result.ingest
    await _persist(session, run=run, tenant_id=user.tenant_id, events=result.events)
    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="ingest.bank",
        subject_type="run",
        subject_id=run_id,
        payload={
            "event_count": len(result.events),
            "rejection_count": len(result.rejections),
            "balanced": bank_result.balanced,
            "dry_run": dry_run,
        },
        created_at=now,
        run_id=run_id,
    )
    await finish(session, dry_run=dry_run)
    return IngestOut(
        run_id=run_id,
        event_count=len(result.events),
        rejections=[_rejection_out(r) for r in result.rejections],
    )


@router.post("/ledger", response_model=IngestOut)
async def ingest_ledger(
    file: UploadFile,
    run_id: str = Query(...),
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> IngestOut:
    run = await _load_open_run(session, run_id)
    content = (await file.read()).decode("utf-8")
    now = datetime.now(UTC)
    issue_id = deterministic_factory(seed=3, epoch_ms=int(now.timestamp() * 1000))
    result = parse_tally_csv(
        content, run_id=run_id, tenant_id=user.tenant_id, issue_id=issue_id, ingested_at=now
    )
    await _persist(session, run=run, tenant_id=user.tenant_id, events=result.events)
    await append_audit(
        session,
        tenant_id=user.tenant_id,
        actor=f"user:{user.user_id}",
        action="ingest.ledger",
        subject_type="run",
        subject_id=run_id,
        payload={
            "event_count": len(result.events),
            "rejection_count": len(result.rejections),
            "dry_run": dry_run,
        },
        created_at=now,
        run_id=run_id,
    )
    await finish(session, dry_run=dry_run)
    return IngestOut(
        run_id=run_id,
        event_count=len(result.events),
        rejections=[_rejection_out(r) for r in result.rejections],
    )


@router.post("/upload", response_model=IngestOut)
async def ingest_upload(
    file: UploadFile,
    source: str = Query(..., pattern="^(razorpay|bank|ledger)$"),
    run_id: str = Query(...),
    opening_balance_paise: int = Query(0),
    dry_run: bool = Query(False),
    session: AsyncSession = Depends(db_session),
    user: AuthenticatedUser = Depends(current_user),
) -> IngestOut:
    """The generic upload PRD §5.4 names, dispatched to the same source-specific
    parsers as the three endpoints above."""
    if source == "razorpay":
        return await ingest_razorpay(
            file, run_id=run_id, dry_run=dry_run, session=session, user=user
        )
    if source == "bank":
        return await ingest_bank(
            file,
            run_id=run_id,
            opening_balance_paise=opening_balance_paise,
            dry_run=dry_run,
            session=session,
            user=user,
        )
    return await ingest_ledger(file, run_id=run_id, dry_run=dry_run, session=session, user=user)


@router.get("/{job_id}/status", response_model=IngestStatusOut)
async def ingest_status(
    job_id: str, session: AsyncSession = Depends(db_session)
) -> IngestStatusOut:
    row = await session.get(Run, job_id)
    if row is None:
        raise ApiError(404, "not found", f"no run {job_id}")
    return IngestStatusOut(job_id=job_id, status=row.status, record_count=row.record_count)


@router.get("/{job_id}/rejections", response_model=RejectionsOut)
async def ingest_rejections(
    job_id: str, session: AsyncSession = Depends(db_session)
) -> RejectionsOut:
    row = await session.get(Run, job_id)
    if row is None:
        raise ApiError(404, "not found", f"no run {job_id}")
    return RejectionsOut(job_id=job_id, rejections=[])
