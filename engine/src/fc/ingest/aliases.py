"""Counterparty alias resolution — PRD §0.2, replacing embeddings.

``data/aliases.yaml`` is hand-written and loaded once at ingestion. Matching
is exact-after-normalisation, not fuzzy or learned: uppercase, strip a
leading rail marker (``NEFT``, ``UPI``, ...), strip punctuation, collapse
whitespace, then look the result up in the alias table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = ["AliasTable", "load_aliases", "normalise_counterparty"]

# engine/src/fc/ingest/aliases.py -> repo root is four parents up.
_DEFAULT_ALIASES_PATH = Path(__file__).resolve().parents[4] / "data" / "aliases.yaml"

_RAIL_PREFIX = re.compile(r"^(?:NEFT|RTGS|IMPS|UPI|NACH|CR|DR)\b[\s:/\-]*", re.IGNORECASE)
_PUNCTUATION = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class AliasTable:
    """Normalised alias string -> canonical counterparty name."""

    lookup: dict[str, str]


def _base_normalise(raw: str) -> str:
    text = raw.upper()
    text = _RAIL_PREFIX.sub("", text)
    text = _PUNCTUATION.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def load_aliases(path: Path | str = _DEFAULT_ALIASES_PATH) -> AliasTable:
    """Load and normalise ``data/aliases.yaml`` into a flat lookup table."""
    raw_text = Path(path).read_text(encoding="utf-8")
    entries: list[dict[str, Any]] = yaml.safe_load(raw_text) or []

    lookup: dict[str, str] = {}
    for entry in entries:
        canonical = str(entry["canonical"]).strip().upper()
        lookup[_base_normalise(canonical)] = canonical
        for alias in entry.get("aliases", []):
            lookup[_base_normalise(str(alias))] = canonical
    return AliasTable(lookup=lookup)


def normalise_counterparty(raw: str, aliases: AliasTable | None = None) -> str:
    """Return the canonical counterparty name, or the normalised string if unmatched."""
    normalised = _base_normalise(raw)
    if aliases is not None and normalised in aliases.lookup:
        return aliases.lookup[normalised]
    return normalised
