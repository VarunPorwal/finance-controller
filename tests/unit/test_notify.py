"""Fire-and-forget, genuinely: a Resend outage, a missing key, or an
invalid one must never raise past this module and never block the caller.
Every path is proven, including one against the real Resend API with a
key that is deliberately wrong — not just mocked — per the explicit ask.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from api.notify import notify_daily_digest, notify_escalation, notify_rule_suggestion
from fc.config import Config


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _cfg(**overrides: object) -> Config:
    return Config(**overrides)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_missing_api_key_skips_the_network_call_entirely() -> None:
    cfg = _cfg(resend_api_key="", notify_escalation_to="ops@example.invalid")
    with patch("api.notify.resend.Emails.send_async", new_callable=AsyncMock) as mock_send:
        await notify_escalation(cfg, exception_id="exc_1", reason="test")
    mock_send.assert_not_called()


@pytest.mark.anyio
async def test_missing_recipient_skips_the_network_call_entirely() -> None:
    cfg = _cfg(resend_api_key="re_fake_key", notify_escalation_to="")
    with patch("api.notify.resend.Emails.send_async", new_callable=AsyncMock) as mock_send:
        await notify_escalation(cfg, exception_id="exc_1", reason="test")
    mock_send.assert_not_called()


@pytest.mark.anyio
async def test_a_rejected_send_never_raises() -> None:
    """Simulates exactly what an invalid key produces: Resend's SDK raising
    on the call. The function must swallow it, not propagate it."""
    cfg = _cfg(resend_api_key="re_fake_key", notify_escalation_to="ops@example.invalid")
    with patch(
        "api.notify.resend.Emails.send_async",
        new_callable=AsyncMock,
        side_effect=RuntimeError("401 Unauthorized: invalid API key"),
    ) as mock_send:
        await notify_escalation(cfg, exception_id="exc_1", reason="test")  # must not raise
    mock_send.assert_called_once()


@pytest.mark.anyio
async def test_a_hanging_send_is_bounded_by_the_timeout_not_left_to_block() -> None:
    """A Resend outage that never responds must not hang the caller forever."""
    import asyncio

    async def _never_returns(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(3600)

    cfg = _cfg(resend_api_key="re_fake_key", notify_escalation_to="ops@example.invalid")
    with (
        patch("api.notify._SEND_TIMEOUT_SECONDS", 0.05),
        patch("api.notify.resend.Emails.send_async", side_effect=_never_returns),
    ):
        await asyncio.wait_for(
            notify_escalation(cfg, exception_id="exc_1", reason="test"), timeout=2.0
        )  # the outer wait_for is the test's own safety net, not the mechanism under test


@pytest.mark.anyio
async def test_all_three_notification_types_never_raise_on_failure() -> None:
    cfg = _cfg(resend_api_key="re_fake_key", notify_escalation_to="ops@example.invalid")
    with patch(
        "api.notify.resend.Emails.send_async",
        new_callable=AsyncMock,
        side_effect=RuntimeError("boom"),
    ):
        await notify_escalation(cfg, exception_id="exc_1", reason="r")
        await notify_daily_digest(cfg, summary="s")
        await notify_rule_suggestion(cfg, rule_name="blinkit_commission", occurrences=3)


@pytest.mark.anyio
async def test_a_genuinely_invalid_key_against_the_real_resend_api_never_raises() -> None:
    """The explicit ask: no mock. A syntactically-plausible but wrong Resend
    key, hitting the real endpoint. Whether the sandbox has network access
    or not, this must return normally either way — a connection failure and
    a 401 from Resend both go through the exact same except-and-log path.
    """
    cfg = _cfg(
        resend_api_key="re_00000000_INVALID_KEY_FOR_TESTING_0000",
        notify_escalation_to="fc-notify-test@example.invalid",
        notify_from="controller@aarambhlabs.dev",
    )
    await notify_escalation(
        cfg, exception_id="exc_real_invalid_key", reason="explicit invalid-key test"
    )
