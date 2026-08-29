"""Resend integration — PRD §2.5.9 N1-N4: escalation alert, daily digest,
rule suggestion.

Every function here is fire-and-forget: a Resend outage, a missing or
invalid ``RESEND_API_KEY``, DNS failure, a timeout — none of it may fail the
request or job that triggered the notification, and none of it may block
one. There is exactly one place that calls Resend (:func:`_send`); every
other function in this module funnels through it, so "never raises" is
proven once rather than re-implemented per notification type. Every path
through :func:`_send` either sends the email or logs why it didn't — never
raises past this module's boundary.
"""

from __future__ import annotations

import asyncio
import logging

import resend

from fc.config import Config

__all__ = ["notify_daily_digest", "notify_escalation", "notify_rule_suggestion"]

_LOG = logging.getLogger("fc.notify")

#: Resend's SDK has no built-in timeout on send_async; a slow or hanging
#: Resend endpoint must not hang the caller indefinitely (a scheduler job
#: awaiting this in-line, or a request handler that fires it before
#: returning), so one is imposed here regardless of the SDK's own behaviour.
_SEND_TIMEOUT_SECONDS = 10.0


async def _send(cfg: Config, *, subject: str, html: str, to: str | None = None) -> None:
    """The one call site that talks to Resend. Never raises."""
    recipient = to or cfg.notify_escalation_to
    if not cfg.resend_api_key:
        _LOG.info("notify skipped (no RESEND_API_KEY configured): %s", subject)
        return
    if not recipient:
        _LOG.info("notify skipped (no recipient configured): %s", subject)
        return

    resend.api_key = cfg.resend_api_key
    try:
        async with asyncio.timeout(_SEND_TIMEOUT_SECONDS):
            await resend.Emails.send_async(
                {
                    "from": cfg.notify_from,
                    "to": [recipient],
                    "subject": subject,
                    "html": html,
                }
            )
    except Exception:  # noqa: BLE001 - fire-and-forget: log every failure, propagate none
        _LOG.exception("notify failed (subject=%r, recipient=%r)", subject, recipient)


async def notify_escalation(cfg: Config, *, exception_id: str, reason: str) -> None:
    """N1: an exception escalated — three failed rechecks, a human escalate,
    or a NEVER_AUTO category that never had a chance to auto-close."""
    await _send(
        cfg,
        subject=f"[Escalation] exception {exception_id}",
        html=f"<p>{reason}</p><p>exception_id: {exception_id}</p>",
    )


async def notify_daily_digest(cfg: Config, *, summary: str) -> None:
    """N2: the end-of-day rollup of what the queue looks like."""
    await _send(cfg, subject="Daily reconciliation digest", html=f"<pre>{summary}</pre>")


async def notify_rule_suggestion(cfg: Config, *, rule_name: str, occurrences: int) -> None:
    """N3/N4: a learned draft is ready for a human to back-test and approve."""
    await _send(
        cfg,
        subject=f"New rule suggestion: {rule_name}",
        html=f"<p>{rule_name!r} explains a pattern seen {occurrences} times. "
        "Back-test it before activating.</p>",
    )
