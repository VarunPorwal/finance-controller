"""Blocking — PRD §6.2.

Cuts the pairwise comparison space before the amount-sensitive cascade stages
run. Every event emits 21 keys: three amount buckets by seven days.

The ``b-1``/``b+1`` spill is load-bearing. A fee deduction moves a settlement's
net across a bucket boundary, so without the spill the gateway row and the bank
credit land in different blocks and are never compared. Do not remove it.

This module also owns the reference-prefix machinery, because two callers need
it: the oversized-block guard here, and the unique-completion test that
``stages/date_shift.py`` uses to decide whether a partial reference is
discriminating at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from fc.config import Config
from fc.models.transaction import TransactionEvent

__all__ = [
    "AMOUNT_BUCKET_PAISE",
    "DAY_WINDOW",
    "REFERENCE_LADDER",
    "BlockIndex",
    "BlockKey",
    "BlockingStats",
    "PrefixIndex",
    "ShardedKey",
    "block_key",
    "build_blocks",
    "candidate_pairs",
    "reference_values",
]

#: Rupees 1,000 buckets (PRD §6.2).
AMOUNT_BUCKET_PAISE = 100_000

#: T +/- 3 days.
DAY_WINDOW = 3

#: Prefix length the oversized-block guard starts at, and the longest it will
#: grow to before giving up (references are 16-26 characters).
_SHARD_PREFIX_LEN = 4
_MAX_SHARD_PREFIX_LEN = 28

#: The reference ladder, most to least reliable (``TransactionEvent`` docstring).
REFERENCE_LADDER = ("utr", "rrn", "settlement_id", "order_id", "payment_id")

#: Base key: (amount bucket, date ordinal). A sharded key adds a reference prefix.
BlockKey = tuple[int, int]
ShardedKey = tuple[int, int, str]


def block_key(event: TransactionEvent) -> tuple[BlockKey, ...]:
    """The 21 keys one event blocks under - PRD §6.2 verbatim.

    Buckets ``(b-1, b, b+1)`` by days ``d-3 .. d+3``, where the day comes from
    :attr:`TransactionEvent.effective_date` (``value_date or txn_date``).
    """
    bucket = event.amount_paise // AMOUNT_BUCKET_PAISE
    day = event.effective_date.toordinal()
    return tuple(
        (b, d)
        for b in (bucket - 1, bucket, bucket + 1)
        for d in range(day - DAY_WINDOW, day + DAY_WINDOW + 1)
    )


def reference_values(event: TransactionEvent) -> tuple[str, ...]:
    """Every non-empty reference on an event, in ladder order."""
    return tuple(
        value
        for value in (getattr(event, field) for field in REFERENCE_LADDER)
        if isinstance(value, str) and value
    )


class PrefixIndex:
    """Answers "does this partial reference have exactly one completion?".

    A truncated UTR is only usable as evidence when it identifies one full
    reference. On a real corpus it usually does not: every UTR a bank issues in
    one month shares a long prefix, so an eight-character fragment can have a
    dozen completions. Matching on it would invent a match. Requiring
    uniqueness makes the ambiguous case abstain, which is a correct outcome
    (CLAUDE.md hard rule 4), not a missed one.
    """

    __slots__ = ("_values",)

    def __init__(self, values: Iterable[str]) -> None:
        self._values: tuple[str, ...] = tuple(sorted({v for v in values if v}))

    def completions(self, partial: str, *, limit: int = 2) -> tuple[str, ...]:
        """Distinct indexed values that strictly extend ``partial``, up to ``limit``.

        A value equal to ``partial`` is the fragment itself, not a completion of
        it, so it does not count towards ambiguity.
        """
        if not partial:
            return ()
        found: list[str] = []
        for value in self._values:
            if value != partial and value.startswith(partial):
                found.append(value)
                if len(found) >= limit:
                    break
        return tuple(found)

    def unique_completion(self, partial: str) -> str | None:
        """The single value ``partial`` extends to, or ``None`` if none or several do."""
        found = self.completions(partial, limit=2)
        return found[0] if len(found) == 1 else None


@dataclass(frozen=True)
class BlockingStats:
    """The reduction, measured. This number goes in the demo."""

    events: int
    naive_comparisons: int  # every unordered pair of distinct events
    naive_cross_source: int  # unordered pairs that span two sources
    candidate_pairs: int
    reduction_ratio: Decimal  # naive_cross_source / candidate_pairs
    blocks: int
    oversize_blocks: int  # exceeded cfg.max_bucket_size before sharding
    sub_bucketed_keys: int  # shards produced by the guard
    oversize_after_shard: int  # shards still over the cap; sharding is one level
    largest_block: int


@dataclass(frozen=True)
class BlockIndex:
    """Event ids grouped by sharded block key, plus the measured reduction."""

    blocks: Mapping[ShardedKey, tuple[str, ...]]
    stats: BlockingStats


def build_blocks(events: Sequence[TransactionEvent], *, cfg: Config) -> BlockIndex:
    """Group events into blocks, applying the §6.2 oversized-block guard.

    Guard: a block over ``cfg.max_bucket_size`` (200) is sub-bucketed by a
    reference prefix. Without it a corpus with many identical amounts collapses
    into one block and the cascade degenerates to O(n^2).
    """
    by_source: dict[str, int] = {}
    raw: dict[BlockKey, list[str]] = {}
    by_id: dict[str, TransactionEvent] = {}
    for event in events:
        by_id[event.event_id] = event
        by_source[event.source] = by_source.get(event.source, 0) + 1
        for key in block_key(event):
            raw.setdefault(key, []).append(event.event_id)

    blocks: dict[ShardedKey, tuple[str, ...]] = {}
    oversize = 0
    sharded = 0
    oversize_after_shard = 0
    for key, members in raw.items():
        if len(members) <= cfg.max_bucket_size:
            blocks[(key[0], key[1], "")] = tuple(sorted(members))
            continue
        oversize += 1
        shards = _shard(members, by_id, cfg.max_bucket_size)
        sharded += len(shards)
        for shard, shard_members in shards.items():
            if len(shard_members) > cfg.max_bucket_size:
                oversize_after_shard += 1
            blocks[(key[0], key[1], shard)] = tuple(sorted(shard_members))

    pairs = _distinct_pairs(blocks, by_id)
    n = len(by_id)
    cross = _cross_source_pairs(by_source)
    ratio = (
        (Decimal(cross) / Decimal(len(pairs))).quantize(Decimal("0.01")) if pairs else Decimal(0)
    )

    return BlockIndex(
        blocks=blocks,
        stats=BlockingStats(
            events=n,
            naive_comparisons=n * (n - 1) // 2,
            naive_cross_source=cross,
            candidate_pairs=len(pairs),
            reduction_ratio=ratio,
            blocks=len(blocks),
            oversize_blocks=oversize,
            sub_bucketed_keys=sharded,
            oversize_after_shard=oversize_after_shard,
            largest_block=max((len(m) for m in blocks.values()), default=0),
        ),
    )


def candidate_pairs(
    index: BlockIndex, by_id: Mapping[str, TransactionEvent]
) -> Iterator[tuple[str, str]]:
    """Deduplicated cross-source event-id pairs, in sorted order.

    Sorted because "same seed -> byte-identical output" (CLAUDE.md hard rule 9)
    forbids letting dict iteration order reach a match.
    """
    yield from _distinct_pairs(index.blocks, by_id)


def _distinct_pairs(
    blocks: Mapping[ShardedKey, tuple[str, ...]], by_id: Mapping[str, TransactionEvent]
) -> tuple[tuple[str, str], ...]:
    seen: set[tuple[str, str]] = set()
    for block in blocks.values():
        # A later cascade stage passes only the events still unclaimed, so the
        # index legitimately names ids it no longer cares about. Blocking is
        # computed once over the whole corpus; filtering here is cheaper and
        # keeps the reported reduction measured against the full input.
        members = [event_id for event_id in block if event_id in by_id]
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                if by_id[left].source == by_id[right].source:
                    continue
                seen.add((left, right) if left < right else (right, left))
    return tuple(sorted(seen))


def _shard(
    members: Sequence[str], by_id: Mapping[str, TransactionEvent], max_size: int
) -> dict[str, tuple[str, ...]]:
    """Sub-bucket an oversized block by reference prefix, lengthening as needed.

    A fixed prefix length does not work on real references. An RBI UTR is
    ``bank + year + day-of-year + sequence``, so every UTR one bank issues in a
    month shares its first eight characters: a four-character shard would put
    the whole block back in one shard and the guard would do nothing while
    appearing to work. So the prefix grows until the shards are bounded.

    Events carrying the *same* reference are never separated, and no prefix
    length can separate them. That residual is irreducible and correct - rows
    quoting one reference are exactly the rows that should be compared - and it
    is counted as ``oversize_after_shard`` rather than hidden.
    """
    shards = {"": tuple(members)}
    for length in range(_SHARD_PREFIX_LEN, _MAX_SHARD_PREFIX_LEN + 1, _SHARD_PREFIX_LEN):
        oversized = {k: v for k, v in shards.items() if len(v) > max_size}
        if not oversized:
            break
        for key in oversized:
            split: dict[str, list[str]] = {}
            for event_id in shards.pop(key):
                refs = reference_values(by_id[event_id])
                split.setdefault(refs[0][:length] if refs else "", []).append(event_id)
            if len(split) == 1:
                # No progress at this length; keep the block and try a longer one.
                shards[next(iter(split))] = tuple(next(iter(split.values())))
                continue
            for shard, shard_members in split.items():
                shards[shard] = tuple(shard_members)
    return shards


def _cross_source_pairs(by_source: Mapping[str, int]) -> int:
    counts = sorted(by_source.items())
    return sum(a[1] * b[1] for i, a in enumerate(counts) for b in counts[i + 1 :])
