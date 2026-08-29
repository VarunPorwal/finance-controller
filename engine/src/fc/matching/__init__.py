"""Deterministic matching — PRD §6.2, §6.3, §6.5, §6.6.

Nothing here imports ``fc.llm``. The LLM never decides whether something is
reconciled (CLAUDE.md hard rule 2); it is the architectural claim the rest of
the system rests on, and ``tests/unit/test_architecture.py`` enforces it by AST
scan over this package.
"""

from fc.matching.blocking import BlockIndex, BlockingStats, block_key, build_blocks
from fc.matching.cascade import CASCADE_ORDER, CascadeResult, run_cascade
from fc.matching.confidence import ConfidenceInputs, cap_for_stage, derive
from fc.matching.ledger_refs import LedgerRefIndex, LedgerRefs, extract_refs, index_ledger_refs
from fc.matching.tolerance import ToleranceTerms, tolerance_paise, tolerance_terms

__all__ = [
    "CASCADE_ORDER",
    "BlockIndex",
    "BlockingStats",
    "CascadeResult",
    "ConfidenceInputs",
    "LedgerRefIndex",
    "LedgerRefs",
    "ToleranceTerms",
    "block_key",
    "build_blocks",
    "cap_for_stage",
    "derive",
    "extract_refs",
    "index_ledger_refs",
    "run_cascade",
    "tolerance_paise",
    "tolerance_terms",
]
