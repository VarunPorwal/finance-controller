"""The one place a router appends to the hash chain — PRD Prompt 8 BUILD §1.

Every router that logs an audit event goes through :func:`append_audit`
rather than hand-rolling the read-prev-hash-then-insert sequence, so the
chain is built the same way everywhere: read the tenant's latest
``this_hash`` (or :data:`~fc.audit.ledger.GENESIS_HASH` for its first event),
hand it to :func:`fc.audit.ledger.append`, insert the row it returns.

Reading the previous hash and inserting the new row happen inside the
caller's own transaction (the session passed in), so a request that fails
after this call rolls its audit event back along with everything else —
an event is only durable once the request that produced it actually commits,
which is correct: an audit trail for a write that never happened would be
worse than no audit trail.

**Known gap, not silently papered over**: the read-prev-hash-then-insert
sequence is not itself serialized. Two requests against the same tenant
committing concurrently can both read the same "latest" ``this_hash`` and
each insert a row pointing at it, which ``verify_chain`` would then report as
a broken link even though nothing was tampered with. A single Postgres
advisory lock per tenant (``pg_advisory_xact_lock``) around this function
would close it; it is not implemented because Prompt 8's demo scope has no
concurrent-writer scenario, and this is exactly the kind of thing to fix
before this ships past a single-request-at-a-time demo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditEvent
from fc.audit.ledger import GENESIS_HASH, append

__all__ = ["append_audit"]


async def append_audit(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    payload: dict[str, Any],
    created_at: datetime,
    run_id: str | None = None,
    ruleset_hash: str | None = None,
) -> AuditEvent:
    prev_hash = await session.scalar(
        select(AuditEvent.this_hash)
        .where(AuditEvent.tenant_id == tenant_id)
        .order_by(AuditEvent.seq.desc())
        .limit(1)
    )
    event = append(
        prev_hash=prev_hash or GENESIS_HASH,
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
        created_at=created_at,
        run_id=run_id,
        ruleset_hash=ruleset_hash,
    )
    row = AuditEvent(
        tenant_id=event.tenant_id,
        run_id=event.run_id,
        actor=event.actor,
        action=event.action,
        subject_type=event.subject_type,
        subject_id=event.subject_id,
        payload=event.payload,
        ruleset_hash=event.ruleset_hash,
        prev_hash=event.prev_hash,
        this_hash=event.this_hash,
        created_at=event.created_at,
    )
    session.add(row)
    await session.flush()
    return row
