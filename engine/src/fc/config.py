"""Runtime configuration — every variable in PRD Appendix B, with its default.

Read once at process start via :func:`load_config`. Pure stdlib plus Pydantic:
importing this module touches no database and no network, so ``make eval`` runs
without either.

Money settings are ``int`` paise and thresholds are ``Decimal`` — never float.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Config", "LLMMode", "asyncpg_url", "load_config"]

LLMMode = Literal["live", "cache_only", "off"]

# libpq understands these; asyncpg's connect() does not and raises on them.
_LIBPQ_ONLY_PARAMS = frozenset({"channel_binding", "target_session_attrs", "options"})


class Config(BaseModel):
    """Immutable snapshot of the environment. Stored on ``runs.config`` per run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Database
    database_url: str = ""
    database_url_readonly: str = ""  # text-to-SQL role
    database_url_app: str = ""  # non-owner role; RLS binds on this one
    fc_app_password: str = ""  # password for fc_app_user, consumed by the migration
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # LLM
    gemini_api_key: str = ""
    groq_api_key: str = ""
    llm_mode: LLMMode = "live"
    llm_cache_dir: str = "/tmp/fc-llm-cache"
    llm_cache_ttl_days: int = 7
    llm_max_calls_per_run: int = 10
    gemini_context_cache_ttl: int = 3600

    # Reconciliation config
    auto_threshold: Decimal = Field(default=Decimal("0.94"), ge=Decimal(0), le=Decimal(1))
    tolerance_abs_paise: int = 100
    tolerance_pct: Decimal = Decimal("0.0005")
    rounding_drift_paise: int = 1
    max_subset_n: int = 40
    subset_timeout_ms: int = 500
    max_bucket_size: int = 200
    recheck_interval_days: int = 2
    max_rechecks: int = 3
    typed_confirm_paise: int = 5_000_000  # ₹50,000

    # Exception pipeline (§6.8)
    dispute_window_days: int = 30  # RBI chargeback contest window
    missing_in_bank_sla_days: int = 2  # escalate to Razorpay support after this

    # Auth
    jwt_secret: str = ""
    jwt_ttl_minutes: int = 15
    refresh_ttl_days: int = 7
    demo_token: str = ""

    # Notifications
    resend_api_key: str = ""
    notify_from: str = "controller@aarambhlabs.dev"
    notify_escalation_to: str = ""

    # App
    api_base_url: str = ""
    frontend_origin: str = ""
    environment: str = "production"
    sentry_dsn: str = ""
    log_level: str = "INFO"

    # Tenant
    tenant_id: str = "t_lumea"

    @property
    def offline(self) -> bool:
        """True when no LLM call may leave the process (``make demo-local``)."""
        return self.llm_mode in ("cache_only", "off")


def load_config(*, env_file: str | None = ".env", environ: dict[str, str] | None = None) -> Config:
    """Build a :class:`Config` from the environment, applying Appendix B defaults.

    An empty or absent variable falls back to the default rather than to the
    empty string, so a half-filled ``.env`` cannot silently zero a threshold.
    """
    if env_file is not None:
        load_dotenv(env_file, override=False)
    source = os.environ if environ is None else environ

    values: dict[str, str] = {}
    for name in Config.model_fields:
        raw = source.get(name.upper())
        if raw is not None and raw.strip() != "":
            values[name] = raw.strip()
    return Config.model_validate(values)


def asyncpg_url(url: str) -> str:
    """Make a Postgres URL safe for the SQLAlchemy asyncpg dialect.

    Neon hands out connection strings carrying libpq-only parameters
    (``channel_binding``), which asyncpg's ``connect()`` rejects as an unexpected
    keyword. Strip those and normalise ``sslmode`` to asyncpg's ``ssl``.
    """
    if not url:
        return url
    parts = urlsplit(url)
    query = [
        ("ssl", value) if key == "sslmode" else (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _LIBPQ_ONLY_PARAMS
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))
