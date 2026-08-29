"""The ≤6-calls-per-run budget — PRD §7.11, and the batching that keeps it.

The number is not decoration. A run that quietly costs fifteen calls exhausts a
free-tier daily quota in a few rehearsals, and the first anyone notices is on
demo day. So the post-run pass batches: one call for every cluster label, one
for every explanation, rather than one per item.

This measures the whole pass against a counting transport, with no database and
no network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fc.config import Config
from fc.llm.client import LLMClient, RawResponse
from fc.llm.generate import (
    CALLS_PER_RUN,
    RunFacts,
    generate_cluster_labels,
    generate_explanations,
    generate_narrative,
)
from fc.models.exception_ import Cluster, Exception_

NOW = datetime(2026, 8, 29, tzinfo=UTC)
RUN_ID = "run_budget"
TENANT = "t_lumea"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class EchoProvider:
    """Answers every purpose with a schema-valid response, and counts."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, spec: Any, **kwargs: Any) -> RawResponse:
        self.calls += 1
        prompt = kwargs.get("prompt", "")
        if "cluster_id" in prompt:
            ids = _ids(prompt, "cluster_id")
            return RawResponse(
                text=json.dumps(
                    {"labels": [{"cluster_id": i, "label": f"rewritten {i}"} for i in ids]}
                )
            )
        if "exception_id" in prompt:
            ids = _ids(prompt, "exception_id")
            return RawResponse(
                text=json.dumps(
                    {
                        "explanations": [
                            {"exception_id": i, "explanation": f"because of {i}"} for i in ids
                        ]
                    }
                )
            )
        return RawResponse(text=json.dumps({"narrative": "A tidy paragraph."}))


def _ids(prompt: str, key: str) -> list[str]:
    return [
        json.loads(line.split(":", 1)[1].strip().rstrip(","))
        for line in prompt.splitlines()
        if line.strip().startswith(f'"{key}"')
    ]


def _facts() -> RunFacts:
    return RunFacts(
        record_count=500,
        matched_count=1133,
        rule_resolved_count=126,
        exception_count=312,
        cluster_count=12,
        escalate_count=18,
        monitor_count=94,
        gross_collected="₹1,00,00,000.00",
        expected_net="₹98,20,000.00",
        actual_bank="₹98,19,600.00",
        unexplained="₹4,000.00",
    )


def _cluster(i: int) -> Cluster:
    return Cluster(
        cluster_id=f"cls_{i}",
        run_id=RUN_ID,
        tenant_id=TENANT,
        root_cause="timing lag",
        label=f"{i}× timing lag — HDFC",
        grouping_key=f"k{i}",
        member_count=4,
        total_paise=100_000,
        max_tier="monitor",
        created_at=NOW,
    )


def _exception(i: int, tier: str = "escalate") -> Exception_:
    return Exception_(
        exception_id=f"exc_{i}",
        run_id=RUN_ID,
        tenant_id=TENANT,
        event_ids=[f"evt_{i}"],
        category="chargeback_unrecorded",
        amount_paise=5_200_000,
        residual_paise=5_200_000,
        confidence=Decimal("0.4"),
        tier=tier,  # type: ignore[arg-type]
        priority_score=Decimal("0.9"),
        recommended_action="Contest with Razorpay before the window closes.",
        signature="sig",
        created_at=NOW,
    )


def _client(tmp_path: Path, mode: str = "live") -> tuple[LLMClient, EchoProvider]:
    provider = EchoProvider()
    cfg = Config(llm_cache_dir=str(tmp_path), llm_mode=mode)  # type: ignore[arg-type]
    return LLMClient(cfg, providers={"gemini": provider, "groq": provider}), provider


async def _post_run(client: LLMClient, *, clusters: int, escalated: int) -> None:
    await generate_narrative(
        _facts(), client=client, tenant_id=TENANT, run_id=RUN_ID, fallback="deterministic"
    )
    await generate_cluster_labels(
        [_cluster(i) for i in range(clusters)], client=client, tenant_id=TENANT, run_id=RUN_ID
    )
    await generate_explanations(
        [_exception(i) for i in range(escalated)], client=client, tenant_id=TENANT, run_id=RUN_ID
    )


@pytest.mark.anyio
async def test_a_full_post_run_pass_costs_three_calls_and_never_more_than_six(
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)
    await _post_run(client, clusters=12, escalated=18)
    assert provider.calls == CALLS_PER_RUN == 3
    assert client.ledger.calls_for(RUN_ID) <= 6


@pytest.mark.anyio
async def test_the_cost_does_not_grow_with_the_size_of_the_queue(tmp_path: Path) -> None:
    """The property batching buys. Thirty clusters and twenty escalations cost
    the same three calls as one of each — which is the difference between a
    budget and a hope."""
    small, small_provider = _client(tmp_path / "small")
    await _post_run(small, clusters=1, escalated=1)

    large, large_provider = _client(tmp_path / "large")
    await _post_run(large, clusters=30, escalated=20)

    assert small_provider.calls == large_provider.calls == 3


@pytest.mark.anyio
async def test_nothing_to_say_costs_nothing(tmp_path: Path) -> None:
    client, provider = _client(tmp_path)
    await generate_cluster_labels([], client=client, tenant_id=TENANT, run_id=RUN_ID)
    await generate_explanations([], client=client, tenant_id=TENANT, run_id=RUN_ID)
    assert provider.calls == 0


@pytest.mark.anyio
async def test_only_escalated_exceptions_are_explained(tmp_path: Path) -> None:
    """The third of three calls, over a queue that can be long. Items nobody has
    to look at do not need prose."""
    client, _ = _client(tmp_path)
    written = await generate_explanations(
        [_exception(1, "escalate"), _exception(2, "monitor"), _exception(3, "auto")],
        client=client,
        tenant_id=TENANT,
        run_id=RUN_ID,
    )
    assert set(written) == {"exc_1"}


@pytest.mark.anyio
async def test_a_label_for_a_cluster_that_does_not_exist_is_discarded(tmp_path: Path) -> None:
    """The model may rename, never add. A label keyed to an invented cluster id
    would otherwise be written straight back to the database."""

    class InventingProvider(EchoProvider):
        async def generate(self, spec: Any, **kwargs: Any) -> RawResponse:
            self.calls += 1
            return RawResponse(
                text=json.dumps(
                    {
                        "labels": [
                            {"cluster_id": "cls_0", "label": "fine"},
                            {"cluster_id": "cls_invented", "label": "not a real cluster"},
                        ]
                    }
                )
            )

    provider = InventingProvider()
    cfg = Config(llm_cache_dir=str(tmp_path))  # type: ignore[arg-type]
    client = LLMClient(cfg, providers={"gemini": provider, "groq": provider})
    labels = await generate_cluster_labels(
        [_cluster(0)], client=client, tenant_id=TENANT, run_id=RUN_ID
    )
    assert labels == {"cls_0": "fine"}


@pytest.mark.anyio
async def test_a_cached_run_costs_nothing_the_second_time(tmp_path: Path) -> None:
    """The rehearsal path (§7.3, demo-day quota exhaustion)."""
    client, provider = _client(tmp_path)
    await _post_run(client, clusters=12, escalated=18)
    await _post_run(client, clusters=12, escalated=18)
    assert provider.calls == 3
    assert client.ledger.cached_for(RUN_ID) == 3


@pytest.mark.anyio
async def test_with_the_llm_off_the_pass_costs_nothing_and_still_produces_prose(
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path, mode="off")
    narrative = await generate_narrative(
        _facts(), client=client, tenant_id=TENANT, run_id=RUN_ID, fallback="deterministic headline"
    )
    labels = await generate_cluster_labels(
        [_cluster(i) for i in range(3)], client=client, tenant_id=TENANT, run_id=RUN_ID
    )
    explanations = await generate_explanations(
        [_exception(i) for i in range(3)], client=client, tenant_id=TENANT, run_id=RUN_ID
    )
    assert provider.calls == 0
    assert narrative == "deterministic headline"
    assert labels == {f"cls_{i}": f"{i}× timing lag — HDFC" for i in range(3)}
    assert explanations == {
        f"exc_{i}": "Contest with Razorpay before the window closes." for i in range(3)
    }
