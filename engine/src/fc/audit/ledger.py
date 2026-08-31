"""Append-only hash-chained audit ledger — pure domain logic.

Every fact this system claims ("we can explain every decision") is checkable
because it is logged here first: every ingestion, match, rule application,
tier assignment, human instruction, confirmation, recheck, rule activation
and LLM call. The chain is what turns that claim from an assertion into a
query — ``verify_chain`` either recomputes cleanly to the end or names the
exact ``seq`` where it stopped.

::

    this_hash = sha256(prev_hash + canonical_json(payload) + actor + action
                       + subject_id)

This module only computes hashes and builds records; it never touches a
database or a clock. ``engine/`` imports nothing from ``api/`` or ``db/``
(CLAUDE.md hard rule 6), so the actual INSERT and the actual ``seq`` a row
receives are the caller's concern — a repository in ``db/`` or a router in
``api/``, both of which import this module and never the reverse. ``append``
and ``append_batch`` take ``created_at`` as a parameter rather than reading
the wall clock, so a run's audit trail is reproducible from its inputs
(CLAUDE.md hard rule 9).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

__all__ = [
    "GENESIS_HASH",
    "HASH_MISMATCH",
    "SEQUENCE_GAP",
    "AuditEvent",
    "AuditEventInput",
    "append",
    "append_batch",
    "canonical_json",
    "compute_hash",
    "normalize_payload",
    "sequence_gaps",
    "verify_chain",
]

#: ``prev_hash`` for the first event a tenant's chain ever records.
GENESIS_HASH = "0" * 64


def _normalize(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        raise TypeError(
            "audit payload must not contain float values — money is int paise "
            "and everything else should be Decimal, str or int"
        )
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def normalize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The JSON-safe form of an audit payload: the one that is hashed *and* stored.

    ``Decimal`` becomes its exact string, ``datetime`` becomes ISO 8601, and a
    float anywhere in the structure is a bug upstream, not something to round.
    Hashing and persistence must both start from this same normalised value —
    a payload hashed as Python objects and stored as a slightly different JSON
    shape would make ``verify_chain`` fail on every row, not just tampered ones.
    """
    return dict(_normalize(dict(payload)))


def canonical_json(payload: Any) -> str:
    """Stable JSON encoding for hashing: sorted keys, no whitespace variance.

    Callers should pass an already-:func:`normalize_payload`-d value. This
    still refuses ``NaN``/``Infinity`` (``allow_nan=False``) as a last defence,
    since those serialise successfully but are not valid JSON and would make
    the hash unreproducible outside Python.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def compute_hash(*, prev_hash: str, payload: Any, actor: str, action: str, subject_id: str) -> str:
    """``sha256(prev_hash + canonical_json(payload) + actor + action + subject_id)``."""
    material = prev_hash + canonical_json(payload) + actor + action + subject_id
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditEvent(BaseModel):
    """One link in the chain, not yet assigned a ``seq`` — the database does that.

    Everything needed to persist the row and to re-verify it later is here:
    the caller inserts these fields directly and ``seq`` comes back from the
    ``BIGSERIAL`` primary key.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    run_id: str | None = None
    actor: str
    action: str
    subject_type: str
    subject_id: str
    payload: dict[str, Any]
    ruleset_hash: str | None = None
    prev_hash: str
    this_hash: str
    created_at: datetime


class AuditEventInput(BaseModel):
    """The fields a caller supplies for one entry of :func:`append_batch`.

    ``prev_hash`` is deliberately excluded — :func:`append_batch` derives it
    from the previous entry in the batch (or the caller's starting
    ``prev_hash`` for the first one), which is what keeps a batch's chain
    correct without the caller having to hash anything by hand.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    actor: str
    action: str
    subject_type: str
    subject_id: str
    payload: dict[str, Any]
    created_at: datetime
    run_id: str | None = None
    ruleset_hash: str | None = None


def append(
    *,
    prev_hash: str,
    tenant_id: str,
    actor: str,
    action: str,
    subject_type: str,
    subject_id: str,
    payload: Mapping[str, Any],
    created_at: datetime,
    run_id: str | None = None,
    ruleset_hash: str | None = None,
) -> AuditEvent:
    """Build the next link in the chain given the previous row's ``this_hash``.

    Pure: the same arguments always produce the same :class:`AuditEvent`,
    including ``this_hash``. Fetching the true ``prev_hash`` (the tenant's
    latest row, or :data:`GENESIS_HASH` if none exists yet) is the caller's
    responsibility, since that is a database read.
    """
    normalized = normalize_payload(payload)
    this_hash = compute_hash(
        prev_hash=prev_hash, payload=normalized, actor=actor, action=action, subject_id=subject_id
    )
    return AuditEvent(
        tenant_id=tenant_id,
        run_id=run_id,
        actor=actor,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=normalized,
        ruleset_hash=ruleset_hash,
        prev_hash=prev_hash,
        this_hash=this_hash,
        created_at=created_at,
    )


def append_batch(
    entries: Iterable[AuditEventInput | Mapping[str, Any]], *, prev_hash: str
) -> list[AuditEvent]:
    """Chain many entries into one contiguous run before a single batched INSERT.

    Each entry's ``this_hash`` becomes the next entry's ``prev_hash`` entirely
    in memory, so the chain is correct regardless of how the caller batches
    the eventual write — one INSERT for the whole run, or several.
    """
    events: list[AuditEvent] = []
    current_prev = prev_hash
    for entry in entries:
        fields = entry.model_dump() if isinstance(entry, AuditEventInput) else dict(entry)
        event = append(prev_hash=current_prev, **fields)
        events.append(event)
        current_prev = event.this_hash
    return events


#: The only way a chain can be invalid: some row's hash does not recompute, or
#: does not chain from its predecessor. A deletion presents as exactly this —
#: the surviving successor's ``prev_hash`` still points at the row that was
#: removed — which is why contiguity is not a second failure mode.
HASH_MISMATCH = "hash_mismatch"

#: Advisory label, **not** a verdict. ``seq`` comes from a ``BIGSERIAL``, and
#: PostgreSQL burns values on any rolled-back transaction, so a gap is the
#: normal state of a healthy chain rather than evidence of anything. Treating it
#: as invalidity made ``/audit/verify-chain`` answer ``valid: false`` for the
#: whole life of the deployment: the production chain has two gaps, of 47 and 74
#: numbers, and the hash link is intact across both.
SEQUENCE_GAP = "sequence_gap"


def sequence_gaps(events: Sequence[Mapping[str, Any]]) -> tuple[tuple[int, int], ...]:
    """Non-consecutive ``seq`` pairs in ``events``, as ``(after_seq, next_seq)``.

    Advisory only. A gap means one of two things and this function cannot tell
    them apart: a row was deleted, or PostgreSQL burned the number on a
    rolled-back transaction. :func:`verify_chain` *can* tell them apart — a
    deletion breaks the hash link and a burned number does not — so the verdict
    belongs there and this is context to report alongside it.
    """
    gaps: list[tuple[int, int]] = []
    prev_seq: int | None = None
    for row in events:
        seq = row["seq"]
        if prev_seq is not None and seq != prev_seq + 1:
            gaps.append((prev_seq, seq))
        prev_seq = seq
    return tuple(gaps)


def verify_chain(
    events: Sequence[Mapping[str, Any]], *, expected_prev_hash: str | None = None
) -> tuple[bool, int | None, str | None]:
    """Recompute the chain over ``events`` (ordered by ``seq`` ascending, the caller's job).

    Each row is a mapping with at least ``seq``, ``prev_hash``, ``this_hash``,
    ``payload``, ``actor``, ``action`` and ``subject_id`` — a dict, a decoded
    database row, whatever the caller's persistence layer hands back, as long
    as its ``payload`` is already the JSON-native value that was stored (no
    ``Decimal``, no float). The caller (typically a router that just fetched a
    range and passes it straight through) does not need to know any of the
    rules below — it gets back a verdict and, on failure, why.

    Returns ``(True, None, None)`` when every row's ``this_hash`` recomputes
    from its own fields and chains from its predecessor's ``this_hash``.
    Otherwise ``(False, seq, HASH_MISMATCH)`` naming the first row that fails:
    either its stored ``prev_hash`` does not equal the predecessor's
    ``this_hash``, or its own ``this_hash`` does not recompute from its fields.
    Both are the same underlying event — a field was altered, or a row that
    used to sit between them is gone — and are not worth distinguishing.

    **Contiguity is deliberately not checked.** ``seq`` is a ``BIGSERIAL`` and
    PostgreSQL burns values on any rolled-back transaction, so gaps occur in a
    perfectly healthy chain: the production ledger has two, of 47 and 74
    numbers, and the hash link is intact across both. Reporting that as
    ``valid: false`` is what made this endpoint answer "invalid" from the day it
    shipped, with ``checked: 0``, so the hashes it exists to verify were never
    verified at all.

    Nothing is lost by dropping it, because the hash chain already detects the
    case contiguity was there to catch, and detects it *better*. Delete a row
    and its successor's ``prev_hash`` still points at the deleted row, so the
    link breaks and :data:`HASH_MISMATCH` fires. Burn a sequence number and no
    link is disturbed. Contiguity could not tell those apart; the hash can.
    :func:`sequence_gaps` reports gaps separately, as context for a human.

    One case neither test catches: truncation. Delete the *most recent* rows
    and there is no successor whose link can break. Detecting that needs an
    anchor outside the table — a periodically published head hash — which this
    build does not have.

    ``expected_prev_hash`` verifies a sub-range against its true predecessor
    (the previous page's last ``this_hash``, or :data:`GENESIS_HASH` for a whole
    chain) instead of trusting the first row's own ``prev_hash``
    unconditionally. Passing :data:`GENESIS_HASH` for a full fetch is what
    catches deletion of the very first row.
    """
    prev_hash = expected_prev_hash
    for row in events:
        seq = row["seq"]
        if prev_hash is not None and row["prev_hash"] != prev_hash:
            return False, seq, HASH_MISMATCH
        recomputed = compute_hash(
            prev_hash=row["prev_hash"],
            payload=row["payload"],
            actor=row["actor"],
            action=row["action"],
            subject_id=row["subject_id"],
        )
        if recomputed != row["this_hash"]:
            return False, seq, HASH_MISMATCH
        prev_hash = row["this_hash"]
    return True, None, None
