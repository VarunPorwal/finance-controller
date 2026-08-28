"""ULID generation. Sortable by creation time, 26 Crockford-base32 characters.

``new_ulid`` takes an injectable clock and randomness source so that a seeded
generator run produces byte-identical identifiers, which is what the
determinism quality gate ("same seed + same ruleset -> byte-identical output")
requires. The default path uses the wall clock and ``secrets``; decision logic
must never call it (CLAUDE.md: no wall-clock in logic).
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from random import Random

__all__ = ["ULID_LENGTH", "deterministic_factory", "new_ulid"]

# Crockford base32: no I, L, O or U.
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ULID_LENGTH = 26
_TIMESTAMP_BITS = 48
_RANDOM_BYTES = 10
_MAX_TIMESTAMP_MS = (1 << _TIMESTAMP_BITS) - 1


def new_ulid(
    prefix: str = "",
    *,
    clock: Callable[[], int] | None = None,
    rand: Callable[[int], bytes] | None = None,
) -> str:
    """Return a ULID, optionally prefixed (``new_ulid("run_")``).

    ``clock`` returns milliseconds since the Unix epoch; ``rand`` returns n
    random bytes. Supply both for a reproducible stream.
    """
    timestamp_ms = clock() if clock is not None else time.time_ns() // 1_000_000
    if not 0 <= timestamp_ms <= _MAX_TIMESTAMP_MS:
        raise ValueError(f"timestamp out of ULID range: {timestamp_ms}")
    entropy = rand(_RANDOM_BYTES) if rand is not None else secrets.token_bytes(_RANDOM_BYTES)
    if len(entropy) != _RANDOM_BYTES:
        raise ValueError(f"rand() must return {_RANDOM_BYTES} bytes, got {len(entropy)}")
    value = (timestamp_ms << (_RANDOM_BYTES * 8)) | int.from_bytes(entropy, "big")
    return prefix + _encode(value, ULID_LENGTH)


def deterministic_factory(seed: int, epoch_ms: int) -> Callable[[str], str]:
    """Build a reproducible ULID factory for the synthetic generator and replay.

    Successive calls advance the embedded timestamp by one millisecond, so the
    identifiers stay sortable while remaining a pure function of ``seed`` and
    ``epoch_ms``.
    """
    rng = Random(seed)
    counter = 0

    def issue(prefix: str = "") -> str:
        nonlocal counter
        stamp = epoch_ms + counter
        counter += 1
        return new_ulid(prefix, clock=lambda: stamp, rand=rng.randbytes)

    return issue


def _encode(value: int, length: int) -> str:
    out = [""] * length
    for position in range(length - 1, -1, -1):
        out[position] = _ALPHABET[value & 0x1F]
        value >>= 5
    return "".join(out)
