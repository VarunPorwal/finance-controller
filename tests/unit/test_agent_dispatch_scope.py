"""``_dispatch`` must re-apply the tenant scope for every item it fans out to.

``set_config('app.tenant_id', ..., is_local => true)`` lives for one
transaction. Each endpoint ``_apply_one`` calls ends in ``finish``, which
commits, so the scope is gone by the second item: RLS then returns no row,
``_load`` raises 404, and the item is reported as excluded — indistinguishable
from "already resolved". Applying a four-member cluster in production resolved
one member and returned HTTP 200.

A unit test rather than an integration one because the property is about call
*order* inside the loop, not about what the database does — and this is the
kind of regression that reappears the moment somebody hoists the call out of
the loop "because it only needs doing once".
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from api.routers import agent as agent_router


@pytest.mark.asyncio
async def test_dispatch_rescopes_before_every_target() -> None:
    targets = ["exc_a", "exc_b", "exc_c", "exc_d"]
    calls: list[tuple[str, str]] = []

    async def fake_rescope(_session: Any, _user: Any) -> None:
        calls.append(("rescope", ""))

    async def fake_apply_one(_session: Any, **kwargs: Any) -> None:
        calls.append(("apply", kwargs["target"]))

    command = AsyncMock()
    command.payload = None
    command.verb = "resolve"
    command.instruction_text = "resolve these"

    with (
        patch.object(agent_router, "rescope", fake_rescope),
        patch.object(agent_router, "_apply_one", fake_apply_one),
    ):
        applied, excluded = await agent_router._dispatch(
            AsyncMock(),
            command=command,
            targets=targets,
            user=AsyncMock(),
            cfg=AsyncMock(),
            dry_run=False,
        )

    assert [a.exception_id for a in applied] == targets
    assert excluded == []
    # Strictly alternating: a rescope immediately precedes each apply.
    assert calls == [step for target in targets for step in (("rescope", ""), ("apply", target))]


@pytest.mark.asyncio
async def test_dispatch_rescopes_even_after_an_item_fails() -> None:
    """A failed item still commits nothing, but the *previous* item's commit
    already dropped the scope — so the recovery must not depend on success."""
    from api.errors import ApiError

    seen: list[str] = []

    async def fake_rescope(_session: Any, _user: Any) -> None:
        seen.append("rescope")

    async def fake_apply_one(_session: Any, **kwargs: Any) -> None:
        seen.append(f"apply:{kwargs['target']}")
        if kwargs["target"] == "exc_b":
            raise ApiError(404, "not found", "no exception exc_b")

    command = AsyncMock()
    command.payload = None
    command.verb = "resolve"
    command.instruction_text = "resolve these"

    with (
        patch.object(agent_router, "rescope", fake_rescope),
        patch.object(agent_router, "_apply_one", fake_apply_one),
    ):
        applied, excluded = await agent_router._dispatch(
            AsyncMock(),
            command=command,
            targets=["exc_a", "exc_b", "exc_c"],
            user=AsyncMock(),
            cfg=AsyncMock(),
            dry_run=False,
        )

    assert [a.exception_id for a in applied] == ["exc_a", "exc_c"]
    assert [e.exception_id for e in excluded] == ["exc_b"]
    assert seen.count("rescope") == 3
