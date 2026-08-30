#!/usr/bin/env python
"""Seed the demo tenant and user — PRD §9.4's provisioning workflow, run by
hand instead of by the (Phase 2, unbuilt) signup flow.

Idempotent: an upsert on the primary key, so re-running after a DB reset
never duplicates and always leaves the row matching what is written below
rather than whatever an earlier partial run left behind.

Connects with ``DATABASE_URL`` (the owner role), not ``DATABASE_URL_APP``:
row-level security on ``tenants``/``users`` is scoped by ``app.tenant_id``,
which does not exist yet for a tenant that has not been created — the same
reason ``alembic upgrade head`` runs as owner rather than as ``fc_app_user``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# `db` and `api` are plain top-level packages, not installed workspace
# members like `fc` - `python -m api.main` gets the repo root on sys.path for
# free because `-m` does that; a script under scripts/ does not, so this is
# the same fix applied before the import that needs it.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from db.models import Tenant, User  # noqa: E402
from fc.config import asyncpg_url, load_config  # noqa: E402

TENANT = {
    "tenant_id": "t_lumea",
    "name": "Lumea Personal Care",
    "gstin": "23AABCL1234M1Z5",
    "fiscal_year_start_month": 4,
}

USER = {
    "user_id": "u_demo",
    "tenant_id": "t_lumea",
    "email": "priya@lumea.in",
    "display_name": "Priya Sharma",
    "role": "finance_manager",
}


async def _seed() -> None:
    cfg = load_config(env_file=str(ROOT / ".env"))
    url = cfg.database_url
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        raise SystemExit(1)

    engine = create_async_engine(asyncpg_url(url))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            await session.execute(
                insert(Tenant)
                .values(**TENANT)
                .on_conflict_do_update(
                    index_elements=[Tenant.tenant_id],
                    set_={k: v for k, v in TENANT.items() if k != "tenant_id"},
                )
            )
            await session.execute(
                insert(User)
                .values(**USER)
                .on_conflict_do_update(
                    index_elements=[User.user_id],
                    set_={k: v for k, v in USER.items() if k != "user_id"},
                )
            )
            await session.commit()

            tenant = await session.scalar(
                select(Tenant).where(Tenant.tenant_id == TENANT["tenant_id"])
            )
            user = await session.scalar(select(User).where(User.user_id == USER["user_id"]))
            print(f"tenant: {tenant.tenant_id}  {tenant.name}  gstin={tenant.gstin}")
            print(f"user:   {user.user_id}  {user.display_name} <{user.email}>  role={user.role}")
    finally:
        await engine.dispose()


def main() -> int:
    asyncio.run(_seed())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
