"""Embeddings — CUT in PRD §0.1, and this file records what replaced them.

§7.9 planned ``gemini-embedding-001`` at 768 dimensions for counterparty
normalisation and narration similarity, stored in ``transaction_events.narration_vec``
behind an HNSW index. §0.1 cut it from the buildathon scope, and
``TASK_ROUTE["embedding"]`` accordingly routes straight to its terminal rather
than through an ``EMBED:`` step.

That is a smaller loss than it sounds, and the reason is worth stating: every
embedding result was always a *proposal* requiring deterministic confirmation
or human approval (§7.9), so nothing downstream ever depended on a vector being
present. Counterparty normalisation is the alias table in
``fc.ingest.aliases`` — deterministic, seeded from ``data/aliases.yaml``,
auditable, and the thing the embeddings were going to propose additions to.

The column and the index still exist in the schema. Nothing writes them.
"""

from __future__ import annotations

from fc.ingest.aliases import AliasTable, normalise_counterparty

__all__ = ["string_normalise"]


def string_normalise(text: str | None, aliases: AliasTable | None = None) -> str:
    """The ``embedding`` route's terminal: deterministic counterparty normalisation.

    This is what sat underneath the vector similarity all along — the embedding
    would have proposed an alias, and this is the table it would have proposed
    it to.
    """
    return normalise_counterparty(text, aliases) if text else ""
