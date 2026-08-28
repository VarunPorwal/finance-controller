"""Ground truth: the correct answer for every generated row, on the row.

PRD §2.6 D1, §4.1.8. Every :class:`GTEntry` is written by the same code path
that authors the corresponding source row (see ``razorpay_gen``, ``bank_gen``,
``tally_gen``), so it can't drift out of sync with what was actually emitted.
It is kept in a companion file rather than embedded in the source rows
themselves only because the adapters' row schemas use ``extra="forbid"`` and
must byte-match real exports — the generator's own event objects, not the
files, are what "the row" refers to.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from fc.generator.scenarios import EXTRA_SCENARIOS, SCENARIOS

__all__ = ["GTEntry", "write_ground_truth", "write_manifest"]


@dataclass(frozen=True)
class GTEntry:
    """One row's ground truth, keyed by the same natural id its adapter uses
    for idempotency (``entity_id`` | bank row hash | ``voucher_guid``)."""

    source: str  # razorpay | bank | ledger
    key: str
    gt_match_group: str | None
    gt_label: str | None
    bucket: str  # matched | rule_resolved | exception
    scenario: int | None


def write_ground_truth(path: str | Path, entries: Iterable[GTEntry]) -> None:
    lines = [json.dumps(asdict(e), sort_keys=True) for e in entries]
    Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_manifest(
    path: str | Path,
    *,
    seed: int,
    n: int,
    entries: list[GTEntry],
    row_counts: dict[str, int],
) -> dict[str, Any]:
    by_bucket: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_scenario: dict[str, int] = {}
    for e in entries:
        by_bucket[e.bucket] = by_bucket.get(e.bucket, 0) + 1
        if e.gt_label:
            by_category[e.gt_label] = by_category.get(e.gt_label, 0) + 1
        if e.scenario is not None:
            key = str(e.scenario)
            by_scenario[key] = by_scenario.get(key, 0) + 1

    manifest = {
        "seed": seed,
        "n": n,
        "row_counts": row_counts,
        "total_ground_truth_rows": len(entries),
        "by_bucket": by_bucket,
        "by_category": by_category,
        "by_scenario": by_scenario,
        "scenarios": [
            {"id": s.id, "key": s.key, "description": s.description}
            for s in (*SCENARIOS, *EXTRA_SCENARIOS)
        ],
        "expected_counts_consistent": (
            by_bucket.get("matched", 0)
            + by_bucket.get("rule_resolved", 0)
            + by_bucket.get("exception", 0)
            == len(entries)
        ),
    }
    Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest
