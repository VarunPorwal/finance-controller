"""The provider adapters — PRD §7.4, §7.5.

Two things are worth testing here and the rest is request-building.

**Failure classification.** The router's whole design turns on telling a 429
carrying ``Retry-After`` apart from a timeout, a 5xx, a safety block and a
schema failure (§7.2). That mapping is the reason these adapters are
hand-written rather than SDK calls, so it is the thing to prove.

**Schema conversion.** Gemini's OpenAPI subset has no ``$ref``, no ``$defs`` and
no ``anyOf``; Pydantic emits all three. A schema Gemini rejects comes back as a
400, which the router classifies as a schema failure on *every* model in the
tier — so getting this wrong looks like an outage rather than a bug, and would
be diagnosed as one.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from fc.llm.client import (
    AuthError,
    ConfigError,
    RateLimited,
    SafetyBlocked,
    SchemaInvalid,
    ServerError,
    TimeoutError_,
)
from fc.llm.gemini import _classify, _declaration_to_gemini, _read_response, to_gemini_schema
from fc.llm.groq import _read_response as _groq_read
from fc.llm.schemas import ExtractionOut, PdfRow, SqlPlan
from fc.models.command import CreateRuleCommand, ResolveCommand


def _response(
    status: int, *, headers: dict[str, str] | None = None, body: str = ""
) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        text=body,
        request=httpx.Request("POST", "https://example.invalid"),
    )


# --- failure classification (§7.2) -------------------------------------------


def test_a_429_becomes_rate_limited_and_carries_its_retry_after() -> None:
    with pytest.raises(RateLimited) as caught:
        _classify(_response(429, headers={"retry-after": "45"}))
    assert caught.value.retry_after == 45.0


def test_an_http_date_retry_after_is_understood_too() -> None:
    """Both header forms are legal and providers use both. Misreading one means
    retrying early and re-tripping the model."""
    when = datetime.now(UTC) + timedelta(seconds=30)
    header = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
    with pytest.raises(RateLimited) as caught:
        _classify(_response(429, headers={"retry-after": header}))
    assert caught.value.retry_after is not None
    assert 20 <= caught.value.retry_after <= 40


def test_a_429_with_no_header_leaves_the_default_to_the_router() -> None:
    with pytest.raises(RateLimited) as caught:
        _classify(_response(429))
    assert caught.value.retry_after is None


def test_a_nonsense_retry_after_is_ignored_rather_than_crashing() -> None:
    with pytest.raises(RateLimited) as caught:
        _classify(_response(429, headers={"retry-after": "soon"}))
    assert caught.value.retry_after is None


@pytest.mark.parametrize("status", [401, 403])
def test_an_auth_status_becomes_an_auth_error(status: int) -> None:
    """Configuration, not load — the router trips these for the session."""
    with pytest.raises(AuthError):
        _classify(_response(status))


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_a_5xx_becomes_a_server_error(status: int) -> None:
    with pytest.raises(ServerError):
        _classify(_response(status))


def test_a_408_becomes_a_timeout() -> None:
    with pytest.raises(TimeoutError_):
        _classify(_response(408))


def test_a_400_becomes_a_schema_failure_so_the_router_rotates_rather_than_retries() -> None:
    with pytest.raises(SchemaInvalid):
        _classify(_response(400, body="Invalid JSON payload received"))


def test_a_413_too_large_is_a_rate_limit_not_a_schema_failure() -> None:
    """Groq's tokens-per-minute ceiling arrives as a 413 whose body says
    ``rate_limit_exceeded`` — a quota condition wearing a payload-size status
    code.

    Regression test for a real one: with 8192 reserved for output, the
    command-parse request came to 10392 tokens against an 8000 TPM limit and was
    refused before it ran. Classified as a schema failure it rotated without
    tripping, so both fallback models were asked the same over-large question
    in turn and the log blamed the schema.
    """
    body = (
        '{"error":{"message":"Request too large for model `openai/gpt-oss-120b` ... on '
        'tokens per minute (TPM): Limit 8000, Requested 10392","code":"rate_limit_exceeded"}}'
    )
    with pytest.raises(RateLimited) as caught:
        _classify(_response(413, headers={"retry-after": "12"}, body=body))
    assert caught.value.retry_after == 12.0


def test_the_groq_output_reservation_leaves_room_for_the_prompt() -> None:
    """Groq counts requested ``max_tokens`` toward TPM, not tokens produced, so
    an over-generous reservation is spent whether or not it is used."""
    from fc.llm.groq import MAX_OUTPUT_TOKENS

    assert MAX_OUTPUT_TOKENS <= 4096, "the reservation is large enough to trip the 8000 TPM cap"


def test_a_404_model_not_found_is_a_config_error_not_a_schema_failure() -> None:
    """A dead model id and a rejected schema want opposite treatment.

    Regression test for a real one: the fallback tier shipped naming a Groq
    model this account cannot reach, and the 404 was classified as
    ``schema_fail`` — which rotates without tripping, so every later call paid
    full latency to rediscover the same dead endpoint, and the log said
    "schema failure" about a configuration mistake.
    """
    body = (
        '{"error":{"message":"The model `llama-3.3-70b-versatile` does not exist or you '
        'do not have access to it.","code":"model_not_found"}}'
    )
    with pytest.raises(ConfigError) as caught:
        _classify(_response(404, body=body))
    assert "model_not_found" in str(caught.value)
    assert not isinstance(caught.value, SchemaInvalid)


def test_a_2xx_classifies_as_nothing() -> None:
    _classify(_response(200))


# --- reading a response ------------------------------------------------------


def test_a_prompt_level_safety_block_is_recognised() -> None:
    with pytest.raises(SafetyBlocked):
        _read_response({"promptFeedback": {"blockReason": "SAFETY"}}, expect_function_call=False)


def test_a_candidate_level_safety_block_is_recognised() -> None:
    with pytest.raises(SafetyBlocked):
        _read_response(
            {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]},
            expect_function_call=False,
        )


def test_an_empty_response_is_a_schema_failure_not_an_empty_string() -> None:
    """An empty answer that reached the caller would validate as nothing and be
    cached as nothing."""
    with pytest.raises(SchemaInvalid):
        _read_response(
            {"candidates": [{"content": {"parts": [{"text": "   "}]}}]},
            expect_function_call=False,
        )
    with pytest.raises(SchemaInvalid):
        _read_response({"candidates": []}, expect_function_call=False)


def test_a_function_call_is_returned_as_json_never_executed() -> None:
    """§7.5's single most important sentence, at the adapter boundary: the call
    is rendered as data, and the router validates it like any other response."""
    raw = _read_response(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"functionCall": {"name": "resolve", "args": {"exception_id": "x"}}}
                        ]
                    }
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 4},
        },
        expect_function_call=True,
    )
    assert json.loads(raw.text) == {"name": "resolve", "args": {"exception_id": "x"}}
    assert raw.input_tokens == 10


def test_a_missing_function_call_is_a_schema_failure() -> None:
    with pytest.raises(SchemaInvalid):
        _read_response(
            {"candidates": [{"content": {"parts": [{"text": "I would rather chat"}]}}]},
            expect_function_call=True,
        )


def test_groq_normalises_a_tool_call_into_the_same_envelope() -> None:
    """The router and the command validator never learn which provider
    answered, which is what makes the fallback tier a real fallback."""
    raw = _groq_read(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "resolve",
                                    "arguments": '{"exception_id": "x"}',
                                }
                            }
                        ]
                    }
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        },
        expect_tool_call=True,
    )
    assert json.loads(raw.text) == {"name": "resolve", "args": {"exception_id": "x"}}
    assert raw.thinking_tokens is None


def test_groq_tool_arguments_that_are_not_json_are_a_schema_failure() -> None:
    with pytest.raises(SchemaInvalid):
        _groq_read(
            {"choices": [{"message": {"tool_calls": [{"function": {"arguments": "{oops"}}]}}]},
            expect_tool_call=True,
        )


# --- schema conversion (§7.4) ------------------------------------------------


@pytest.mark.parametrize("model", [ExtractionOut, SqlPlan, PdfRow])
def test_a_converted_schema_carries_nothing_geminis_subset_rejects(model: Any) -> None:
    blob = json.dumps(to_gemini_schema(model))
    for forbidden in ("$ref", "$defs", "anyOf", "allOf", "oneOf", "additionalProperties"):
        assert forbidden not in blob, f"{model.__name__} still emits {forbidden}"


def test_types_are_uppercased_into_the_openapi_dialect() -> None:
    schema = to_gemini_schema(PdfRow)
    assert schema["type"] == "OBJECT"
    assert schema["properties"]["narration"]["type"] == "STRING"


def test_an_optional_field_becomes_nullable_rather_than_a_union() -> None:
    """``str | None`` is ``anyOf[string, null]`` in JSON Schema and has no
    equivalent here — it has to collapse, and it has to collapse to the branch
    that is not null."""
    field = to_gemini_schema(PdfRow)["properties"]["value_date"]
    assert field["type"] == "STRING"
    assert field["nullable"] is True
    assert "value date" in field["description"]


def test_property_order_is_deterministic_so_the_cache_fingerprint_is_stable() -> None:
    first = json.dumps(to_gemini_schema(ExtractionOut))
    second = json.dumps(to_gemini_schema(ExtractionOut))
    assert first == second
    assert to_gemini_schema(PdfRow)["propertyOrdering"] == sorted(
        to_gemini_schema(PdfRow)["properties"]
    )


def test_a_nested_command_declaration_is_fully_inlined() -> None:
    """``create_rule`` is the deep one: RuleDraft nests Scope, Deduction and
    Tolerance, so it is three levels of ``$ref`` before conversion."""
    declaration = {
        "name": "create_rule",
        "description": "Draft a deduction rule.",
        "parameters": {
            "type": "object",
            "properties": CreateRuleCommand.model_json_schema()["properties"],
            "required": ["rule_draft"],
            "$defs": CreateRuleCommand.model_json_schema()["$defs"],
        },
    }
    blob = json.dumps(_declaration_to_gemini(declaration))
    for forbidden in ("$ref", "$defs", "anyOf"):
        assert forbidden not in blob, f"the declaration still emits {forbidden}"
    assert '"STRING"' in blob


def test_a_flat_declaration_survives_conversion_unchanged_in_meaning() -> None:
    schema = ResolveCommand.model_json_schema()
    declaration = {
        "name": "resolve",
        "description": "Close one exception.",
        "parameters": {
            "type": "object",
            "properties": {k: v for k, v in schema["properties"].items() if k != "verb"},
            "required": [r for r in schema.get("required", []) if r != "verb"],
        },
    }
    converted = _declaration_to_gemini(declaration)
    assert set(converted["parameters"]["properties"]) == {"exception_id", "category", "reason"}
    assert "verb" not in converted["parameters"]["properties"], (
        "the discriminator was offered to the model to fill in"
    )
