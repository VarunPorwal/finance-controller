"""Groq adapter — the fallback tier, hand-written against the OpenAI-compatible
chat completions API.

Text tasks only. ``multimodal=False`` on its :class:`ModelSpec`, so the
capability gate in ``fc.llm.client.Tier.next_available`` keeps it off
``pdf_extract`` structurally rather than by anyone remembering to.

Same reasoning as the Gemini adapter for not using the SDK: the router needs
the HTTP status, and 429 here carries a ``retry-after`` header that is the
difference between an invisible failover and a visible one.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import BaseModel

from fc.config import Config
from fc.llm.client import RawResponse, SchemaInvalid
from fc.llm.gemini import _classify  # the status taxonomy is provider-independent
from fc.llm.schemas import ModelSpec

__all__ = ["GroqAdapter"]

_BASE_URL = "https://api.groq.com/openai/v1"

#: Groq's free tier caps *tokens per minute* at 8000, and it counts the
#: requested ``max_tokens`` toward that ceiling rather than the tokens actually
#: produced. The command-parse prompt is around 2.2k tokens with the fourteen
#: declarations attached, so reserving 8192 for output put the request at 10392
#: and it was refused with a 413 before it ever ran.
#:
#: Every response this router asks for is a small structured object — a command,
#: a SQL plan, a paragraph — so a large reservation was never buying anything.
#: Sized to leave comfortable room for the prompt instead.
MAX_OUTPUT_TOKENS = 2048


class GroqAdapter:
    def __init__(self, cfg: Config, *, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = cfg.groq_api_key
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
        from fc.llm.client import AuthError, ServerError, TimeoutError_

        if not self._api_key:
            raise AuthError("GROQ_API_KEY is not set")
        if pdf is not None:  # pragma: no cover - the capability gate prevents this
            raise SchemaInvalid("groq models are not multimodal")

        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": spec.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        if tools:
            body["tools"] = [
                {"type": "function", "function": dict(declaration)} for declaration in tools
            ]
            body["tool_choice"] = "required"
        elif schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "strict": True,
                    "schema": schema.model_json_schema(),
                },
            }

        try:
            response = await self._client.post(
                "/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
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
        return _read_response(payload, expect_tool_call=bool(tools))


def _read_response(payload: Mapping[str, Any], *, expect_tool_call: bool) -> RawResponse:
    choices = payload.get("choices") or []
    if not choices:
        raise SchemaInvalid("no choices in response")
    message = choices[0].get("message") or {}

    if expect_tool_call:
        calls = message.get("tool_calls") or []
        if not calls:
            raise SchemaInvalid("expected a tool call, got none")
        function = calls[0].get("function") or {}
        try:
            args = json.loads(function.get("arguments") or "{}")
        except ValueError as exc:
            raise SchemaInvalid(f"tool call arguments were not JSON: {exc}") from exc
        # Normalised into the same envelope the Gemini adapter emits, so the
        # router and the command validator never learn which provider answered.
        return RawResponse(
            text=json.dumps({"name": function.get("name"), "args": args}), **_usage(payload)
        )

    text = message.get("content") or ""
    if not text.strip():
        raise SchemaInvalid("empty response text")
    return RawResponse(text=text, **_usage(payload))


def _usage(payload: Mapping[str, Any]) -> dict[str, int | None]:
    usage = payload.get("usage") or {}
    return {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "thinking_tokens": None,
    }
