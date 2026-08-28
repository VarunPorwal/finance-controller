"""Alembic environment. Async engine, asyncpg, Neon.

Migrations run as the database owner (``DATABASE_URL``). The API connects as the
non-owner ``fc_app_user`` (``DATABASE_URL_APP``) so that the row-level security
policies created here actually bind at request time.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine" / "src"))

from db.models import Base  # noqa: E402
from fc.config import asyncpg_url, load_config  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_settings = load_config(env_file=str(ROOT / ".env"))
if not _settings.database_url:
    raise RuntimeError("DATABASE_URL is not set; alembic has nothing to connect to")
config.set_main_option("sqlalchemy.url", asyncpg_url(_settings.database_url))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
