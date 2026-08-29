"""The router — PRD §7.2, and the eleven guards in §7.3.

This is the component the whole AI layer's honesty rests on, so the tests are
about its failure behaviour rather than its happy path: what it does when a
model is rate-limited, when one returns malformed JSON, when every model in
every tier is unavailable, and when the operator has turned it off entirely.

No network. A fake provider stands in for Gemini and Groq, and a fake clock
stands in for ``time.monotonic`` so cooldowns are tested without sleeping.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fc.config import Config
from fc.llm.client import (
    TASK_ROUTE,
    TERMINALS,
    TIERS,
    AuthError,
    ConfigError,
    LLMClient,
    ModelHealth,
    RateLimited,
    RawResponse,
    SchemaInvalid,
    ServerError,
    TerminalUnavailable,
    TimeoutError_,
)
from fc.llm.schemas import MULTIMODAL, STRUCTURED, TEXT_ONLY, LLMCallRecord, NarrativeOut


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeProvider:
    """Answers, or raises whatever the script says for that model key."""

    def __init__(self, script: dict[str, Any] | None = None, default: Any = None) -> None:
        self.script = script or {}
        self.default = default if default is not None else json.dumps({"narrative": "ok"})
        self.calls: list[str] = []

    async def generate(self, spec: Any, **kwargs: Any) -> RawResponse:
        self.calls.append(spec.key)
        outcome = self.script.get(spec.key, self.default)
        if isinstance(outcome, Exception):
            raise outcome
        return RawResponse(text=outcome, input_tokens=10, output_tokens=5)

    async def create_context_cache(self, spec: Any, **kwargs: Any) -> str:
        return "cachedContents/fake"


def _client(
    tmp_path: Path,
    *,
    script: dict[str, Any] | None = None,
    clock: FakeClock | None = None,
    mode: str = "live",
    records: list[LLMCallRecord] | None = None,
) -> tuple[LLMClient, FakeProvider]:
    provider = FakeProvider(script)
    clock = clock or FakeClock()
    cfg = Config(llm_cache_dir=str(tmp_path), llm_mode=mode)  # type: ignore[arg-type]
    client = LLMClient(
        cfg,
        providers={"gemini": provider, "groq": provider},
        monotonic=clock,
        sink=(records.append if records is not None else None),
    )
    return client, provider


NARRATIVE = json.dumps({"narrative": "fallback"})


# --- routing and rotation ----------------------------------------------------


def test_every_route_ends_in_a_non_llm_terminal() -> None:
    """The property the whole degradation story rests on (§7.2)."""
    for purpose, route in TASK_ROUTE.items():
        assert route[-1].startswith("TERMINAL:"), f"{purpose} does not terminate"
        assert route[-1].removeprefix("TERMINAL:") in TERMINALS, f"{purpose} names no terminal"
        assert not any(step.startswith("TERMINAL:") for step in route[:-1]), (
            f"{purpose} terminates early, so the tiers after it are unreachable"
        )


def test_only_rule_draft_can_reach_a_high_thinking_model() -> None:
    """Guard (§7.3): thinking-token cost blowup on a hot path."""
    deep_tiers = {
        name for name, models in TIERS.items() if any(m.thinking == "high" for m in models)
    }
    assert deep_tiers == {"deep"}
    for purpose, route in TASK_ROUTE.items():
        if "deep" in route:
            assert purpose == "rule_draft", f"{purpose} can select a high-thinking model"


@pytest.mark.anyio
async def test_the_cursor_advances_on_every_success_not_only_on_failure(tmp_path: Path) -> None:
    """This is what makes it round-robin rather than failover: three healthy
    calls must land on three different models, not three times on the first."""
    client, provider = _client(tmp_path)
    for i in range(3):
        await client.call(
            "cluster_label",
            prompt=f"p{i}",
            tenant_id="t",
            schema=None,
            fallback=NARRATIVE,
        )
    light = [m.key for m in TIERS["light"]]
    assert provider.calls == [light[0], light[1], light[0]]


@pytest.mark.anyio
async def test_the_capability_gate_keeps_groq_off_multimodal_work(tmp_path: Path) -> None:
    """Guard (§7.3): schema drift. A model can never be selected for a task it
    cannot perform — checked before rotation, not after a failure."""
    client, provider = _client(tmp_path, script={}, mode="live")
    # Every gemini model unavailable, so the ladder would reach groq if it could.
    for key, health in client.health.items():
        if key.startswith("gemini"):
            health.trip_for_session()
    # Groq is the only model left standing and it is not multimodal, so the
    # ladder finds nothing to try and lands on pdf_extract's terminal — which
    # is the one terminal that cannot synthesise output, because no
    # deterministic code can read a scanned statement. It says so instead.
    with pytest.raises(TerminalUnavailable) as caught:
        await client.call(
            "pdf_extract", prompt="p", tenant_id="t", requires=MULTIMODAL, fallback=None
        )
    assert "Upload the CSV" in str(caught.value)
    assert provider.calls == [], "a text-only model was asked to read a PDF"


@pytest.mark.anyio
async def test_all_models_unavailable_descends_the_ladder_and_terminates(tmp_path: Path) -> None:
    """Guard (§7.3): infinite rotation. A bounded scan per tier, then the
    terminal — never a spin."""
    client, provider = _client(tmp_path)
    for health in client.health.values():
        health.trip_for_session()
    result = await client.call("narrative", prompt="p", tenant_id="t", fallback=NARRATIVE)
    assert result.terminal is True
    assert result.text == NARRATIVE
    assert provider.calls == []


# --- failure classification (§7.2) -------------------------------------------


@pytest.mark.anyio
async def test_a_429_trips_the_model_for_its_retry_after_and_rotates(tmp_path: Path) -> None:
    clock = FakeClock()
    first = TIERS["light"][0]
    client, provider = _client(
        tmp_path,
        script={first.key: RateLimited("slow down", retry_after=45.0)},
        clock=clock,
    )
    await client.call("narrative", prompt="p", tenant_id="t", fallback=NARRATIVE)
    assert provider.calls[0] == first.key
    assert len(provider.calls) == 2, "did not rotate to the next model in the tier"
    assert client.health[first.key].tripped
    clock.advance(44)
    assert client.health[first.key].tripped, "recovered before Retry-After elapsed"
    clock.advance(2)
    assert client.health[first.key].available()


@pytest.mark.anyio
async def test_a_429_without_a_retry_after_header_defaults_to_sixty_seconds(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    first = TIERS["light"][0]
    client, _ = _client(tmp_path, script={first.key: RateLimited("no header")}, clock=clock)
    await client.call("narrative", prompt="p", tenant_id="t", fallback=NARRATIVE)
    clock.advance(59)
    assert client.health[first.key].tripped
    clock.advance(2)
    assert client.health[first.key].available()


@pytest.mark.anyio
async def test_a_schema_failure_rotates_immediately_and_is_not_a_transient_failure(
    tmp_path: Path,
) -> None:
    """Retrying a model that returned malformed JSON reproduces the malformed
    JSON. Only a different model helps — so it rotates, and the failure counter
    that would eventually trip a *flaky* model is deliberately not touched."""
    first = TIERS["light"][0]
    client, provider = _client(tmp_path, script={first.key: "this is not json"})
    result = await client.call(
        "narrative", prompt="p", tenant_id="t", schema=NarrativeOut, fallback=NARRATIVE
    )
    assert provider.calls == [first.key, TIERS["light"][1].key]
    assert client.health[first.key].consecutive_failures == 0
    assert not client.health[first.key].tripped
    assert result.terminal is False


@pytest.mark.anyio
async def test_three_timeouts_trip_the_model_and_one_does_not(tmp_path: Path) -> None:
    clock = FakeClock()
    first = TIERS["light"][0]
    client, _ = _client(tmp_path, script={first.key: TimeoutError_("slow")}, clock=clock)
    await client.call("narrative", prompt="a", tenant_id="t", fallback=NARRATIVE)
    assert not client.health[first.key].tripped
    await client.call("narrative", prompt="b", tenant_id="t", fallback=NARRATIVE)
    assert not client.health[first.key].tripped
    await client.call("narrative", prompt="c", tenant_id="t", fallback=NARRATIVE)
    assert client.health[first.key].tripped
    clock.advance(121)
    assert client.health[first.key].available()


@pytest.mark.anyio
async def test_a_5xx_is_treated_as_transient_like_a_timeout(tmp_path: Path) -> None:
    first = TIERS["light"][0]
    client, _ = _client(tmp_path, script={first.key: ServerError("502")})
    for prompt in "abc":
        await client.call("narrative", prompt=prompt, tenant_id="t", fallback=NARRATIVE)
    assert client.health[first.key].tripped


@pytest.mark.anyio
async def test_an_auth_error_trips_the_model_for_the_whole_session(tmp_path: Path) -> None:
    """Configuration, not load. No cooldown can fix a wrong API key, so the
    model is out until somebody restarts the process with a right one."""
    clock = FakeClock()
    first = TIERS["light"][0]
    client, _ = _client(tmp_path, script={first.key: AuthError("401")}, clock=clock)
    await client.call("narrative", prompt="p", tenant_id="t", fallback=NARRATIVE)
    clock.advance(10_000)
    assert not client.health[first.key].available()


@pytest.mark.anyio
async def test_a_config_error_trips_the_model_for_the_session_like_an_auth_error(
    tmp_path: Path,
) -> None:
    """A 404 is permanent until somebody edits TIERS. Rotating without tripping
    would make every later call re-discover the same dead endpoint."""
    clock = FakeClock()
    first = TIERS["light"][0]
    client, provider = _client(
        tmp_path, script={first.key: ConfigError("404: model_not_found")}, clock=clock
    )
    await client.call("narrative", prompt="p", tenant_id="t", fallback=NARRATIVE)
    clock.advance(10_000)
    assert not client.health[first.key].available(), "a dead model id recovered on its own"
    # And it rotated rather than failing the call.
    assert provider.calls[0] == first.key
    assert len(provider.calls) == 2


def test_a_half_open_probe_that_fails_doubles_the_cooldown_capped_at_ten_minutes() -> None:
    clock = FakeClock()
    health = ModelHealth(rpm_limit=10, rpd_limit=100, monotonic=clock)
    health.trip(60)
    clock.advance(61)
    assert health.available()  # opens the half-open probe
    assert health.half_open
    health.trip(60)
    clock.advance(61)
    assert not health.available(), "a failed probe did not double the cooldown"
    clock.advance(60)
    assert health.available()

    for _ in range(12):
        health.trip(500)
        health.half_open = True
        health.trip(500)
    assert health.cooldown_until is not None
    assert health.cooldown_until - clock.now <= ModelHealth.MAX_COOLDOWN_S


def test_headroom_fails_over_before_the_wall_not_at_it() -> None:
    """Guard (§7.3): hitting a 429 and *then* failing over costs a visible
    retry. 85% of RPM is invisible."""
    clock = FakeClock()
    health = ModelHealth(rpm_limit=20, rpd_limit=100, monotonic=clock)
    # 85% of 20 is 17, so the seventeenth call is the last one allowed and the
    # model reports itself unavailable with three requests of headroom left.
    for _ in range(17):
        assert health.available()
        health.record_success()
    assert not health.available(), "used 17 of 20 RPM and still called itself available"
    assert health.rpm_used == 17

    clock.advance(61)
    assert health.available(), "the minute window did not roll off"


def test_the_daily_counter_resets_after_a_day() -> None:
    clock = FakeClock()
    health = ModelHealth(rpm_limit=1000, rpd_limit=10, monotonic=clock)
    for _ in range(9):
        health.record_success()
        clock.advance(61)
    assert not health.available()
    clock.advance(86_401)
    assert health.available()
    assert health.day_count == 0


# --- caching (§7.3 guards 2 and 10, §9.5) ------------------------------------


@pytest.mark.anyio
async def test_a_cache_hit_serves_without_calling_a_model_or_advancing_the_cursor(
    tmp_path: Path,
) -> None:
    client, provider = _client(tmp_path)
    await client.call("narrative", prompt="same", tenant_id="t", fallback=NARRATIVE)
    assert len(provider.calls) == 1
    for _ in range(3):
        hit = await client.call("narrative", prompt="same", tenant_id="t", fallback=NARRATIVE)
        assert hit.cached is True
    assert len(provider.calls) == 1, "a cache hit reached a provider"
    # The cursor did not move, so the next miss lands on the second model.
    await client.call("narrative", prompt="different", tenant_id="t", fallback=NARRATIVE)
    assert provider.calls[-1] == TIERS["light"][1].key


@pytest.mark.anyio
async def test_the_cache_key_is_salted_per_tenant(tmp_path: Path) -> None:
    """§9.5. A naive prompt-hash cache would let one tenant's data surface in
    another's response — this is the specific failure that closes."""
    client, provider = _client(tmp_path)
    await client.call("narrative", prompt="how much is open?", tenant_id="t_a", fallback=NARRATIVE)
    result = await client.call(
        "narrative", prompt="how much is open?", tenant_id="t_b", fallback=NARRATIVE
    )
    assert result.cached is False, "tenant B was served tenant A's cached answer"
    assert len(provider.calls) == 2


@pytest.mark.anyio
async def test_a_purpose_with_a_downstream_check_is_not_cached_until_confirmed(
    tmp_path: Path,
) -> None:
    """Guard (§7.3): cache poisoning. ``pdf_extract`` parses cleanly and is
    still not believed until ``verify_balance_continuity`` agrees, so ``call``
    must write nothing and ``confirm`` must be the only writer."""
    rows = json.dumps({"rows": []})
    client, provider = _client(tmp_path, script={TIERS["standard"][0].key: rows})
    result = await client.call(
        "pdf_extract", prompt="p", tenant_id="t", requires=MULTIMODAL, fallback=None
    )
    assert result.verified is None
    assert not list(tmp_path.rglob("*.json")), "an unverified extraction was cached"

    again = await client.call(
        "pdf_extract", prompt="p", tenant_id="t", requires=MULTIMODAL, fallback=None
    )
    assert again.cached is False, "an unverified extraction was served from cache"
    assert len(provider.calls) == 2

    client.confirm(result, tenant_id="t")
    third = await client.call(
        "pdf_extract", prompt="p", tenant_id="t", requires=MULTIMODAL, fallback=None
    )
    assert third.cached is True
    assert len(provider.calls) == 2


@pytest.mark.anyio
async def test_a_rejected_extraction_is_never_cached_and_the_retry_calls_again(
    tmp_path: Path,
) -> None:
    rows = json.dumps({"rows": []})
    client, provider = _client(tmp_path, script={TIERS["standard"][0].key: rows})
    result = await client.call(
        "pdf_extract", prompt="p", tenant_id="t", requires=MULTIMODAL, fallback=None
    )
    client.reject(result, tenant_id="t")
    assert not list(tmp_path.rglob("*.json"))
    await client.call("pdf_extract", prompt="p", tenant_id="t", requires=MULTIMODAL, fallback=None)
    assert len(provider.calls) == 2, "a rejected extraction was re-served from cache"


@pytest.mark.anyio
async def test_the_cache_key_excludes_the_model_deliberately(tmp_path: Path) -> None:
    """Guard (§7.3): cache thrash. Any tier member's answer is acceptable, and
    determinism comes from the deterministic core, not from the LLM — so a
    rotation must not invalidate the cache."""
    client, provider = _client(tmp_path)
    await client.call("narrative", prompt="p", tenant_id="t", fallback=NARRATIVE)
    # Force the next pick to be a different model; the cached answer still serves.
    client.tiers["light"]._cursor = 1
    hit = await client.call("narrative", prompt="p", tenant_id="t", fallback=NARRATIVE)
    assert hit.cached is True
    assert len(provider.calls) == 1


# --- the kill switch (§7.3) --------------------------------------------------


@pytest.mark.anyio
async def test_llm_mode_off_terminates_every_purpose_without_touching_a_provider(
    tmp_path: Path,
) -> None:
    """One env var proves P7."""
    client, provider = _client(tmp_path, mode="off")
    for purpose in ("narrative", "cluster_label", "explanation", "command_parse", "text_to_sql"):
        result = await client.call(purpose, prompt="p", tenant_id="t", fallback=NARRATIVE)
        assert result.terminal is True
        assert result.text == NARRATIVE
    assert provider.calls == []
    assert client.degraded is True


@pytest.mark.anyio
async def test_llm_mode_cache_only_serves_hits_and_terminates_on_a_miss(tmp_path: Path) -> None:
    live, _ = _client(tmp_path)
    await live.call("narrative", prompt="warm", tenant_id="t", fallback=NARRATIVE)

    rehearsal, provider = _client(tmp_path, mode="cache_only")
    hit = await rehearsal.call("narrative", prompt="warm", tenant_id="t", fallback=NARRATIVE)
    assert hit.cached is True
    miss = await rehearsal.call("narrative", prompt="cold", tenant_id="t", fallback=NARRATIVE)
    assert miss.terminal is True
    assert provider.calls == [], "cache_only opened a socket"


# --- observability (§7.11) ---------------------------------------------------


@pytest.mark.anyio
async def test_every_attempt_emits_a_record_including_failures_and_terminals(
    tmp_path: Path,
) -> None:
    records: list[LLMCallRecord] = []
    first = TIERS["light"][0]
    client, _ = _client(
        tmp_path, script={first.key: RateLimited("429", retry_after=1.0)}, records=records
    )
    await client.call("narrative", prompt="p", tenant_id="t", run_id="run_1", fallback=NARRATIVE)
    outcomes = [r.outcome for r in records]
    assert "rate_limited" in outcomes
    assert "ok" in outcomes
    assert all(r.run_id == "run_1" for r in records)
    assert all(r.tenant_id == "t" for r in records)


@pytest.mark.anyio
async def test_a_sink_that_raises_never_fails_the_call(tmp_path: Path) -> None:
    def bad_sink(record: LLMCallRecord) -> None:
        raise RuntimeError("the observability database is on fire")

    provider = FakeProvider()
    cfg = Config(llm_cache_dir=str(tmp_path))  # type: ignore[arg-type]
    client = LLMClient(cfg, providers={"gemini": provider}, sink=bad_sink)
    result = await client.call("narrative", prompt="p", tenant_id="t", fallback=NARRATIVE)
    assert result.text  # the call itself succeeded


@pytest.mark.anyio
async def test_health_reports_process_scope_rather_than_implying_it_is_shared(
    tmp_path: Path,
) -> None:
    """Guard (§7.3): quota undercount. Two instances would each count only
    their own calls — the API says so rather than leaving it to a docstring."""
    client, _ = _client(tmp_path)
    snapshot = client.health_snapshot()
    assert snapshot["health_scope"] == "process"
    assert set(snapshot["tiers"]) == set(TIERS)
    assert snapshot["degraded"] is False


@pytest.mark.anyio
async def test_the_ledger_counts_calls_and_cache_hits_per_run(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    await client.call("narrative", prompt="a", tenant_id="t", run_id="r1", fallback=NARRATIVE)
    await client.call("narrative", prompt="a", tenant_id="t", run_id="r1", fallback=NARRATIVE)
    await client.call("narrative", prompt="b", tenant_id="t", run_id="r2", fallback=NARRATIVE)
    assert client.ledger.calls_for("r1") == 2
    assert client.ledger.cached_for("r1") == 1
    assert client.ledger.calls_for("r2") == 1
    assert client.ledger.total == 3


@pytest.mark.anyio
async def test_degraded_is_true_while_any_model_is_tripped(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    assert client.degraded is False
    client.health[TIERS["light"][0].key].trip(60)
    assert client.degraded is True


# --- structured output is the gate (§7.4) ------------------------------------


@pytest.mark.anyio
async def test_a_response_that_fails_its_schema_never_reaches_the_caller(tmp_path: Path) -> None:
    """Every model returns a shape the schema rejects, so the caller gets the
    terminal — not a half-understood object."""
    bad = json.dumps({"not_the_field": "x"})
    client, _ = _client(tmp_path, script={m.key: bad for tier in TIERS.values() for m in tier})
    result = await client.call(
        "narrative",
        prompt="p",
        tenant_id="t",
        schema=NarrativeOut,
        requires=STRUCTURED,
        fallback=NARRATIVE,
    )
    assert result.terminal is True
    assert NarrativeOut.model_validate_json(result.text).narrative == "fallback"


@pytest.mark.anyio
async def test_a_schema_invalid_error_from_the_adapter_rotates_too(tmp_path: Path) -> None:
    first = TIERS["light"][0]
    client, provider = _client(tmp_path, script={first.key: SchemaInvalid("400 bad schema")})
    await client.call("narrative", prompt="p", tenant_id="t", fallback=NARRATIVE)
    assert provider.calls == [first.key, TIERS["light"][1].key]


def test_the_capability_constants_describe_what_each_task_needs() -> None:
    assert TEXT_ONLY.structured is False
    assert STRUCTURED.structured is True
    assert MULTIMODAL.multimodal is True
    groq = TIERS["fallback"][0]
    assert groq.satisfies(STRUCTURED) is True
    assert groq.satisfies(MULTIMODAL) is False
