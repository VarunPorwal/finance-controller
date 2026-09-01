"""Delete leftover probe rules a test or a manual poke left in the Rulebook.

A rule named for a test — "AUDIT PROBE - delete me" and its kind — is not a
rulebook entry, it is debris. It still shows up in the Rulebook, still counts
toward a set's rule count, and still gets offered to a run, so it is worth
removing rather than living with.

Deliberately narrow: it matches names that *announce themselves* as scratch,
never a name that merely looks unfamiliar, because deleting a real rule
somebody wrote is far worse than leaving a probe behind. It prints what it
would delete and only writes with ``--apply``.

    python scripts/prune_test_rules.py            # show what would go
    python scripts/prune_test_rules.py --apply    # delete it
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine" / "src"))

from sqlalchemy import delete, select  # noqa: E402

from api.deps import scoped_session  # noqa: E402
from db.models import Rule as RuleRow  # noqa: E402
from fc.config import load_config  # noqa: E402

#: A name that says out loud it is not a real rule. Anchored on whole words so
#: a genuine rule mentioning "audit" in passing is never caught.
_SCRATCH_NAME = re.compile(
    r"\b(delete me|audit probe|test rule|probe|scratch|do not use|dummy|xxx)\b",
    re.IGNORECASE,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="actually delete")
    args = parser.parse_args()

    cfg = load_config()
    if not cfg.database_url:
        print("no DATABASE_URL configured", file=sys.stderr)
        return 1

    async with scoped_session(cfg.tenant_id, "owner") as session:
        rows = (
            await session.scalars(select(RuleRow).where(RuleRow.tenant_id == cfg.tenant_id))
        ).all()
        doomed = [r for r in rows if _SCRATCH_NAME.search(r.name or "")]
        if not doomed:
            print("no leftover probe rules found")
            return 0
        for row in doomed:
            print(f"  {row.rule_id}:{row.version}  {row.status:8}  {row.name!r}")
        if not args.apply:
            print(f"\n{len(doomed)} rule(s) would be deleted; re-run with --apply")
            return 0
        await session.execute(
            delete(RuleRow).where(
                RuleRow.tenant_id == cfg.tenant_id,
                RuleRow.rule_id.in_([r.rule_id for r in doomed]),
                RuleRow.version.in_([r.version for r in doomed]),
            )
        )
        await session.commit()
        print(f"\ndeleted {len(doomed)} rule(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
