"""Gemini adapter — hand-written against the Generative Language REST API.

Not the SDK, deliberately. The router's whole design turns on telling a 429
carrying ``Retry-After`` apart from a timeout, a 5xx, a safety block, an auth
failure and a schema failure, and treating each differently (§7.2). An SDK
folds those into its own exception hierarchy, and unwrapping them back to an
HTTP status is more code than the request builder below.

Four API surfaces are used and no others:

* ``models/{model}:generateContent`` — every call
* ``generationConfig.responseSchema`` — structured output (§7.4)
* ``tools[].functionDeclarations`` — the command layer (§7.5)
* ``cachedContents`` — the text-to-SQL context cache (§7.6)
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping, Sequence
from email.utils import parsedate_to_datetime
from typing import Any, cast

import httpx
from pydantic import BaseModel

from fc.config import Config
from fc.llm.client import (
    AuthError,
    RateLimited,
    RawResponse,
    SafetyBlocked,
    SchemaInvalid,
    ServerError,
    TimeoutError_,
)
from fc.llm.schemas import ModelSpec

__all__ = ["GeminiAdapter", "to_gemini_schema"]

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: Keywords Gemini's OpenAPI subset accepts. Pydantic emits a good deal more.
_ALLOWED_SCHEMA_KEYS = frozenset(
    {
        "type",
        "format",
        "description",
        "nullable",
        "enum",
        "items",
        "properties",
        "required",
        "propertyOrdering",
    }
)

_TYPE_MAP = {
    "string": "STRING",
    "integer": "INTEGER",
    "number": "NUMBER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}


def to_gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model's JSON Schema to Gemini's OpenAPI subset.

    The subset has no ``$ref`` and no ``$defs``, so nested models must be
    inlined, and it rejects unknown keywords rather than ignoring them — which
    is why unsupported keys are stripped rather than passed through. A schema
    Gemini rejects is a 400, which the router would classify as a permanent
    failure on every model in the tier, so getting this wrong looks like an
    outage rather than a bug.
    """
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    return cast("dict[str, Any]", _convert(raw, defs))


def _convert(node: Any, defs: Mapping[str, Any]) -> Any:
    if isinstance(node, list):
        return [_convert(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        name = str(node["$ref"]).rsplit("/", 1)[-1]
        return _convert(dict(defs[name]), defs)

    # `str | None` becomes anyOf[{type: string}, {type: null}] — Gemini has no
    # anyOf, so collapse to the non-null branch and mark it nullable.
    if "anyOf" in node:
        branches = [b for b in node["anyOf"] if b.get("type") != "null"]
        nullable = len(branches) != len(node["anyOf"])
        if len(branches) == 1:
            converted = _convert(dict(branches[0]), defs)
            if isinstance(converted, dict):
                if nullable:
                    converted["nullable"] = True
                if "description" in node:
                    converted.setdefault("description", node["description"])
            return converted
        # A genuine union of two non-null shapes has no representation here.
        return {"type": "STRING", "description": node.get("description", "")}

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key not in _ALLOWED_SCHEMA_KEYS:
            continue
        if key == "type":
            out["type"] = _TYPE_MAP.get(str(value), "STRING")
        elif key in ("items", "properties"):
            out[key] = (
                {k: _convert(v, defs) for k, v in value.items()}
                if key == "properties"
                else _convert(value, defs)
            )
        else:
            out[key] = value
    if out.get("type") == "OBJECT" and "properties" in out:
        # Deterministic key order, so the same model always produces the same
        # schema bytes and therefore the same cache fingerprint.
        out["propertyOrdering"] = sorted(out["properties"])
    return out


def _declaration_to_gemini(declaration: Mapping[str, Any]) -> dict[str, Any]:
    """A function declaration's ``parameters`` from JSON Schema to Gemini's subset.

    Declarations are authored once, in standard JSON Schema, and each adapter
    translates. Groq takes them as they are; Gemini needs the OpenAPI dialect.
    Keeping the source form neutral is what stops the command set drifting into
    two definitions that disagree about which fields exist.
    """
    out = dict(declaration)
    parameters = out.get("parameters")
    if isinstance(parameters, dict):
        defs = parameters.get("$defs", {})
        out["parameters"] = _convert(dict(parameters), defs)
    return out


class GeminiAdapter:
    """One HTTP client, reused. Closed by the process, not per call."""

    def __init__(self, cfg: Config, *, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = cfg.gemini_api_key
        self._client = client or httpx.AsyncClient(base_url=_BASE_URL)

    async def generate(
        self,
        spec: ModelSpec,
        *,
        prompt: str,
        system: str | None = None,
        schema: type[BaseModel] | None = None,
        tools: Sequence[Mapping[str, Any]] | None = None,
        pdf: bytes | None = None,
        cached_content: str | None = None,
        timeout_s: float = 30.0,
    ) -> RawResponse:
        if not self._api_key:
            raise AuthError("GEMINI_API_KEY is not set")

        parts: list[dict[str, Any]] = []
        if pdf is not None:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": "application/pdf",
                        "data": base64.b64encode(pdf).decode("ascii"),
                    }
                }
            )
        parts.append({"text": prompt})

        generation_config: dict[str, Any] = {
            "temperature": 0,
            "maxOutputTokens": 8192,
        }
        if spec.thinking != "none":
            generation_config["thinkingConfig"] = {"thinkingLevel": spec.thinking}
        if schema is not None and not tools:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = to_gemini_schema(schema)

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
        }
        if tools:
            body["tools"] = [{"functionDeclarations": [_declaration_to_gemini(d) for d in tools]}]
            body["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
        if cached_content is not None:
            # The cache carries the system instruction; sending both is an error.
            body["cachedContent"] = cached_content
        elif system is not None:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        payload = await self._post(
            f"/models/{spec.model}:generateContent", body, timeout_s=timeout_s
        )
        return _read_response(payload, expect_function_call=bool(tools))

    async def create_context_cache(self, spec: ModelSpec, *, system: str, ttl_seconds: int) -> str:
        """§7.6. Returns the cache resource name to pass as ``cachedContent``."""
        if not self._api_key:
            raise AuthError("GEMINI_API_KEY is not set")
        body = {
            "model": f"models/{spec.model}",
            "systemInstruction": {"parts": [{"text": system}]},
            "ttl": f"{ttl_seconds}s",
        }
        payload = await self._post("/cachedContents", body, timeout_s=30.0)
        name = payload.get("name")
        if not isinstance(name, str):
            raise ServerError(f"cachedContents returned no name: {payload!r}")
        return name

    async def _post(
        self, path: str, body: Mapping[str, Any], *, timeout_s: float
    ) -> dict[str, Any]:
        try:
            response = await self._client.post(
                path,
                json=body,
                headers={"x-goog-api-key": self._api_key},
                timeout=timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError_(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ServerError(str(exc)) from exc

        _classify(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise SchemaInvalid(f"response was not JSON: {response.text[:200]!r}") from exc
        if not isinstance(payload, dict):
            raise SchemaInvalid(f"expected a JSON object, got {type(payload).__name__}")
        return payload


def _classify(response: httpx.Response) -> None:
    """HTTP status to the router's failure taxonomy (§7.2)."""
    status = response.status_code
    if status < 400:
        return
    if status == 429:
        raise RateLimited(response.text[:200], retry_after=_retry_after(response))
    if status in (401, 403):
        raise AuthError(f"{status}: {response.text[:200]}")
    if status >= 500:
        raise ServerError(f"{status}: {response.text[:200]}")
    if status == 408:
        raise TimeoutError_(response.text[:200])
    # 400 on a structured call is almost always a schema Gemini would not
    # accept. Rotating is right either way: retrying the same model with the
    # same body reproduces it exactly.
    raise SchemaInvalid(f"{status}: {response.text[:400]}")


def _retry_after(response: httpx.Response) -> float | None:
    """Both header forms: delta-seconds, and an HTTP-date."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    from datetime import UTC, datetime

    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _read_response(payload: Mapping[str, Any], *, expect_function_call: bool) -> RawResponse:
    if "promptFeedback" in payload and payload["promptFeedback"].get("blockReason"):
        raise SafetyBlocked(str(payload["promptFeedback"]["blockReason"]))

    candidates = payload.get("candidates") or []
    if not candidates:
        raise SchemaInvalid("no candidates in response")
    candidate = candidates[0]
    if candidate.get("finishReason") in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT"):
        raise SafetyBlocked(str(candidate.get("finishReason")))

    parts = candidate.get("content", {}).get("parts") or []
    if expect_function_call:
        for part in parts:
            call = part.get("functionCall")
            if call:
                # Rendered as JSON so the router validates it exactly like any
                # other structured response. It is never executed (§7.5).
                return RawResponse(
                    text=json.dumps({"name": call.get("name"), "args": call.get("args", {})}),
                    **_usage(payload),
                )
        raise SchemaInvalid("expected a function call, got none")

    text = "".join(part.get("text", "") for part in parts)
    if not text.strip():
        raise SchemaInvalid("empty response text")
    return RawResponse(text=text, **_usage(payload))


def _usage(payload: Mapping[str, Any]) -> dict[str, int | None]:
    usage = payload.get("usageMetadata") or {}
    return {
        "input_tokens": usage.get("promptTokenCount"),
        "output_tokens": usage.get("candidatesTokenCount"),
        "thinking_tokens": usage.get("thoughtsTokenCount"),
    }
