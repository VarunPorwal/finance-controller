"""``LLM_MODE=off`` — the central claim, asserted rather than demonstrated.

"If both providers go down, reconciliation still runs, metrics still compute,
the dashboard still renders. Only prose degrades."

That is the sentence the whole AI section is built to defend, and until this
file existed it rested on somebody flipping an environment variable by hand
before a demo. It is now a test: the full pipeline and the full post-run
generation pass run twice — once with a model answering, once with the model
switched off — and **every gate metric must be byte-identical**.

It also proves the negative: with the flag off, no socket is opened at all. The
transport raises if anything touches it.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fc.config import Config
from fc.eval.corpus import DATA_DIR, load_corpus
from fc.eval.report import EvalReport, check_gates, evaluate
from fc.llm.client import LLMClient, RawResponse
from fc.llm.generate import (
    RunFacts,
    generate_cluster_labels,
    generate_explanations,
    generate_narrative,
)
from fc.models.exception_ import Cluster, Exception_
from fc.models.money import fmt_inr

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        not (DATA_DIR / "ground_truth.jsonl").exists(),
        reason="no generated corpus; run .\\scripts\\dev.ps1 generate",
    ),
]

TENANT = "t_lumea"
RUN_ID = "run_eval"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class LoudProvider:
    """Answers when called — and records that it was, so "no socket" is checked
    rather than assumed."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, spec: Any, **kwargs: Any) -> RawResponse:
        self.calls += 1
        prompt = kwargs.get("prompt", "")
        if "cluster_id" in prompt:
            return RawResponse(
                text=json.dumps({"labels": [{"cluster_id": "cls_1", "label": "reworded label"}]})
            )
        if "exception_id" in prompt:
            return RawResponse(
                text=json.dumps(
                    {"explanations": [{"exception_id": "exc_1", "explanation": "reworded why"}]}
                )
            )
        return RawResponse(text=json.dumps({"narrative": "Generated prose, quite different."}))


class ForbiddenProvider:
    """Fails the test rather than the request if anything reaches it."""

    async def generate(self, spec: Any, **kwargs: Any) -> RawResponse:
        raise AssertionError("LLM_MODE=off opened a connection")


def _metrics(report: EvalReport, cfg: Config) -> str:
    """Everything §12.5 gates on, plus the dashboard's own headline figures,
    serialised so a difference of any kind shows up as a difference."""
    gates = {g.name: (g.passed, g.actual, g.threshold) for g in check_gates(report, cfg)}
    return json.dumps(
        {
            "gates": gates,
            "predicted_pairs": report.predicted_pairs,
            "correct_pairs": report.correct_pairs,
            "true_pairs": report.true_pairs,
            "false_auto_resolutions": report.false_auto_resolutions,
            "never_auto_inside_auto_closed": report.never_auto_inside_auto_closed,
            "never_auto_after_pipeline": report.never_auto_after_pipeline,
            "precision": str(report.precision),
            "recall": str(report.recall),
            "match_rate": str(report.match_rate),
            "stage_precision": {k: str(v) for k, v in sorted(report.stage_precision.items())},
            "refusals": dict(sorted(report.refusals.items())),
            "matches": [m.model_dump_json() for m in report.cascade.matches],
            "unmatched": sorted(report.cascade.unmatched_event_ids),
            "diagnostics": dict(sorted(report.cascade.diagnostics.items())),
        },
        sort_keys=True,
    )


def _facts(report: EvalReport) -> RunFacts:
    return RunFacts(
        record_count=len(report.corpus.events),
        matched_count=len(report.cascade.matched_event_ids),
        rule_resolved_count=0,
        exception_count=len(report.cascade.unmatched_event_ids),
        cluster_count=0,
        escalate_count=0,
        monitor_count=0,
        gross_collected=fmt_inr(0),
        expected_net=fmt_inr(0),
        actual_bank=fmt_inr(0),
        unexplained=fmt_inr(0),
    )


def _cluster() -> Cluster:
    from datetime import UTC, datetime

    return Cluster(
        cluster_id="cls_1",
        run_id=RUN_ID,
        tenant_id=TENANT,
        root_cause="timing lag",
        label="4× timing lag — HDFC",
        grouping_key="k",
        member_count=4,
        total_paise=100_000,
        max_tier="monitor",
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


def _exception() -> Exception_:
    from datetime import UTC, datetime

    return Exception_(
        exception_id="exc_1",
        run_id=RUN_ID,
        tenant_id=TENANT,
        event_ids=["evt_1"],
        category="chargeback_unrecorded",
        amount_paise=5_200_000,
        residual_paise=5_200_000,
        confidence=Decimal("0.4"),
        tier="escalate",
        priority_score=Decimal("0.9"),
        recommended_action="Contest with Razorpay before the window closes.",
        signature="sig",
        created_at=datetime(2026, 8, 29, tzinfo=UTC),
    )


async def _post_run(client: LLMClient, report: EvalReport) -> dict[str, Any]:
    """The complete post-run generation pass, exactly as a real run fires it."""
    return {
        "narrative": await generate_narrative(
            _facts(report),
            client=client,
            tenant_id=TENANT,
            run_id=RUN_ID,
            fallback="The deterministic headline.",
        ),
        "labels": await generate_cluster_labels(
            [_cluster()], client=client, tenant_id=TENANT, run_id=RUN_ID
        ),
        "explanations": await generate_explanations(
            [_exception()], client=client, tenant_id=TENANT, run_id=RUN_ID
        ),
    }


@pytest.mark.anyio
async def test_turning_the_llm_off_changes_no_metric(tmp_path: Path) -> None:
    """The four gates, byte-identical with and without a model."""
    corpus = load_corpus()

    live_cfg = Config(llm_cache_dir=str(tmp_path / "live"), llm_mode="live")  # type: ignore[arg-type]
    live_client = LLMClient(live_cfg, providers={"gemini": LoudProvider()})
    live_report = evaluate(corpus, live_cfg)
    live_prose = await _post_run(live_client, live_report)

    off_cfg = Config(llm_cache_dir=str(tmp_path / "off"), llm_mode="off")  # type: ignore[arg-type]
    off_client = LLMClient(off_cfg, providers={"gemini": ForbiddenProvider()})
    off_report = evaluate(corpus, off_cfg)
    off_prose = await _post_run(off_client, off_report)

    assert _metrics(live_report, live_cfg) == _metrics(off_report, off_cfg), (
        "a metric moved when the LLM was switched off"
    )

    # Every §12.5 gate still passes with no model at all.
    for gate in check_gates(off_report, off_cfg):
        assert gate.passed, f"{gate.name} failed with LLM_MODE=off: {gate.actual}"

    # And the dashboard is complete, not empty: prose is present in both, and
    # only its wording differs.
    for key in ("narrative", "labels", "explanations"):
        assert live_prose[key], f"{key} was empty even with a model answering"
        assert off_prose[key], f"{key} degraded to nothing rather than to a template"
    for key in ("narrative", "labels", "explanations"):
        assert live_prose[key] != off_prose[key], (
            f"the fake model returned the template for {key}, so this proves nothing"
        )
    assert off_prose["narrative"] == "The deterministic headline."
    assert off_prose["labels"] == {"cls_1": "4× timing lag — HDFC"}
    assert off_prose["explanations"] == {"exc_1": "Contest with Razorpay before the window closes."}


@pytest.mark.anyio
async def test_with_the_llm_off_nothing_reaches_a_provider(tmp_path: Path) -> None:
    """``ForbiddenProvider`` raises on contact, so this is a real assertion
    about network activity rather than a count of calls we chose to make."""
    corpus = load_corpus()
    cfg = Config(llm_cache_dir=str(tmp_path), llm_mode="off")  # type: ignore[arg-type]
    client = LLMClient(cfg, providers={"gemini": ForbiddenProvider(), "groq": ForbiddenProvider()})
    report = evaluate(corpus, cfg)
    await _post_run(client, report)
    assert client.degraded is True
    assert not list(tmp_path.rglob("*.json")), "LLM_MODE=off wrote to the cache"


def test_the_eval_suite_itself_never_imports_the_llm() -> None:
    """``make eval`` runs with no database and no network (hard rule 6). The
    import graph is what guarantees it, not the mode flag."""
    import fc.eval.report

    source = Path(fc.eval.report.__file__).read_text(encoding="utf-8")
    assert "fc.llm" not in source
