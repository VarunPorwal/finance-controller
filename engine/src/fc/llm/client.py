"""The tiered round-robin router — PRD §7.2, §7.3, §7.6.

Round-robin *within* a tier, ladder *between* tiers. Plain round-robin sends
hard work to weak models; a pure ladder drains the strongest model until it
dies. The cursor advances on every successful pick, not only on failure, which
is what spreads quota evenly instead of exhausting one model first.

Every route in :data:`TASK_ROUTE` ends in a non-LLM terminal, and that is the
load-bearing property of this file. With both providers down — or with
``LLM_MODE=off``, which is the same thing on purpose — reconciliation still
runs, every metric still computes, the dashboard is still complete. Only prose
degrades. The terminal is not an error path; it is the deterministic answer the
caller already had, which is why every ``call`` takes a ``fallback``.

The eleven risks in §7.3 are each marked below with ``Guard (§7.3):``.

**Known limitation, stated rather than hidden (§7.3, quota undercount).** Health
counters live in this process. Two API instances sharing one project quota will
each count only their own calls and will together exceed the headroom margins.
The buildathon deployment is a single instance; Tier 2 moves this state to
Redis, along with the parsed-command store in ``api/routers/agent.py``, which
has the same shape of limitation for the same reason. ``/agent/health`` reports
``health_scope: "process"`` so the honest answer is visible in the API rather
than only in this docstring.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from fc.config import Config
from fc.llm.schemas import (
    HAS_DOWNSTREAM_CHECK,
    TEXT_ONLY,
    Capabilities,
    LLMCallRecord,
    LLMResult,
    ModelSpec,
)

__all__ = [
    "PROMPTS",
    "PROMPT_HASHES",
    "TASK_ROUTE",
    "TERMINALS",
    "TIERS",
    "AuthError",
    "CallLedger",
    "ConfigError",
    "LLMClient",
    "LLMError",
    "ModelHealth",
    "RateLimited",
    "RawResponse",
    "SafetyBlocked",
    "SchemaInvalid",
    "ServerError",
    "TerminalUnavailable",
    "Tier",
    "TimeoutError_",
    "load_prompt",
]

_LOG = logging.getLogger("fc.llm")

_PROMPT_DIR = Path(__file__).parent / "prompts"


def _load_prompts() -> tuple[dict[str, str], dict[str, str]]:
    """Read the prompt files once, at import, and hash each.

    §10.3 model-layer controls: prompts are files with content hashes recorded
    in ``llm_calls``, so a change to a prompt is visible in the call log rather
    than inferred from a shift in output quality.
    """
    texts: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for path in sorted(_PROMPT_DIR.glob("*.md")):
        body = path.read_text(encoding="utf-8")
        texts[path.stem] = body
        hashes[path.stem] = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    return texts, hashes


PROMPTS, PROMPT_HASHES = _load_prompts()


def load_prompt(name: str) -> str:
    """The text of ``prompts/{name}.md``. Raises if a prompt file is missing."""
    try:
        return PROMPTS[name]
    except KeyError:  # pragma: no cover - a missing prompt file is a build error
        raise KeyError(f"no prompt file prompts/{name}.md (have {sorted(PROMPTS)})") from None


# --- tiers and routes (§7.2) -------------------------------------------------

# Free-tier RPM/RPD are the published AI Studio figures for the Flash class and
# Groq's free tier. They are the *input to the headroom margin*, not a hard
# limit we rely on: the router fails over at 85% of RPM and 90% of RPD, so a
# figure that is slightly optimistic costs a rotation, not a visible 429.
#: Free-tier limits, verified against AI Studio 29 Aug 2026, and every id
#: verified against the live catalogue with a structured-output call.
#:
#: The Flash tier is the constrained one: **20 requests per day, per model.**
#: That is what makes round-robin load-bearing here rather than tidy — one
#: model alone would exhaust the daily budget in twenty calls, and four in
#: rotation give eighty. Every usable id is listed for that reason; a subset
#: would be leaving quota on the table for no benefit.
FLASH_RPM, FLASH_RPD = 5, 20
LITE_RPM, LITE_RPD = 15, 500

#: Ids checked and deliberately excluded:
#:
#: * ``gemini-3-flash`` — 404, not in this account's catalogue at all.
#: * ``gemini-flash-lite-latest`` — an **alias**: its response reports
#:   ``modelVersion=gemini-3.5-flash-lite``, which is already in the light tier.
#:   Aliases resolve server-side to a numbered model and share its bucket, so it
#:   would add a name and no capacity while making the budget look larger.
#: * ``gemini-flash-latest`` — the same alias pattern (pointer-style version
#:   metadata, no date stamp); excluded for the same reason.
#: * ``llama-3.3-70b-versatile`` — 404 on this Groq account; no Llama chat
#:   model is available, only the prompt-guard classifiers.
TIERS: dict[str, tuple[ModelSpec, ...]] = {
    "light": (
        ModelSpec(
            "gemini",
            "gemini-3.5-flash-lite",
            "low",
            multimodal=True,
            rpm_limit=LITE_RPM,
            rpd_limit=LITE_RPD,
        ),
        ModelSpec(
            "gemini",
            "gemini-3.1-flash-lite",
            "low",
            multimodal=True,
            rpm_limit=LITE_RPM,
            rpd_limit=LITE_RPD,
        ),
        ModelSpec(
            "gemini",
            "gemini-3.1-flash-lite-preview",
            "low",
            multimodal=True,
            rpm_limit=LITE_RPM,
            rpd_limit=LITE_RPD,
        ),
    ),
    "standard": (
        ModelSpec(
            "gemini",
            "gemini-3.7-flash",
            "low",
            multimodal=True,
            rpm_limit=FLASH_RPM,
            rpd_limit=FLASH_RPD,
        ),
        ModelSpec(
            "gemini",
            "gemini-3.6-flash",
            "low",
            multimodal=True,
            rpm_limit=FLASH_RPM,
            rpd_limit=FLASH_RPD,
        ),
        ModelSpec(
            "gemini",
            "gemini-3.5-flash",
            "low",
            multimodal=True,
            rpm_limit=FLASH_RPM,
            rpd_limit=FLASH_RPD,
        ),
        ModelSpec(
            "gemini",
            "gemini-3-flash-preview",
            "low",
            multimodal=True,
            rpm_limit=FLASH_RPM,
            rpd_limit=FLASH_RPD,
        ),
    ),
    "deep": (
        # Guard (§7.3): thinking-token cost blowup. ``high`` appears here and
        # nowhere else, and only ``rule_draft`` routes to this tier.
        #
        # These are the *same four models* as ``standard`` at a higher reasoning
        # budget, so they share its quota — see ModelSpec.quota_key. The tier
        # adds reasoning depth, not capacity.
        ModelSpec("gemini", "gemini-3.7-flash", "high", rpm_limit=FLASH_RPM, rpd_limit=FLASH_RPD),
        ModelSpec("gemini", "gemini-3.6-flash", "high", rpm_limit=FLASH_RPM, rpd_limit=FLASH_RPD),
        ModelSpec("gemini", "gemini-3.5-flash", "high", rpm_limit=FLASH_RPM, rpd_limit=FLASH_RPD),
        ModelSpec(
            "gemini", "gemini-3-flash-preview", "high", rpm_limit=FLASH_RPM, rpd_limit=FLASH_RPD
        ),
    ),
    "fallback": (
        # A separate provider and therefore a genuinely separate budget — which
        # is most of why the fallback tier is worth having at all.
        ModelSpec(
            "groq", "openai/gpt-oss-120b", "none", multimodal=False, rpm_limit=30, rpd_limit=1000
        ),
        ModelSpec(
            "groq", "openai/gpt-oss-20b", "none", multimodal=False, rpm_limit=30, rpd_limit=1000
        ),
    ),
}

#: Every route terminates in a non-LLM outcome. That is what makes degradation
#: honest rather than a failure — asserted by ``test_every_route_ends_in_a_terminal``.
#:
#: ``embedding`` routes straight to its terminal: embeddings are CUT in §0.1, so
#: there is no ``EMBED:`` step to take, and counterparty normalisation was
#: always the deterministic answer underneath it.
TASK_ROUTE: dict[str, tuple[str, ...]] = {
    "command_parse": ("light", "standard", "fallback", "TERMINAL:form"),
    "text_to_sql": ("standard", "light", "fallback", "TERMINAL:refuse"),
    "narrative": ("light", "fallback", "TERMINAL:template"),
    "cluster_label": ("light", "TERMINAL:template"),
    "explanation": ("light", "TERMINAL:template"),
    "rule_draft": ("deep", "standard", "fallback", "TERMINAL:defer"),
    "pdf_extract": ("standard", "TERMINAL:manual_csv"),
    "embedding": ("TERMINAL:string_normalise",),
}

#: §7.6. An explicit context cache binds to one model, so rotating away from it
#: silently costs full input rate on an 8k-token system prompt. ``text_to_sql``
#: therefore pins its first choice and rotates less evenly than the other
#: purposes. A deliberate trade, recorded here rather than discovered later.
CONTEXT_CACHED_PURPOSES: frozenset[str] = frozenset({"text_to_sql"})


# --- failures (§7.2 failure classification) ----------------------------------


class LLMError(Exception):
    """Base for every provider failure the router knows how to classify."""


class RateLimited(LLMError):
    def __init__(self, message: str = "", retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TimeoutError_(LLMError):
    """Named with a trailing underscore so it cannot shadow the builtin."""


class ServerError(LLMError):
    pass


class SafetyBlocked(LLMError):
    pass


class AuthError(LLMError):
    pass


class ConfigError(LLMError):
    """A model that does not exist, or that this account cannot reach.

    Classified apart from :class:`SchemaInvalid` because the two want opposite
    treatment. A schema failure rotates *without* tripping, on the reasoning
    that the model is fine and this particular request was not — which is right
    for a 400, and exactly wrong for a 404: the endpoint is dead, and rotating
    without tripping means every later call pays full latency to rediscover
    that. Handled like :class:`AuthError` instead — tripped for the session and
    logged loudly, because no cooldown fixes a wrong model id.

    Found the hard way: the fallback tier shipped naming a Groq model this
    account has no access to, and the resulting 404 was reported as a schema
    failure, which is a quieter and much more misleading thing for it to say.
    """


class SchemaInvalid(LLMError):
    """The response did not validate. Rotate; never retry the same model."""


class TerminalUnavailable(LLMError):
    """A terminal that cannot synthesise output, because the *input* is
    unreadable without a model.

    Only ``pdf_extract`` reaches this: there is no deterministic way to read a
    scanned statement. The terminal's usable output is the instruction to
    upload the CSV instead, which ``api/`` renders as a 422 with that action.
    """

    def __init__(self, purpose: str, message: str) -> None:
        super().__init__(message)
        self.purpose = purpose


@dataclass(frozen=True)
class RawResponse:
    """What an adapter returns before the router validates it."""

    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None


# --- health (§7.2) -----------------------------------------------------------


@dataclass
class ModelHealth:
    """Quota and circuit-breaker state for one model.

    The headroom margins are the important part. Hitting a 429 and *then*
    failing over costs a visible retry in front of an audience; failing over at
    85% of RPM is invisible.
    """

    rpm_limit: int
    rpd_limit: int
    monotonic: Callable[[], float] = time.monotonic
    minute_window: deque[float] = field(default_factory=deque)
    day_count: int = 0
    day_started: float = -1.0
    cooldown_until: float | None = None
    consecutive_failures: int = 0
    half_open: bool = False

    RPM_HEADROOM = 0.85
    RPD_HEADROOM = 0.90
    MAX_COOLDOWN_S = 600.0
    FAILURES_BEFORE_TRIP = 3
    TRANSIENT_COOLDOWN_S = 120.0
    DEFAULT_RATE_LIMIT_COOLDOWN_S = 60.0

    def available(self) -> bool:
        now = self.monotonic()
        if self.cooldown_until is not None:
            if now < self.cooldown_until:
                return False
            self.half_open = True  # allow exactly one probe
            self.cooldown_until = None
        self._trim_minute(now)
        self._maybe_reset_day(now)
        return (
            len(self.minute_window) < self.rpm_limit * self.RPM_HEADROOM
            and self.day_count < self.rpd_limit * self.RPD_HEADROOM
        )

    def record_success(self) -> None:
        now = self.monotonic()
        self._maybe_reset_day(now)
        self.minute_window.append(now)
        self.day_count += 1
        self.consecutive_failures = 0
        self.half_open = False

    def record_failure(self) -> None:
        """A transient failure. Trips only once the third one lands."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.FAILURES_BEFORE_TRIP:
            self.trip(self.TRANSIENT_COOLDOWN_S)

    def trip(self, cooldown_s: float) -> None:
        # Guard (§7.3): cooldown storms. Per-model, doubled when a half-open
        # probe fails, and capped at ten minutes — so a burst that trips every
        # model still recovers on its own, and the terminals keep the feature
        # working in the meantime.
        base = cooldown_s * 2 if self.half_open else cooldown_s
        self.cooldown_until = self.monotonic() + min(base, self.MAX_COOLDOWN_S)
        self.half_open = False

    def trip_for_session(self) -> None:
        """An auth error is configuration, not load. Retrying cannot help."""
        self.cooldown_until = math.inf
        self.half_open = False

    @property
    def tripped(self) -> bool:
        return self.cooldown_until is not None and self.monotonic() < self.cooldown_until

    @property
    def rpm_used(self) -> int:
        self._trim_minute(self.monotonic())
        return len(self.minute_window)

    def _trim_minute(self, now: float) -> None:
        while self.minute_window and now - self.minute_window[0] >= 60.0:
            self.minute_window.popleft()

    def _maybe_reset_day(self, now: float) -> None:
        if self.day_started < 0:
            self.day_started = now
        elif now - self.day_started >= 86_400.0:
            self.day_started = now
            self.day_count = 0


class Tier:
    """One tier's models, and the cursor that rotates through them."""

    def __init__(self, name: str, models: Sequence[ModelSpec]) -> None:
        self.name = name
        self.models = tuple(models)
        self._cursor = 0
        # Guard (§7.3): cursor race. Two threads picking concurrently would
        # otherwise land on the same model and double-count its quota.
        self._lock = threading.Lock()

    def next_available(
        self,
        requires: Capabilities,
        health: Mapping[str, ModelHealth],
        *,
        pinned: str | None = None,
    ) -> ModelSpec | None:
        """The next model that can serve this task, or ``None`` to descend a tier.

        Guard (§7.3): infinite rotation. The scan is bounded by ``range(n)``, so
        an all-unhealthy tier returns ``None`` after one pass instead of spinning.
        """
        with self._lock:
            n = len(self.models)
            for i in range(n):
                m = self.models[(self._cursor + i) % n]
                if pinned is not None and m.key != pinned:
                    continue
                # Guard (§7.3): schema drift between models. Capability is
                # checked *before* rotation, so a model can never be selected
                # for a task it cannot perform.
                if not m.satisfies(requires):
                    continue
                if not health[m.quota_key].available():
                    continue
                # The cursor advances on every successful pick, not only on
                # failure. This is what makes it round-robin rather than
                # failover, and why quota drains evenly across the tier.
                self._cursor = (self._cursor + i + 1) % n
                return m
            return None

    def position_of(self, spec: ModelSpec) -> int:
        return self.models.index(spec)


# --- terminals ---------------------------------------------------------------


def _terminal_template(purpose: str, fallback: str | None) -> str:
    """Narrative, cluster label, explanation: the deterministic renderer's own
    output. The caller already computed it — the model was only ever going to
    rephrase it."""
    return _require_fallback(purpose, fallback)


def _terminal_form(purpose: str, fallback: str | None) -> str:
    """Command parse: the structured form. The operator fills the fields in
    directly instead of typing a sentence, which is the same command by a
    slower route, not a failure."""
    return _require_fallback(purpose, fallback)


def _terminal_refuse(purpose: str, fallback: str | None) -> str:
    """Text-to-SQL: an honest ``answerable: false`` naming the reason, rendered
    verbatim to the user. Refusing is a correct outcome here (hard rule 4)."""
    return _require_fallback(purpose, fallback)


def _terminal_defer(purpose: str, fallback: str | None) -> str:
    """Rule draft: the learner's own arithmetic name and description. It never
    needed a model for the numbers, only for the prose."""
    return _require_fallback(purpose, fallback)


def _terminal_string_normalise(purpose: str, fallback: str | None) -> str:
    """Embedding: deterministic counterparty normalisation. Embeddings are CUT
    (§0.1); this was always what sat underneath them."""
    return _require_fallback(purpose, fallback)


def _terminal_manual_csv(purpose: str, fallback: str | None) -> str:
    """PDF extraction: the one terminal that cannot synthesise its output.

    There is no deterministic way to read a scanned statement, so the usable
    output is an action rather than a document — upload the CSV export instead.
    """
    raise TerminalUnavailable(
        purpose,
        "PDF extraction needs a multimodal model and none is available. "
        "Upload the CSV or Excel export of the same statement instead — the "
        "CSV path is fully deterministic and needs no model at all.",
    )


def _require_fallback(purpose: str, fallback: str | None) -> str:
    if fallback is None:  # pragma: no cover - a caller bug, not a runtime state
        raise TerminalUnavailable(
            purpose, f"{purpose} reached its terminal with no deterministic fallback supplied"
        )
    return fallback


TERMINALS: dict[str, Callable[[str, str | None], str]] = {
    "template": _terminal_template,
    "form": _terminal_form,
    "refuse": _terminal_refuse,
    "defer": _terminal_defer,
    "manual_csv": _terminal_manual_csv,
    "string_normalise": _terminal_string_normalise,
}


# --- cache -------------------------------------------------------------------


class DiskCache:
    """Prompt-keyed response cache on disk.

    Guard (§7.3): cache thrash. **The key deliberately excludes the model.** Any
    member of a tier is an acceptable answer for the task, and determinism is
    guaranteed by the deterministic core rather than by the LLM — so keying on
    the model would only mean a rotation silently invalidates the whole cache
    and the demo's pre-warmed responses stop being served.

    §9.5: the key includes ``tenant_id``, and entries are filed under a hash of
    it. A naive prompt-hash cache would let one tenant's data surface in
    another's response; that is the specific failure this partitioning closes.
    """

    def __init__(self, root: Path, *, ttl_days: int) -> None:
        self.root = root
        self.ttl_seconds = ttl_days * 86_400

    @staticmethod
    def key(
        *,
        tenant_id: str,
        purpose: str,
        prompt: str,
        system: str | None,
        schema_fingerprint: str,
        prompt_hash: str,
        extra: Mapping[str, Any] | None = None,
    ) -> str:
        material = json.dumps(
            {
                "tenant": tenant_id,
                "purpose": purpose,
                "prompt": prompt,
                "system": system or "",
                "schema": schema_fingerprint,
                "prompt_file": prompt_hash,
                "extra": dict(extra or {}),
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _path(self, tenant_id: str, key: str) -> Path:
        shard = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
        return self.root / shard / f"{key}.json"

    def get(self, tenant_id: str, key: str) -> LLMResult | None:
        path = self._path(tenant_id, key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        stored_at = float(payload.pop("_stored_at", 0.0))
        if self.ttl_seconds and time.time() - stored_at > self.ttl_seconds:
            return None
        try:
            result = LLMResult.model_validate(payload)
        except ValidationError:  # pragma: no cover - a stale cache format
            return None
        return result.model_copy(update={"cached": True})

    def set(self, tenant_id: str, key: str, result: LLMResult) -> None:
        # Guard (§7.3): cache poisoning. A response that has not passed its
        # deterministic check never gets here — for purposes in
        # HAS_DOWNSTREAM_CHECK the only caller of this method is
        # LLMClient.confirm(), which runs after the check has agreed.
        if result.verified is not True:
            return
        path = self._path(tenant_id, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = result.model_dump(mode="json")
        payload["_stored_at"] = time.time()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)


class CallLedger:
    """Calls and cache hits per run — §7.11, and the ≤6-per-run budget."""

    def __init__(self) -> None:
        self._calls: dict[str, int] = {}
        self._cached: dict[str, int] = {}
        self._lock = threading.Lock()

    def record(self, run_id: str | None, *, cached: bool) -> None:
        key = run_id or "_"
        with self._lock:
            self._calls[key] = self._calls.get(key, 0) + 1
            if cached:
                self._cached[key] = self._cached.get(key, 0) + 1

    def calls_for(self, run_id: str | None) -> int:
        return self._calls.get(run_id or "_", 0)

    def cached_for(self, run_id: str | None) -> int:
        return self._cached.get(run_id or "_", 0)

    @property
    def total(self) -> int:
        return sum(self._calls.values())

    @property
    def total_cached(self) -> int:
        return sum(self._cached.values())

    @property
    def cache_hit_rate(self) -> float:
        return self.total_cached / self.total if self.total else 0.0


# --- the router --------------------------------------------------------------


class LLMClient:
    """Routes one purpose to a model, or to its terminal. Never to an error."""

    def __init__(
        self,
        cfg: Config,
        *,
        providers: Mapping[str, Any] | None = None,
        sink: Callable[[LLMCallRecord], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.cfg = cfg
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(UTC))
        self._sink = sink
        self._providers: dict[str, Any] = dict(providers or {})
        self.tiers = {name: Tier(name, models) for name, models in TIERS.items()}
        # Keyed on ``quota_key``, so standard and deep share one counter for
        # the model they share. See ModelSpec.quota_key.
        self.health = {
            spec.quota_key: ModelHealth(spec.rpm_limit, spec.rpd_limit, monotonic=monotonic)
            for models in TIERS.values()
            for spec in models
        }
        self.cache = DiskCache(Path(cfg.llm_cache_dir), ttl_days=cfg.llm_cache_ttl_days)
        self.ledger = CallLedger()
        self._pins: dict[str, str] = {}
        self._context_caches: dict[str, str] = {}

    # -- providers ------------------------------------------------------------

    def _provider(self, name: str) -> Any:
        if name not in self._providers:
            if name == "gemini":
                from fc.llm.gemini import GeminiAdapter

                self._providers[name] = GeminiAdapter(self.cfg)
            elif name == "groq":
                from fc.llm.groq import GroqAdapter

                self._providers[name] = GroqAdapter(self.cfg)
            else:  # pragma: no cover - unreachable while Provider is a 2-member Literal
                raise ValueError(f"unknown provider {name!r}")
        return self._providers[name]

    # -- the call path (§7.2) -------------------------------------------------

    async def call(
        self,
        purpose: str,
        *,
        prompt: str,
        tenant_id: str,
        fallback: str | None = None,
        run_id: str | None = None,
        system: str | None = None,
        schema: type[BaseModel] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        pdf: bytes | None = None,
        requires: Capabilities = TEXT_ONLY,
        timeout_s: float = 30.0,
    ) -> LLMResult:
        """Serve ``purpose``, or terminate honestly. Never raises on failure.

        ``fallback`` is the deterministic output the caller would use anyway.
        Requiring it at the call site is what makes "every terminal produces
        usable output" true by construction rather than by intention.
        """
        prompt_hash = self._prompt_hash(purpose, prompt, system, pdf)
        key = DiskCache.key(
            tenant_id=tenant_id,
            purpose=purpose,
            prompt=prompt,
            system=system,
            schema_fingerprint=_schema_fingerprint(schema),
            prompt_hash=prompt_hash,
            extra={"pdf": hashlib.sha256(pdf).hexdigest() if pdf else None},
        )

        # Cache lookup happens before selection, and never advances the cursor.
        if self.cfg.llm_mode != "off":
            hit = self.cache.get(tenant_id, key)
            if hit is not None:
                self.ledger.record(run_id, cached=True)
                self._log(hit, purpose, prompt_hash, tenant_id, run_id, "ok")
                return hit

        if self.cfg.llm_mode != "live":
            # Guard (§7.3): demo-day quota exhaustion. ``cache_only`` serves a
            # hit and terminates on a miss, so a rehearsal costs nothing —
            # pre-warm by running the demo once on ``live`` and every later
            # run reads from disk. ``off`` terminates everything, which is what
            # proves P7 in one environment variable.
            return self._terminate(purpose, fallback, prompt_hash, tenant_id, run_id)

        for step in TASK_ROUTE[purpose]:
            if step.startswith("TERMINAL:"):
                return self._terminate(purpose, fallback, prompt_hash, tenant_id, run_id)

            tier = self.tiers[step]
            pinned = self._pins.get(purpose) if purpose in CONTEXT_CACHED_PURPOSES else None
            # Guard (§7.3): infinite rotation. ``next_available`` bounds one
            # scan, but not the loop around it — and a schema failure
            # deliberately marks nothing unhealthy, so without this every model
            # stays selectable forever and a tier of models all returning
            # malformed JSON spins until the process is killed. One attempt per
            # model per tier per call is the bound that actually holds.
            attempted: set[str] = set()
            while (spec := tier.next_available(requires, self.health, pinned=pinned)) is not None:
                if spec.key in attempted:
                    break
                attempted.add(spec.key)
                result = await self._attempt(
                    spec,
                    tier,
                    purpose=purpose,
                    prompt=prompt,
                    system=system,
                    schema=schema,
                    tools=tools,
                    pdf=pdf,
                    timeout_s=timeout_s,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    prompt_hash=prompt_hash,
                    key=key,
                )
                if result is not None:
                    return result
                if pinned is not None:
                    # The pin exists for the context cache; once its model is
                    # unhealthy the cache is worthless anyway, so drop the pin
                    # and let this tier rotate normally.
                    pinned = None

        return self._terminate(purpose, fallback, prompt_hash, tenant_id, run_id)

    async def _attempt(
        self,
        spec: ModelSpec,
        tier: Tier,
        *,
        purpose: str,
        prompt: str,
        system: str | None,
        schema: type[BaseModel] | None,
        tools: Sequence[Mapping[str, Any]] | None,
        pdf: bytes | None,
        timeout_s: float,
        tenant_id: str,
        run_id: str | None,
        prompt_hash: str,
        key: str,
    ) -> LLMResult | None:
        """One model, once. ``None`` means "rotate"; it never means "retry me"."""
        health = self.health[spec.quota_key]
        position = tier.position_of(spec)
        t0 = self._monotonic()
        try:
            raw = await self._provider(spec.provider).generate(
                spec,
                prompt=prompt,
                system=system,
                schema=schema,
                tools=tools,
                pdf=pdf,
                cached_content=self._context_cache_name(purpose, spec),
                timeout_s=timeout_s,
            )
            if schema is not None:
                schema.model_validate_json(raw.text)  # validation is the gate
        except RateLimited as exc:
            # Guard (§7.3): Retry-After ignored. Parsed from the header where
            # present, 60 s where absent — retrying early only re-trips.
            health.trip(exc.retry_after or ModelHealth.DEFAULT_RATE_LIMIT_COOLDOWN_S)
            self._log_failure(spec, tier, purpose, prompt_hash, tenant_id, run_id, "rate_limited")
            return None
        except (TimeoutError_, ServerError):
            health.record_failure()
            self._log_failure(spec, tier, purpose, prompt_hash, tenant_id, run_id, "timeout")
            return None
        except (SchemaInvalid, ValidationError):
            # Rotate immediately and do NOT count this as a transient failure.
            # Retrying the same model with the same prompt will produce the same
            # malformed shape; a different model is the only thing that helps.
            self._log_failure(spec, tier, purpose, prompt_hash, tenant_id, run_id, "schema_fail")
            return None
        except SafetyBlocked:
            _LOG.warning("safety block from %s on %s; rotating", spec.key, purpose)
            self._log_failure(spec, tier, purpose, prompt_hash, tenant_id, run_id, "down")
            return None
        except AuthError:
            health.trip_for_session()
            _LOG.error(
                "auth failure for %s — tripped for this process. Check the API key.", spec.key
            )
            self._log_failure(spec, tier, purpose, prompt_hash, tenant_id, run_id, "down")
            return None
        except ConfigError as exc:
            health.trip_for_session()
            _LOG.error(
                "%s is not reachable on this account (%s) — tripped for this process. "
                "The model id in TIERS is wrong or the account lacks access; no amount of "
                "retrying will fix it.",
                spec.key,
                exc,
            )
            self._log_failure(spec, tier, purpose, prompt_hash, tenant_id, run_id, "down")
            return None

        health.record_success()
        latency_ms = int((self._monotonic() - t0) * 1000)
        # A purpose with a downstream check leaves ``verified`` unset and is not
        # cached here — only ``confirm()`` writes it. See HAS_DOWNSTREAM_CHECK.
        verified: bool | None = None if purpose in HAS_DOWNSTREAM_CHECK else True
        result = LLMResult(
            text=raw.text,
            purpose=purpose,
            provider=spec.provider,
            model=spec.model,
            tier=tier.name,
            ladder_position=position,
            cached=False,
            verified=verified,
            latency_ms=latency_ms,
            input_tokens=raw.input_tokens,
            output_tokens=raw.output_tokens,
            thinking_tokens=raw.thinking_tokens,
            cache_key=key,
        )
        if verified is True:
            self.cache.set(tenant_id, key, result)
        self.ledger.record(run_id, cached=False)
        self._log(result, purpose, prompt_hash, tenant_id, run_id, "ok")
        return result

    # -- downstream verification ---------------------------------------------

    def confirm(self, result: LLMResult, *, tenant_id: str, run_id: str | None = None) -> LLMResult:
        """The deterministic check agreed. Now — and only now — cache it.

        The single writer for purposes in :data:`HAS_DOWNSTREAM_CHECK`. Making
        the cache write unreachable from the parse path is what closes §7.3's
        cache-poisoning risk: a boolean flipped after the fact would leave the
        bad entry already on disk.
        """
        verified = result.model_copy(update={"verified": True})
        if not verified.cached and verified.cache_key:
            self.cache.set(tenant_id, verified.cache_key, verified)
        self._log(verified, result.purpose, "", tenant_id, run_id, "ok")
        return verified

    def reject(self, result: LLMResult, *, tenant_id: str, run_id: str | None = None) -> LLMResult:
        """The deterministic check disagreed. Log it; cache nothing."""
        rejected = result.model_copy(update={"verified": False})
        self._log(rejected, result.purpose, "", tenant_id, run_id, "ok")
        return rejected

    # -- terminals ------------------------------------------------------------

    def _terminate(
        self,
        purpose: str,
        fallback: str | None,
        prompt_hash: str,
        tenant_id: str,
        run_id: str | None,
    ) -> LLMResult:
        name = TASK_ROUTE[purpose][-1].removeprefix("TERMINAL:")
        text = TERMINALS[name](purpose, fallback)
        result = LLMResult(
            text=text,
            purpose=purpose,
            provider="none",
            model=f"terminal:{name}",
            tier="terminal",
            ladder_position=len(TASK_ROUTE[purpose]) - 1,
            terminal=True,
            verified=True,
        )
        self.ledger.record(run_id, cached=False)
        self._log(result, purpose, prompt_hash, tenant_id, run_id, "terminal")
        return result

    # -- observability (§7.11) ------------------------------------------------

    def health_snapshot(self) -> dict[str, Any]:
        tiers: dict[str, list[dict[str, Any]]] = {}
        for name, models in TIERS.items():
            rows: list[dict[str, Any]] = []
            for spec in models:
                h = self.health[spec.quota_key]
                rows.append(
                    {
                        "model": spec.model,
                        "provider": spec.provider,
                        "thinking": spec.thinking,
                        # Two tiers can hold one model; this says which rows
                        # are looking at the same bucket.
                        "quota_key": spec.quota_key,
                        "available": h.available(),
                        "rpm_used": h.rpm_used,
                        "rpm_limit": h.rpm_limit,
                        "rpd_used": h.day_count,
                        "rpd_limit": h.rpd_limit,
                        "cooldown_remaining_s": (
                            None
                            if not h.tripped or h.cooldown_until is None
                            else (
                                None
                                if h.cooldown_until == math.inf
                                else round(h.cooldown_until - self._monotonic(), 1)
                            )
                        ),
                        "tripped": h.tripped,
                    }
                )
            tiers[name] = rows
        return {
            "tiers": tiers,
            "budget": self.budget(),
            "mode": self.cfg.llm_mode,
            "degraded": self.degraded,
            # Guard (§7.3): quota undercount. Stated in the API, not only in a
            # docstring, so "how does this scale" has an honest answer on screen.
            "health_scope": "process",
        }

    def budget(self) -> dict[str, Any]:
        """Daily request budget, deduplicated by quota bucket.

        The Flash models allow twenty requests a day *each*, so on demo day the
        question is not "is anything broken" but "how many calls do I have
        left" — and the answer has to be visible at a glance rather than
        inferred from four tier listings that repeat the same model twice.

        Rows are keyed on ``quota_key``, so ``gemini-3.6-flash`` appears once
        even though ``standard`` and ``deep`` both route to it.
        """
        seen: dict[str, ModelSpec] = {}
        for models in TIERS.values():
            for spec in models:
                seen.setdefault(spec.quota_key, spec)

        per_model: list[dict[str, Any]] = []
        for quota_key, spec in seen.items():
            h = self.health[quota_key]
            per_model.append(
                {
                    "model": spec.model,
                    "provider": spec.provider,
                    "rpd_used": h.day_count,
                    "rpd_limit": spec.rpd_limit,
                    # What the router will actually use before failing over —
                    # the headroom margin is the real ceiling, not the limit.
                    "rpd_usable": int(spec.rpd_limit * ModelHealth.RPD_HEADROOM),
                    "rpd_remaining": max(
                        0, int(spec.rpd_limit * ModelHealth.RPD_HEADROOM) - h.day_count
                    ),
                    "rpm_used": h.rpm_used,
                    "rpm_limit": spec.rpm_limit,
                    "available": h.available(),
                }
            )
        per_model.sort(key=lambda r: (r["provider"], r["model"]))
        return {
            "models": per_model,
            "requests_remaining_today": sum(r["rpd_remaining"] for r in per_model),
            "gemini_requests_remaining_today": sum(
                r["rpd_remaining"] for r in per_model if r["provider"] == "gemini"
            ),
        }

    @property
    def degraded(self) -> bool:
        """Guard (§7.3): silent degradation. True whenever prose is running on
        something other than its first choice — including both offline modes,
        which are degraded on purpose and should still say so."""
        if self.cfg.llm_mode != "live":
            return True
        return any(h.tripped for h in self.health.values())

    # -- context caching (§7.6) ----------------------------------------------

    def _context_cache_name(self, purpose: str, spec: ModelSpec) -> str | None:
        if purpose not in CONTEXT_CACHED_PURPOSES:
            return None
        return self._context_caches.get(spec.model)

    async def refresh_context_cache(self) -> str | None:
        """Create or refresh the text-to-SQL context cache — the scheduler's
        55-minute job against a 1 h TTL (§7.6).

        The ~8k-token system prompt (schema, semantics, twenty examples) is
        reused on every question, so caching it explicitly is most of the input
        cost of the Ask tab. Pins ``text_to_sql`` to whichever model the cache
        was created against, because an explicit cache does not apply to any
        other model.
        """
        if self.cfg.llm_mode != "live":
            return None
        spec = TIERS["standard"][0]
        try:
            name: str = await self._provider(spec.provider).create_context_cache(
                spec,
                system=load_prompt("sql_system"),
                ttl_seconds=self.cfg.gemini_context_cache_ttl,
            )
        except LLMError as exc:
            _LOG.warning("context cache refresh failed (%s); calls fall back to full rate", exc)
            return None
        self._context_caches[spec.model] = name
        self._pins["text_to_sql"] = spec.key
        return name

    # -- logging --------------------------------------------------------------

    def _prompt_hash(self, purpose: str, prompt: str, system: str | None, pdf: bytes | None) -> str:
        h = hashlib.sha256()
        h.update(purpose.encode("utf-8"))
        h.update(prompt.encode("utf-8"))
        h.update((system or "").encode("utf-8"))
        if pdf:
            h.update(hashlib.sha256(pdf).digest())
        return h.hexdigest()[:32]

    def _log(
        self,
        result: LLMResult,
        purpose: str,
        prompt_hash: str,
        tenant_id: str,
        run_id: str | None,
        outcome: str,
    ) -> None:
        self._emit(
            LLMCallRecord(
                tenant_id=tenant_id,
                run_id=run_id,
                purpose=purpose,
                provider=result.provider,
                model=result.model,
                tier=result.tier,
                ladder_position=result.ladder_position,
                prompt_hash=prompt_hash,
                cached=result.cached,
                outcome=outcome,
                verified=result.verified,
                latency_ms=result.latency_ms,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                thinking_tokens=result.thinking_tokens,
                created_at=self._now(),
            )
        )

    def _log_failure(
        self,
        spec: ModelSpec,
        tier: Tier,
        purpose: str,
        prompt_hash: str,
        tenant_id: str,
        run_id: str | None,
        outcome: str,
    ) -> None:
        self._emit(
            LLMCallRecord(
                tenant_id=tenant_id,
                run_id=run_id,
                purpose=purpose,
                provider=spec.provider,
                model=spec.model,
                tier=tier.name,
                ladder_position=tier.position_of(spec),
                prompt_hash=prompt_hash,
                cached=False,
                outcome=outcome,
                verified=None,
                created_at=self._now(),
            )
        )

    def _emit(self, record: LLMCallRecord) -> None:
        if self._sink is None:
            return
        try:
            self._sink(record)
        except Exception:  # noqa: BLE001 - observability must never fail a call
            _LOG.exception("llm_calls sink raised; call itself is unaffected")


def _schema_fingerprint(schema: type[BaseModel] | None) -> str:
    if schema is None:
        return "none"
    return hashlib.sha256(
        json.dumps(schema.model_json_schema(), sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
