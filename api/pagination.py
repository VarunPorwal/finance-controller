"""Cursor pagination — PRD §5.1: ``?limit=&cursor=``, response carries ``next_cursor``.

The cursor is opaque to the client by convention (base64), but it is not a
security boundary — it is the last row's own sort key, which a client with
list access could already see. Every listing endpoint sorts by a single
monotonic column (usually ``seq`` or a ULID, both already totally ordered),
so "the next page starts after this value" is the entire cursor.
"""

from __future__ import annotations

import base64

from pydantic import BaseModel, ConfigDict

__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "Page", "decode_cursor", "encode_cursor"]

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page[T](BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[T]
    next_cursor: str | None = None


def encode_cursor(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - any malformed cursor is the same client error
        from api.errors import ApiError

        raise ApiError(400, "invalid cursor", f"cursor could not be decoded: {exc}") from exc
