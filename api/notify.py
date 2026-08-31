"""Resend integration — PRD §2.5.9 N1-N4.

| ID | Notification | Fires on |
|---|---|---|
| N1 | Escalation alert | an exception reaching ``tier='escalate'`` |
| N2 | Daily digest | the scheduler's daily job |
| N3 | Rule suggestion | the learner drafting a rule |
| N4 | Deadline reminder | 48 hours before a consequence date |

Every function here is fire-and-forget: a Resend outage, a missing or invalid
``RESEND_API_KEY``, DNS failure, a timeout — none of it may fail the request or
job that triggered the notification, and none of it may block one. There is
exactly one place that calls Resend (:func:`_send`); every other function in
this module funnels through it, so "never raises" is proven once rather than
re-implemented per notification type. Every path through :func:`_send` either
sends the email or logs why it didn't — never raises past this module's
boundary.

**Every interpolated value is HTML-escaped.** Reasons, digests and rule names
all originate in text a user typed or a bank supplied, and a bank narration is
the least trustworthy string in this system (§10.3). An unescaped ``<`` here
would put attacker-controlled markup in a finance team's inbox.
"""

from __future__ import annotations

import asyncio
import html
import logging
from collections.abc import Sequence
from datetime import date

import resend

from fc.config import Config
from fc.models.money import fmt_inr

__all__ = [
    "notify_daily_digest",
    "notify_deadline_reminder",
    "notify_escalation",
    "notify_rule_suggestion",
    "notify_run_complete",
]

_LOG = logging.getLogger("fc.notify")

#: Resend's SDK has no built-in timeout on send_async; a slow or hanging
#: Resend endpoint must not hang the caller indefinitely (a scheduler job
#: awaiting this in-line, or a request handler that fires it before
#: returning), so one is imposed here regardless of the SDK's own behaviour.
_SEND_TIMEOUT_SECONDS = 10.0


async def _send(
    cfg: Config, *, subject: str, html_body: str, to: str | Sequence[str] | None = None
) -> None:
    """The one call site that talks to Resend. Never raises."""
    if isinstance(to, str):
        recipients = [to]
    elif to:
        recipients = [r for r in to if r]
    else:
        recipients = [cfg.notify_escalation_to] if cfg.notify_escalation_to else []

    if not cfg.resend_api_key:
        _LOG.info("notify skipped (no RESEND_API_KEY configured): %s", subject)
        return
    if not recipients:
        _LOG.info("notify skipped (no recipient configured): %s", subject)
        return

    resend.api_key = cfg.resend_api_key
    try:
        async with asyncio.timeout(_SEND_TIMEOUT_SECONDS):
            await resend.Emails.send_async(
                {
                    "from": cfg.notify_from,
                    "to": list(recipients),
                    "subject": subject,
                    "html": html_body,
                }
            )
    except Exception:  # noqa: BLE001 - fire-and-forget: log every failure, propagate none
        _LOG.exception("notify failed (subject=%r, recipients=%r)", subject, recipients)


async def notify_escalation(
    cfg: Config,
    *,
    exception_id: str,
    reason: str,
    amount_paise: int | None = None,
    to: str | Sequence[str] | None = None,
) -> None:
    """N1: an exception escalated — three failed rechecks, a human escalate,
    or a NEVER_AUTO category that never had a chance to auto-close."""
    amount = f" ({fmt_inr(amount_paise)})" if amount_paise is not None else ""
    await _send(
        cfg,
        subject=f"[Escalation] exception {exception_id}{amount}",
        html_body=(
            f"<p>{html.escape(reason)}</p>"
            f"<p>exception_id: <code>{html.escape(exception_id)}</code></p>"
        ),
        to=to,
    )


async def notify_daily_digest(
    cfg: Config, *, summary: str, to: str | Sequence[str] | None = None
) -> None:
    """N2: the end-of-day rollup of what the queue looks like."""
    await _send(
        cfg,
        subject="Daily reconciliation digest",
        html_body=f"<pre>{html.escape(summary)}</pre>",
        to=to,
    )


async def notify_rule_suggestion(
    cfg: Config,
    *,
    rule_name: str,
    occurrences: int,
    to: str | Sequence[str] | None = None,
) -> None:
    """N3: a learned draft is ready for a human to back-test and approve."""
    name = html.escape(rule_name)
    await _send(
        cfg,
        subject=f"New rule suggestion: {rule_name}",
        html_body=(
            f"<p><strong>{name}</strong> explains a pattern seen {occurrences} times.</p>"
            "<p>It is a draft and explains nothing until it has been back-tested "
            "against history and activated — in that order.</p>"
        ),
        to=to,
    )


async def notify_run_complete(
    cfg: Config,
    *,
    run_id: str,
    headline: str,
    records_processed: int,
    settled_automatically: int,
    needing_attention: int,
    false_auto_resolutions: int,
    top_exceptions: Sequence[dict[str, object]],
    app_url: str,
    to: str | Sequence[str] | None = None,
) -> None:
    """The "email me when a run finishes" toggle (Reconcile screen).

    ``top_exceptions`` entries carry ``category`` (str), ``amount_paise``
    (int) and ``deadline`` (``date | None``) — the top 5 by amount, already
    selected by the caller; this function only renders them.
    """
    rows = "".join(
        f"<tr><td>{html.escape(str(item.get('category', '')))}</td>"
        f"<td>{fmt_inr(int(item['amount_paise']))}</td>"  # type: ignore[arg-type]
        f"<td>{html.escape(str(item['deadline'])) if item.get('deadline') else '—'}</td></tr>"
        for item in top_exceptions
    )
    await _send(
        cfg,
        subject=f"Reconciliation complete — {html.escape(headline)}",
        html_body=(
            f"<p><strong>{html.escape(headline)}</strong></p>"
            "<ul>"
            f"<li>Records processed: {records_processed}</li>"
            f"<li>Settled automatically: {settled_automatically}</li>"
            f"<li>Needing attention: {needing_attention}</li>"
            f"<li>False auto-resolutions: {false_auto_resolutions}</li>"
            "</ul>"
            "<p><strong>Top exceptions by amount</strong></p>"
            "<table cellpadding=\"4\"><tr><th>Category</th><th>Amount</th><th>Deadline</th></tr>"
            f"{rows}</table>"
            f"<p><a href=\"{html.escape(app_url)}\">Open the app</a></p>"
            f"<p style=\"color:#888;font-size:12px\">run_id: {html.escape(run_id)}</p>"
        ),
        to=to,
    )


async def notify_deadline_reminder(
    cfg: Config,
    *,
    exception_id: str,
    deadline: date,
    consequence: str,
    amount_paise: int,
    to: str | Sequence[str] | None = None,
) -> None:
    """N4: 48 hours before a consequence date.

    Separate from N3, which shares a trigger with nothing. The two were one
    function until this build; they answer different questions and only one of
    them is time-critical.
    """
    await _send(
        cfg,
        subject=f"[Deadline in 48h] {exception_id} — {fmt_inr(amount_paise)}",
        html_body=(
            f"<p><code>{html.escape(exception_id)}</code> "
            f"({fmt_inr(amount_paise)}) has a deadline of "
            f"<strong>{deadline.isoformat()}</strong>.</p>"
            f"<p>{html.escape(consequence)}</p>"
        ),
        to=to,
    )
