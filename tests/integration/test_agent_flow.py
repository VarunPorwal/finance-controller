"""parse -> preview -> confirm -> execute, against the real app and database.

The test that matters here is the last one. A preview is a promise that what
runs is what was shown; the moment state can move in between, "the human
approved this" is false unless somebody checks. So this file parses an
instruction, mutates the underlying exception out of band, and then confirms —
and the API must refuse and hand back the revised preview rather than carrying
out a plan nobody read.

The model is stubbed through FastAPI's dependency overrides. What is under test
is everything after it: the validator, the store, the re-validation, and the
fact that ``/agent/execute`` goes through the same endpoint a click does.
"""

from __future__ import annotations

import json
import tempfile
import time
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
_TENANT = "t_agent_flow"
_USER = "u_agent_flow"
_RUN = "run_agent_flow"
_EXC = "exc_agent_flow"
_BIG_EXC = "exc_agent_flow_big"
_CLUSTER = "cls_agent_flow"
_JWT_ALGORITHM = "HS256"
_TENANTS = (_TENANT,)
_BIG_AMOUNT = 5_200_000  # ₹52,000 — above the typed-confirmation threshold


def _require_jwt_secret() -> Any:
    cfg = load_config()
    if not cfg.jwt_secret:
        pytest.skip("no JWT_SECRET configured")
    return cfg


class StubProvider:
    """Returns whichever function call the test asked for."""

    def __init__(self, call: dict[str, Any]) -> None:
        self.call = call

    async def generate(self, spec: Any, **kwargs: Any) -> RawResponse:
        return RawResponse(text=json.dumps(self.call))


def _stub_client(tmp_dir: str, call: dict[str, Any]) -> LLMClient:
    """The real router, with a stub transport underneath it.

    Wired to the same ``LLMCallBuffer`` the app uses, so the ``llm_calls`` rows
    a real request would write are written here too — the observability path is
    part of what is under test, not scaffolding around it.
    """
    from api.deps import get_llm_buffer

    cfg = load_config().model_copy(update={"llm_cache_dir": tmp_dir, "llm_mode": "live"})
    provider = StubProvider(call)
    return LLMClient(
        cfg,
        providers={"gemini": provider, "groq": provider},
        sink=get_llm_buffer().sink,
    )


def _resolve_call(exception_id: str = _EXC) -> dict[str, Any]:
    return {
        "name": "resolve",
        "args": {
            "exception_id": exception_id,
            "category": "manual_refund",
            "reason": "manual refund done over the phone on the 14th",
        },
    }


def _run_async[T](body: Callable[[Any, AsyncClient], Awaitable[T]], call: dict[str, Any]) -> T:
    """One shared loop, one shared admin connection — see conftest.

    The engine cache is deliberately *not* cleared per test any more: with a
    single loop for the session the pool stays valid, and rebuilding it cost
    about a second of Singapore round trip every time.
    """
    from api.deps import get_llm_client
    from api.main import app
    from api.routers.agent import _COMMANDS

    _COMMANDS.clear()

    async def main() -> T:
        conn = ADMIN
        await _seed(conn)
        with tempfile.TemporaryDirectory() as tmp:
            app.dependency_overrides[get_llm_client] = lambda: _stub_client(tmp, call)
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
        "INSERT INTO tenants (tenant_id, name, status) VALUES ($1, 'agent flow', 'active')",
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
    for exception_id, amount in ((_EXC, 100_000), (_BIG_EXC, _BIG_AMOUNT)):
        event_id = f"evt_{exception_id}"
        await conn.execute(
            "INSERT INTO transaction_events (event_id, run_id, tenant_id, source, "
            "source_row_id, amount_paise, direction, txn_date, raw_narration, raw) "
            "VALUES ($1, $2, $3, 'bank', $1, $4, 'credit', $5, $6, '{}'::jsonb)",
            event_id,
            _RUN,
            _TENANT,
            amount,
            _AT.date(),
            f"NEFT CR:HDFC20262410009999/LUMEA RETAIL/INV-{exception_id}",
        )
        await conn.execute(
            "INSERT INTO exceptions (exception_id, run_id, tenant_id, event_ids, category, "
            "amount_paise, residual_paise, confidence, tier, priority_score, "
            "recommended_action, status, signature, created_at) "
            "VALUES ($1, $2, $3, $4, 'amount_variance', $5, $5, 0.9, 'monitor', "
            "0.5, 'review', 'open', 'sig', $6)",
            exception_id,
            _RUN,
            _TENANT,
            [event_id],
            amount,
            _AT,
        )


async def _cleanup(conn: Any) -> None:
    await purge(conn, _TENANTS)


def _headers() -> dict[str, str]:
    cfg = _require_jwt_secret()
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


async def _parse(client: AsyncClient, text: str = "close it, phone refund") -> Any:
    return await client.post(
        "/api/v1/agent/parse",
        json={"text": text, "context": {"run_id": _RUN}},
        headers=_headers(),
    )


# --- the happy path ----------------------------------------------------------


def test_parse_returns_a_preview_and_writes_nothing() -> None:
    async def body(conn: Any, client: AsyncClient) -> None:
        response = await _parse(client)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["command_id"].startswith("cmd_")
        assert payload["command"]["payload"]["verb"] == "resolve"
        assert payload["preview"]["effects"][0]["action"] == "exception.resolve"
        assert payload["preview"]["refusal"] is None

        status = await conn.fetchval("SELECT status FROM exceptions WHERE exception_id = $1", _EXC)
        assert status == "open", "parsing changed state"

    _run_async(body, _resolve_call())


def test_execute_resolves_through_the_same_endpoint_a_click_uses() -> None:
    async def body(conn: Any, client: AsyncClient) -> None:
        command_id = (await _parse(client)).json()["command_id"]
        response = await client.post(
            "/api/v1/agent/execute",
            json={"command_id": command_id, "confirmed": True},
            headers=_headers(),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["applied"] == [{"exception_id": _EXC, "ok": True, "detail": None}]
        assert payload["audit_seq"] is not None

        row = await conn.fetchrow(
            "SELECT status, resolved_by, resolved_via, resolution_category "
            "FROM exceptions WHERE exception_id = $1",
            _EXC,
        )
        assert row["status"] == "resolved"
        # §8.7: human-resolved items never count toward auto-resolution metrics.
        assert row["resolved_by"] == "human"
        assert row["resolution_category"] == "manual_refund"

        # §8.3: the audit event carries the operator's words verbatim.
        payloads = await conn.fetch(
            "SELECT action, payload FROM audit_events WHERE tenant_id = $1 ORDER BY seq", _TENANT
        )
        actions = [r["action"] for r in payloads]
        assert "exception.resolve" in actions
        assert "agent.execute" in actions
        agent_event = next(r for r in payloads if r["action"] == "agent.execute")
        assert json.loads(agent_event["payload"])["instruction_text"] == "close it, phone refund"

    _run_async(body, _resolve_call())


def test_execute_with_dry_run_previews_without_persisting() -> None:
    """Hard rule 7 applies to this endpoint like every other write endpoint."""

    async def body(conn: Any, client: AsyncClient) -> None:
        command_id = (await _parse(client)).json()["command_id"]
        response = await client.post(
            "/api/v1/agent/execute?dry_run=true",
            json={"command_id": command_id, "confirmed": True},
            headers=_headers(),
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"][0]["ok"] is True
        status = await conn.fetchval("SELECT status FROM exceptions WHERE exception_id = $1", _EXC)
        assert status == "open", "a dry run persisted"

    _run_async(body, _resolve_call())


# --- the refusals ------------------------------------------------------------


def test_executing_without_confirmation_is_refused() -> None:
    async def body(conn: Any, client: AsyncClient) -> None:
        command_id = (await _parse(client)).json()["command_id"]
        response = await client.post(
            "/api/v1/agent/execute",
            json={"command_id": command_id, "confirmed": False},
            headers=_headers(),
        )
        assert response.status_code == 422
        assert "a preview is not an instruction" in response.json()["detail"]

    _run_async(body, _resolve_call())


def test_an_unknown_command_id_is_404_and_says_to_parse_again() -> None:
    """Never a silent re-parse. If the plan they approved is gone, they need to
    see the new plan before confirming it."""

    async def body(conn: Any, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/agent/execute",
            json={"command_id": "cmd_never_existed", "confirmed": True},
            headers=_headers(),
        )
        assert response.status_code == 404
        assert "Parse the instruction again" in response.json()["detail"]

    _run_async(body, _resolve_call())


def test_an_expired_command_id_is_410_and_distinguishes_itself_from_unknown() -> None:
    async def body(conn: Any, client: AsyncClient) -> None:
        from api.routers import agent as agent_router

        command_id = (await _parse(client)).json()["command_id"]
        entry = agent_router._COMMANDS[command_id]
        agent_router._COMMANDS[command_id] = entry.model_copy(
            update={"stored_at": time.time() - agent_router.COMMAND_TTL_SECONDS - 1}
        )
        response = await client.post(
            "/api/v1/agent/execute",
            json={"command_id": command_id, "confirmed": True},
            headers=_headers(),
        )
        assert response.status_code == 410
        assert "the queue may have moved since" in response.json()["detail"]

    _run_async(body, _resolve_call())


def test_state_moving_between_preview_and_confirm_refuses_and_returns_the_new_preview() -> None:
    """The point of the whole preview flow.

    Without this, "the human approved this" is false whenever state moved in
    between — and it moves for the most ordinary reason there is: somebody else
    got to the item first.
    """

    async def body(conn: Any, client: AsyncClient) -> None:
        command_id = (await _parse(client)).json()["command_id"]

        # Somebody else resolves it while the preview is on screen.
        await conn.execute(
            "UPDATE exceptions SET status = 'escalated', tier = 'escalate' WHERE exception_id = $1",
            _EXC,
        )

        response = await client.post(
            "/api/v1/agent/execute",
            json={"command_id": command_id, "confirmed": True},
            headers=_headers(),
        )
        assert response.status_code == 409, response.text
        problem = response.json()
        assert problem["title"] == "conflict"
        assert "changed since the preview was built" in problem["detail"]
        assert problem["preview"]["refusal"]["code"] == "conflict"
        assert problem["preview"]["refusal"]["detail"]["current_status"] == {_EXC: "escalated"}

        # And nothing was applied.
        status = await conn.fetchval("SELECT status FROM exceptions WHERE exception_id = $1", _EXC)
        assert status == "escalated"

    _run_async(body, _resolve_call())


def test_a_large_amount_requires_the_user_to_type_it() -> None:
    """§8.5 rule 5, end to end."""

    async def body(conn: Any, client: AsyncClient) -> None:
        parsed = (await _parse(client)).json()
        assert parsed["preview"]["requires_typed_confirmation"] is True
        assert parsed["preview"]["typed_confirmation_paise"] == _BIG_AMOUNT

        refused = await client.post(
            "/api/v1/agent/execute",
            json={"command_id": parsed["command_id"], "confirmed": True},
            headers=_headers(),
        )
        assert refused.status_code == 422
        assert refused.json()["title"] == "typed confirmation required"

        wrong = await client.post(
            "/api/v1/agent/execute",
            json={
                "command_id": parsed["command_id"],
                "confirmed": True,
                "typed_confirmation": "51000",
            },
            headers=_headers(),
        )
        assert wrong.status_code == 422, "a different number was accepted"

        # Any faithful spelling of the amount is accepted — the check is the
        # figure, not our formatting of it.
        accepted = await client.post(
            "/api/v1/agent/execute",
            json={
                "command_id": parsed["command_id"],
                "confirmed": True,
                "typed_confirmation": "₹52,000.00",
            },
            headers=_headers(),
        )
        assert accepted.status_code == 200, accepted.text
        status = await conn.fetchval(
            "SELECT status FROM exceptions WHERE exception_id = $1", _BIG_EXC
        )
        assert status == "resolved"

    _run_async(body, _resolve_call(_BIG_EXC))


def test_an_instruction_naming_a_missing_exception_is_422_with_candidates() -> None:
    """§8.5 rules 2 and 3 are the two that need an answer from the person, not
    a confirmation — so they are the two that surface as 422 (§5.10)."""

    async def body(conn: Any, client: AsyncClient) -> None:
        response = await _parse(client)
        assert response.status_code == 422, response.text
        problem = response.json()
        assert problem["title"] == "not_found"
        assert "candidates" in problem

    _run_async(body, _resolve_call("exc_agent_flow_nope"))


def test_a_cut_verb_is_refused_by_name_rather_than_reinterpreted() -> None:
    async def body(conn: Any, client: AsyncClient) -> None:
        response = await _parse(client)
        assert response.status_code == 200, response.text
        refusal = response.json()["preview"]["refusal"]
        assert refusal["code"] == "cut"
        assert "grouping key" in refusal["message"]

    _run_async(
        body,
        {"name": "merge_cluster", "args": {"cluster_ids": ["cls_1", "cls_2"]}},
    )


def test_the_llm_call_is_logged_to_llm_calls() -> None:
    """§7.11: the observability row the router itself cannot write."""

    async def body(conn: Any, client: AsyncClient) -> None:
        await _parse(client)
        rows = await conn.fetch(
            "SELECT purpose, outcome, cached FROM llm_calls WHERE tenant_id = $1", _TENANT
        )
        assert rows, "no llm_calls row was written"
        assert all(r["purpose"] == "command_parse" for r in rows)

    _run_async(body, _resolve_call())


def test_a_verb_with_no_execution_path_is_refused_rather_than_silently_doing_nothing() -> None:
    """The bug this guards against shipped for an afternoon: ``create_rule``'s
    effect is ``rule.create``, ``_targets`` collected only ``exception.*``, and
    ``/agent/execute`` returned 200 with an empty ``applied`` list while writing
    an audit event saying the instruction had been carried out.

    "Looks applied but isn't" is the worst shape of failure a reconciliation
    system can have, so an unroutable verb is now a 422 that names what to do
    instead.
    """

    async def body(conn: Any, client: AsyncClient) -> None:
        parsed = (await _parse(client)).json()
        assert parsed["preview"]["refusal"] is None, "the preview should still render"

        response = await client.post(
            "/api/v1/agent/execute",
            json={"command_id": parsed["command_id"], "confirmed": True},
            headers=_headers(),
        )
        assert response.status_code == 422, response.text
        problem = response.json()
        assert problem["title"] == "no execution path"
        assert "not built" in problem["detail"]
        assert "preview" in problem, "the refusal should carry the preview it refused"

        # Nothing was audited as applied.
        actions = [
            r["action"]
            for r in await conn.fetch(
                "SELECT action FROM audit_events WHERE tenant_id = $1", _TENANT
            )
        ]
        assert "agent.execute" not in actions

    _run_async(
        body,
        {
            "name": "rerun",
            "args": {"period_start": "2026-08-01", "period_end": "2026-08-31"},
        },
    )


def test_create_rule_actually_creates_a_draft_rule() -> None:
    """The other half of the same bug: ``create_rule`` is executable, so it must
    reach ``POST /rules`` rather than falling into the refusal above."""

    async def body(conn: Any, client: AsyncClient) -> None:
        parsed = (await _parse(client)).json()
        assert parsed["preview"]["effects"][0]["action"] == "rule.create"

        response = await client.post(
            "/api/v1/agent/execute",
            json={"command_id": parsed["command_id"], "confirmed": True},
            headers=_headers(),
        )
        assert response.status_code == 200, response.text
        assert response.json()["applied"] == [
            {"exception_id": "Nykaa commission 18%", "ok": True, "detail": None}
        ]

        row = await conn.fetchrow(
            "SELECT name, status, origin FROM rules WHERE tenant_id = $1", _TENANT
        )
        assert row is not None, "no rule was created"
        assert row["name"] == "Nykaa commission 18%"
        # §8.8: a rule is never born active, whatever the instruction said.
        assert row["status"] == "draft"

    _run_async(
        body,
        {
            "name": "create_rule",
            "args": {
                "rule_draft": {
                    "name": "Nykaa commission 18%",
                    "description": "Learned from three resolutions.",
                    "scope": {
                        "counterparty_matches": ["nykaa"],
                        "date_from": "2026-08-01",
                    },
                    "deductions": [{"type": "commission", "basis": "gross", "rate": "18.0"}],
                    "tolerance": {"absolute_paise": 100, "percent": "0.05"},
                    "priority": 100,
                    "effective_confidence": "0.90",
                }
            },
        },
    )


def test_apply_to_cluster_runs_the_whole_validator_per_member() -> None:
    """§8.6, and the reason it is not just the endpoint's own status guard.

    The cluster here holds the ₹1,200 item the human actually looked at and a
    ₹52,000 chargeback with no dispute reference. One confirmation must not
    carry the second one out on the first one's back — it is excluded by name,
    with a reason, and the small one still closes.
    """

    async def body(conn: Any, client: AsyncClient) -> None:
        await conn.execute(
            "INSERT INTO clusters (cluster_id, run_id, tenant_id, root_cause, label, "
            "grouping_key, member_count, total_paise, max_tier, created_at) "
            "VALUES ($1, $2, $3, 'timing lag', 'lag', 'k', 2, 5300000, 'escalate', $4)",
            _CLUSTER,
            _RUN,
            _TENANT,
            _AT,
        )
        await conn.execute(
            "UPDATE exceptions SET cluster_id = $1 WHERE exception_id = ANY($2)",
            _CLUSTER,
            [_EXC, _BIG_EXC],
        )
        # The big one is a chargeback with nothing citing a dispute reference.
        await conn.execute(
            "UPDATE exceptions SET category = 'chargeback_unrecorded' WHERE exception_id = $1",
            _BIG_EXC,
        )

        parsed = (await _parse(client)).json()
        assert parsed["preview"]["cluster_offer"]["member_count"] == 1

        response = await client.post(
            "/api/v1/agent/execute",
            json={
                "command_id": parsed["command_id"],
                "confirmed": True,
                "apply_to_cluster": True,
            },
            headers=_headers(),
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert [a["exception_id"] for a in payload["applied"]] == [_EXC]
        excluded = {a["exception_id"]: a["detail"] for a in payload["excluded"]}
        assert _BIG_EXC in excluded, "a chargeback rode in on another item's confirmation"
        assert "its own confirmation" in excluded[_BIG_EXC]

        statuses = dict(
            await conn.fetch(
                "SELECT exception_id, status FROM exceptions WHERE tenant_id = $1", _TENANT
            )
        )
        assert statuses[_EXC] == "resolved"
        assert statuses[_BIG_EXC] == "open", "the excluded member was changed anyway"

    _run_async(body, _resolve_call())
