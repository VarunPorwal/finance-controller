"""FastAPI dependencies — PRD §4.4.

The application connects as ``fc_app_user`` (``DATABASE_URL_APP``), a non-owner
role with no ``BYPASSRLS``. That is what makes the row-level security policies
bind: the migration owner (``DATABASE_URL``) is superuser-equivalent on Neon and
bypasses them, which is correct for migrations and wrong for request handling.

``SET LOCAL`` scopes the tenant to the transaction, so a connection returned to
the pool cannot carry another tenant's context into the next request.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "engine" / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "engine" / "src"))

from fc.config import Config, asyncpg_url, load_config  # noqa: E402


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config(env_file=str(ROOT / ".env"))


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    config = get_config()
    url = config.database_url_app or config.database_url
    if not url:
        raise RuntimeError("neither DATABASE_URL_APP nor DATABASE_URL is set")
    return create_async_engine(
        asyncpg_url(url),
        pool_size=config.db_pool_size,
        max_overflow=config.db_max_overflow,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def db_session(tenant_id: str, role: str) -> AsyncIterator[AsyncSession]:
    """Yield a session scoped to one tenant and one role for one transaction.

    Routers depend on this via a wrapper that resolves ``tenant_id`` and ``role``
    from the authenticated user; auth lands in a later prompt.
    """
    async with get_sessionmaker()() as session:
        await session.begin()
        await session.execute(text("SET LOCAL app.tenant_id = :t"), {"t": tenant_id})
        await session.execute(text("SET LOCAL app.role = :r"), {"r": role})
        try:
            yield session
        finally:
            await session.rollback()
