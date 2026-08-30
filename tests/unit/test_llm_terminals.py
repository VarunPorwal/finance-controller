"""Terminals — PRD §7.2.

"Every route terminates in a non-LLM outcome" is only worth anything if the
outcome is usable. A terminal that returns an error string would satisfy the
letter of it and none of the point: the dashboard would render "sorry, the
model is unavailable" where a sentence belongs.

The design that makes this true by construction is that ``call`` requires a
``fallback`` — the deterministic output the caller had already computed. There
is no branch in which a terminal has to invent something.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fc.config import Config
from fc.llm.client import TASK_ROUTE, TERMINALS, LLMClient, TerminalUnavailable
from fc.llm.embeddings import string_normalise


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


#: Purpose -> the deterministic output its caller supplies, one per terminal.
FALLBACKS = {
    "narrative": json.dumps({"narrative": "412 records reconciled, 310 left open."}),
    "cluster_label": json.dumps({"labels": [{"cluster_id": "cls_1", "label": "14× timing lag"}]}),
    "explanation": json.dumps(
        {"explanations": [{"exception_id": "exc_1", "explanation": "Chase Razorpay support."}]}
    ),
    "command_parse": json.dumps({"name": "__form__", "args": {}}),
    "text_to_sql": json.dumps(
        {"answerable": False, "sql": None, "reason": "No model is reachable right now."}
    ),
    "text_to_sql_light": json.dumps(
        {"answerable": False, "sql": None, "reason": "No model is reachable right now."}
    ),
    "sql_narrate": json.dumps({"narrative": "Here are the numbers, unphrased."}),
    "rule_draft": json.dumps({"name": "Nykaa commission 18%", "description": "Learned from 3."}),
    "embedding": "blinkit commerce",
}


@pytest.mark.anyio
@pytest.mark.parametrize("purpose", sorted(FALLBACKS))
async def test_every_terminal_returns_the_deterministic_output_not_an_error(
    purpose: str, tmp_path: Path
) -> None:
    cfg = Config(llm_cache_dir=str(tmp_path), llm_mode="off")  # type: ignore[arg-type]
    client = LLMClient(cfg, providers={})
    result = await client.call(
        purpose, prompt="anything", tenant_id="t", fallback=FALLBACKS[purpose]
    )
    assert result.terminal is True
    assert result.text == FALLBACKS[purpose]
    assert result.verified is True
    assert "error" not in result.text.lower()
    assert "sorry" not in result.text.lower()


def test_every_purpose_in_the_route_table_has_a_fallback_under_test() -> None:
    """If a purpose is added without one, this fails rather than the coverage
    quietly shrinking."""
    covered = set(FALLBACKS) | {"pdf_extract"}
    assert set(TASK_ROUTE) == covered


@pytest.mark.anyio
async def test_pdf_extraction_is_the_one_terminal_that_cannot_synthesise_output(
    tmp_path: Path,
) -> None:
    """There is no deterministic way to read a scanned statement, so the usable
    output is an action — upload the CSV, which needs no model at all — and the
    caller turns that into a 422 rather than a half-empty ingest."""
    cfg = Config(llm_cache_dir=str(tmp_path), llm_mode="off")  # type: ignore[arg-type]
    client = LLMClient(cfg, providers={})
    with pytest.raises(TerminalUnavailable) as caught:
        await client.call("pdf_extract", prompt="p", tenant_id="t", fallback=None)
    assert "CSV" in str(caught.value)
    assert caught.value.purpose == "pdf_extract"


def test_a_terminal_reached_with_no_fallback_is_a_caller_bug_not_a_silent_empty_string() -> None:
    for name, terminal in TERMINALS.items():
        if name == "manual_csv":
            continue
        with pytest.raises(TerminalUnavailable):
            terminal("narrative", None)


def test_the_embedding_terminal_is_deterministic_counterparty_normalisation() -> None:
    """Embeddings are CUT (§0.1); this is what was underneath them all along."""
    assert string_normalise("  Blinkit Commerce Private Limited  ")
    assert string_normalise(None) == ""
    assert string_normalise("ACME") == string_normalise("acme")
