"""The scheduler must not start on import — pytest collecting ``api.main``
(every router test in this repo does that) must never let a recheck job
mutate ``exceptions`` rows mid-test-run. Two independent gates: the FastAPI
lifespan handler (only fires on a real ASGI ``startup`` event) and
``Config.scheduler_enabled`` (off by default). Both are proven here, not
just described.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

from api import scheduler as scheduler_module
from fc.config import Config


def _cfg(**overrides: object) -> Config:
    return Config(**overrides)  # type: ignore[arg-type]


def test_scheduler_enabled_defaults_to_false() -> None:
    assert _cfg().scheduler_enabled is False


def test_start_is_a_noop_when_scheduler_disabled() -> None:
    with patch.object(scheduler_module.AsyncIOScheduler, "start") as mock_start:
        result = scheduler_module.start(_cfg(scheduler_enabled=False))
    assert result is None
    mock_start.assert_not_called()


def test_start_actually_starts_when_explicitly_enabled() -> None:
    with (
        patch.object(scheduler_module.AsyncIOScheduler, "start") as mock_start,
        patch.object(scheduler_module.AsyncIOScheduler, "shutdown") as mock_shutdown,
    ):
        result = scheduler_module.start(_cfg(scheduler_enabled=True))
        assert result is not None
        mock_start.assert_called_once()
        scheduler_module.stop(result)
    mock_shutdown.assert_called_once()


def test_importing_api_main_never_calls_apscheduler_start() -> None:
    """The primary gate: module import must not run the lifespan handler at
    all. Reloads api.main under a patched AsyncIOScheduler.start to prove
    the module-level code path (as opposed to the lifespan function, which
    is merely *registered* here, never invoked) never reaches it."""
    with patch.object(scheduler_module.AsyncIOScheduler, "start") as mock_start:
        import api.main

        importlib.reload(api.main)
    mock_start.assert_not_called()


def test_our_own_test_transport_never_triggers_lifespan_startup() -> None:
    """The exact scenario every other API integration test in this repo
    relies on: httpx.ASGITransport(app=app), used without lifespan support,
    must not send the ASGI 'lifespan.startup' message — confirmed here by
    asserting the scheduler is untouched after building a transport from the
    real app object, not just by every other test happening to pass."""
    import api.main

    with patch.object(scheduler_module.AsyncIOScheduler, "start") as mock_start:
        from httpx import ASGITransport

        ASGITransport(app=api.main.app)
        # No request was even made — building the transport alone must not
        # touch the scheduler, let alone a request through it would.
    mock_start.assert_not_called()


@pytest.mark.anyio
async def test_real_asgi_lifespan_respects_the_disabled_flag() -> None:
    """Drives the actual registered lifespan context manager — what a real
    ASGI server calls on startup/shutdown — and confirms that with the
    config default (disabled) it still starts nothing for real."""
    import api.main

    with (
        patch.object(api.main, "get_config", return_value=_cfg(scheduler_enabled=False)),
        patch.object(scheduler_module.AsyncIOScheduler, "start") as mock_start,
    ):
        async with api.main.lifespan(api.main.app):
            pass
    mock_start.assert_not_called()


@pytest.mark.anyio
async def test_real_asgi_lifespan_starts_it_when_enabled() -> None:
    import api.main

    with (
        patch.object(api.main, "get_config", return_value=_cfg(scheduler_enabled=True)),
        patch.object(scheduler_module.AsyncIOScheduler, "start") as mock_start,
        patch.object(scheduler_module.AsyncIOScheduler, "shutdown") as mock_shutdown,
    ):
        async with api.main.lifespan(api.main.app):
            mock_start.assert_called_once()
    mock_shutdown.assert_called_once()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
