"""The conversational Ask tab's central claim: a follow-up resolves its
referent from conversation history and then asks *fresh* SQL — it never
answers by filtering the previous turn's numbers in its head.

Proven the only way that actually proves it: the underlying data changes
between two turns, and the second turn's answer must reflect the new state,
not the first turn's cached count. If the system re-read the previous
answer instead of re-querying, this test would see the stale number.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from fc.config import load_config
from fc.llm.client import LLMClient, RawResponse
from tests.integration.conftest import ADMIN, purge, run

asyncpg = pytest.importorskip("asyncpg", reason="asyncpg is not installed")

_AT = datetime(2026, 8, 29, tzinfo=UTC)
_TENANT = "t_agent_ask"
_USER = "u_agent_ask"
_RUN = "run_agent_ask"
_JWT_ALGORITHM = "HS256"
_TENANTS = (_TENANT,)

_OPEN_COUNT_SQL = (
    "SELECT COUNT(*) AS open_count FROM exceptions "
    "WHERE status IN ('open','monitoring','snoozed','escalated')"
)
_SQL_PLAN = {"answerable": True, "sql": _OPEN_COUNT_SQL, "reason": None}
# Deliberately states a number the facts never gave it, so `is_grounded`
# rejects it and the deterministic fallback (built straight from the SQL
# rows) is what the test actually inspects — the point being tested is SQL
# re-execution, not narration, and this keeps the two independent.
_UNGROUNDED_NARRATIVE = {"narrative": "an invented ₹999,999 figure the facts never stated"}


class SequencedProvider:
    """Returns each queued response once, in order — one per LLM call, so a
    test can assert on the Nth call precisely rather than a single canned
    reply for the whole conversation."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def generate(self, spec: Any, **kwargs: Any) -> RawResponse:
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        assert index < len(self.responses), "more LLM calls than the test queued responses for"
        return RawResponse(text=json.dumps(self.responses[index]))


def _stub_client(tmp_dir: str, provider: SequencedProvider) -> LLMClient:
    from api.deps import get_llm_buffer

    cfg = load_config().model_copy(update={"llm_cache_dir": tmp_dir, "llm_mode": "live"})
    return LLMClient(
        cfg, providers={"gemini": provider, "groq": provider}, sink=get_llm_buffer().sink
    )


def _run_async[T](
    body: Callable[[Any, AsyncClient], Awaitable[T]], provider: SequencedProvider
) -> T:
    from api.deps import get_llm_client
    from api.main import app

    async def main() -> T:
        conn = ADMIN
        await _seed(conn)
        with tempfile.TemporaryDirectory() as tmp:
            app.dependency_overrides[get_llm_client] = lambda: _stub_client(tmp, provider)
            try:
                transport = ASGITransport(app=app)
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    return await body(conn, client)
            finally:
                app.dependency_overrides.pop(get_llm_client, None)
                await purge(conn, _TENANTS)

    return cast("T", run(main))


async def _seed(conn: Any) -> None:
    await purge(conn, _TENANTS)
    await conn.execute(
        "INSERT INTO tenants (tenant_id, name, status) VALUES ($1, 'agent ask test', 'active')",
        _TENANT,
    )
    await conn.execute(
        "INSERT INTO users (user_id, tenant_id, email, display_name, role, status) "
        "VALUES ($1, $2, $3, $1, 'owner', 'active')",
        _USER,
        _TENANT,
        f"{_USER}@example.invalid",
    )
    await conn.execute(
        "INSERT INTO runs (run_id, tenant_id, triggered_by, status, ruleset_hash, "
        "input_hashes, config) "
        "VALUES ($1, $2, $3, 'complete', 'deadbeef', '{}'::jsonb, '{}'::jsonb)",
        _RUN,
        _TENANT,
        _USER,
    )
    for i in range(2):
        exception_id = f"exc_agent_ask_{i}"
        event_id = f"evt_agent_ask_{i}"
        await conn.execute(
            "INSERT INTO transaction_events (event_id, run_id, tenant_id, source, "
            "source_row_id, amount_paise, direction, txn_date, raw_narration, raw) "
            "VALUES ($1, $2, $3, 'bank', $1, 10000, 'credit', $4, 'test row', '{}'::jsonb)",
            event_id,
            _RUN,
            _TENANT,
            _AT.date(),
        )
        await conn.execute(
            "INSERT INTO exceptions (exception_id, run_id, tenant_id, event_ids, category, "
            "amount_paise, residual_paise, confidence, tier, priority_score, "
            "recommended_action, status, signature, created_at) "
            "VALUES ($1, $2, $3, $4, 'amount_variance', 10000, 10000, 0.9, 'monitor', "
            "0.5, 'review', 'open', $1, $5)",
            exception_id,
            _RUN,
            _TENANT,
            [event_id],
            _AT,
        )


def _headers() -> dict[str, str]:
    cfg = load_config()
    if not cfg.jwt_secret:
        pytest.skip("no JWT_SECRET configured")
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": _USER,
            "tenant_id": _TENANT,
            "role": "owner",
            "email": f"{_USER}@example.invalid",
            "display_name": _USER,
            "typ": "access",
            "iat": now,
            "exp": now.replace(year=now.year + 1),
        },
        cfg.jwt_secret,
        algorithm=_JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def test_a_follow_up_reflects_fresh_data_not_the_previous_turns_cached_number() -> None:
    """Turn 1 asks how many exceptions are open (2, seeded). Before turn 2,
    a third one opens directly in the database — out of band, the way a
    concurrent user's action would. Turn 2 asks the identical question
    again as a "follow-up". If the system answered from conversation memory
    (re-reading turn 1's "2") the test would see 2 again; it must see 3,
    because each turn is required to run its own fresh query.
    """
    provider = SequencedProvider(
        [_SQL_PLAN, _UNGROUNDED_NARRATIVE, _SQL_PLAN, _UNGROUNDED_NARRATIVE]
    )

    async def body(conn: Any, client: AsyncClient) -> None:
        r1 = await client.post(
            "/api/v1/agent/ask",
            json={"question": "How many exceptions are open?"},
            headers=_headers(),
        )
        assert r1.status_code == 200, r1.text
        out1 = r1.json()
        assert out1["answerable"] is True
        assert out1["tool"] == "sql"
        assert int(out1["rows"][0]["open_count"]) == 2

        # The world moves between turns.
        await conn.execute(
            "INSERT INTO transaction_events (event_id, run_id, tenant_id, source, "
            "source_row_id, amount_paise, direction, txn_date, raw_narration, raw) "
            "VALUES ('evt_agent_ask_2', $1, $2, 'bank', 'evt_agent_ask_2', 10000, "
            "'credit', $3, 'test row', '{}'::jsonb)",
            _RUN,
            _TENANT,
            _AT.date(),
        )
        await conn.execute(
            "INSERT INTO exceptions (exception_id, run_id, tenant_id, event_ids, category, "
            "amount_paise, residual_paise, confidence, tier, priority_score, "
            "recommended_action, status, signature, created_at) "
            "VALUES ('exc_agent_ask_2', $1, $2, ARRAY['evt_agent_ask_2'], 'amount_variance', "
            "10000, 10000, 0.9, 'monitor', 0.5, 'review', 'open', 'exc_agent_ask_2', $3)",
            _RUN,
            _TENANT,
            _AT,
        )

        history = [{"question": "How many exceptions are open?", "answer": out1["answer"]}]
        r2 = await client.post(
            "/api/v1/agent/ask",
            json={"question": "How many exceptions are open?", "history": history},
            headers=_headers(),
        )
        assert r2.status_code == 200, r2.text
        out2 = r2.json()
        assert out2["answerable"] is True
        assert int(out2["rows"][0]["open_count"]) == 3
        assert out2["rows"][0]["open_count"] != out1["rows"][0]["open_count"]

        # Both SQL-generation calls actually ran (not served from cache) —
        # a cache hit here would mean the second turn never asked the model
        # anything, and the freshness this test proves would be accidental.
        assert len(provider.calls) == 4

    _run_async(body, provider)


def test_diff_intent_routes_to_the_diff_tool_not_sql() -> None:
    """ "What changed since the last run" must never reach text_to_sql at
    all — logged as tool="diff", and the stub queue proves it: if this
    routed to SQL it would consume the SqlPlan response and fail schema
    validation against NarrativeOut, or vice versa.
    """
    provider = SequencedProvider([_UNGROUNDED_NARRATIVE])

    async def body(conn: Any, client: AsyncClient) -> None:
        # A second, later run so there are two runs to diff.
        await conn.execute(
            "INSERT INTO runs (run_id, tenant_id, triggered_by, status, ruleset_hash, "
            "input_hashes, config) "
            "VALUES ('run_agent_ask_2', $1, $2, 'complete', 'deadbeef', '{}'::jsonb, '{}'::jsonb)",
            _TENANT,
            _USER,
        )
        r = await client.post(
            "/api/v1/agent/ask",
            json={"question": "What changed since the last run?"},
            headers=_headers(),
        )
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["tool"] == "diff"
        assert out["compared_from_run_id"] is not None
        assert out["compared_to_run_id"] is not None
        assert out["sql"] is None
        # Exactly one call — sql_narrate only, never text_to_sql.
        assert len(provider.calls) == 1

    _run_async(body, provider)
