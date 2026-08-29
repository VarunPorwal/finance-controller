"""The generated corpus, ingested through the real adapters — shared by
``fc.eval.report`` and ``fc.pipeline``'s demo path.

Split out of ``fc.eval.report`` so the pipeline's ``--demo`` entrypoint can
load the same corpus the eval suite scores against, without ``fc.eval.report``
(which now also runs the full pipeline for its own gate) importing
``fc.pipeline`` in a circle.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fc.ingest.bank_csv import parse_bank_csv
from fc.ingest.narration.hdfc import HdfcNarrationParser
from fc.ingest.razorpay import parse_razorpay_recon
from fc.ingest.tally import parse_tally_csv
from fc.models.ids import deterministic_factory
from fc.models.transaction import TransactionEvent

__all__ = [
    "DATA_DIR",
    "EPOCH_MS",
    "INGESTED_AT",
    "RUN_ID",
    "TENANT_ID",
    "Corpus",
    "load_corpus",
]

DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "generated"

#: Fixed so the suite is a pure function of the corpus (hard rule 9).
EPOCH_MS = 1_780_000_000_000
INGESTED_AT = datetime(2026, 8, 29, tzinfo=UTC)
_OPENING_BALANCE_PAISE = 1_000_000_00
RUN_ID = "run_eval"
TENANT_ID = "t_lumea"


@dataclass(frozen=True)
class Corpus:
    events: tuple[TransactionEvent, ...]
    #: (source, source_row_id) -> gt_match_group
    truth: Mapping[tuple[str, str], str | None]
    #: (source, source_row_id) -> bucket
    bucket: Mapping[tuple[str, str], str]
    rejections: int
    #: (source, source_row_id) -> gt_label, for the NEVER_AUTO gates.
    label: Mapping[tuple[str, str], str | None] = field(default_factory=dict)


def load_corpus(data_dir: Path = DATA_DIR) -> Corpus:
    """Ingest the generated files through the production adapters."""
    issue_id = deterministic_factory(seed=42, epoch_ms=EPOCH_MS)

    razorpay = parse_razorpay_recon(
        json.loads((data_dir / "razorpay_recon.json").read_text(encoding="utf-8")),
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        issue_id=issue_id,
        ingested_at=INGESTED_AT,
    )
    bank = parse_bank_csv(
        (data_dir / "bank_statement.csv").read_text(encoding="utf-8"),
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        narration_parser=HdfcNarrationParser(),
        opening_balance_paise=_OPENING_BALANCE_PAISE,
        issue_id=issue_id,
        ingested_at=INGESTED_AT,
    )
    ledger = parse_tally_csv(
        (data_dir / "tally_daybook.csv").read_text(encoding="utf-8"),
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        issue_id=issue_id,
        ingested_at=INGESTED_AT,
    )

    truth: dict[tuple[str, str], str | None] = {}
    bucket: dict[tuple[str, str], str] = {}
    label: dict[tuple[str, str], str | None] = {}
    for line in (data_dir / "ground_truth.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        key = (entry["source"], entry["key"])
        truth[key] = entry["gt_match_group"]
        bucket[key] = entry["bucket"]
        label[key] = entry.get("gt_label")

    events = (*razorpay.events, *bank.ingest.events, *ledger.events)
    rejections = len(razorpay.rejections) + len(bank.ingest.rejections) + len(ledger.rejections)
    return Corpus(events=events, truth=truth, bucket=bucket, rejections=rejections, label=label)
