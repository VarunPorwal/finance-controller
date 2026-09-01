"""Bring a shipped rulebook back after an upload retired it.

Uploading a rulebook used to retire *every* active rule the tenant had, not
just the ones it replaced. Retirement is one-way, so on any tenant that
happened to, the starter pack is gone: the demo corpus reconciles against no
rulebook at all and quietly reports zero rule-resolved exceptions. Rule sets
stop it happening again; they cannot undo the runs that already did it.

This restores one rulebook by *adding a new version* of each of its rules —
never by editing what is there. An active rule is immutable and a database
trigger enforces it (CLAUDE.md hard rule 8), and a retired rule stays retired
because somebody may have meant it. Version N+1 is how this system has always
expressed "use this again", and it leaves the whole history readable.

    python scripts/restore_rule_set.py                    # show what it would add
    python scripts/restore_rule_set.py --apply
    python scripts/restore_rule_set.py --set dataset-v2 --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine" / "src"))

from sqlalchemy import select  # noqa: E402

from api.deps import scoped_session  # noqa: E402
from api.ruleset import BUNDLED_RULE_SETS, DEMO_RULE_SET, rule_set_of  # noqa: E402
from db.models import Rule as RuleRow  # noqa: E402
from db.models import User  # noqa: E402
from fc.config import load_config  # noqa: E402
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules  # noqa: E402


def _source_for(name: str) -> Path:
    if name == DEMO_RULE_SET:
        return Path(DEFAULT_RULES_PATH)
    for set_name, path in BUNDLED_RULE_SETS:
        if set_name == name:
            return path
    raise SystemExit(f"no shipped rulebook named {name!r}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="rule_set", default=DEMO_RULE_SET)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    source = _source_for(args.rule_set)
    now = datetime.now(UTC)
    ruleset = load_rules(source, tenant_id=cfg.tenant_id, created_at=now, rule_set=args.rule_set)

    async with scoped_session(cfg.tenant_id, "owner") as session:
        actor = await session.scalar(
            select(User.user_id)
            .where(User.tenant_id == cfg.tenant_id, User.status == "active")
            .order_by(User.created_at, User.user_id)
            .limit(1)
        )
        if actor is None:
            print("no active user to attribute the restore to", file=sys.stderr)
            return 1

        rows = (
            await session.scalars(select(RuleRow).where(RuleRow.tenant_id == cfg.tenant_id))
        ).all()
        latest: dict[str, RuleRow] = {}
        for row in rows:
            best = latest.get(row.rule_id)
            if best is None or row.version > best.version:
                latest[row.rule_id] = row
        live = {
            row.rule_id
            for row in rows
            if row.status == "active" and rule_set_of(row) == args.rule_set
        }

        added = 0
        for rule in ruleset.rules:
            # Only the version the file says should be live. A file that
            # carries its own retired history (the starter pack does) must not
            # have that history re-inserted as new active rows.
            if rule.status != "active" or rule.rule_id in live:
                continue
            previous = latest.get(rule.rule_id)
            version = previous.version + 1 if previous is not None else 1
            print(
                f"  {rule.rule_id:24} -> v{version}"
                f"   (was {previous.status if previous else 'absent'})"
            )
            if not args.apply:
                added += 1
                continue
            session.add(
                RuleRow(
                    rule_id=rule.rule_id,
                    version=version,
                    tenant_id=cfg.tenant_id,
                    version_hash=rule.version_hash,
                    name=rule.name,
                    description=rule.description,
                    scope=rule.scope.model_dump(mode="json", exclude_none=True),
                    deductions=[d.model_dump(mode="json") for d in rule.deductions],
                    tolerance=rule.tolerance.model_dump(mode="json"),
                    priority=rule.priority,
                    effective_confidence=rule.effective_confidence,
                    effective_from=rule.effective_from,
                    effective_to=rule.effective_to,
                    status="active",
                    origin="imported",
                    created_by=actor,
                    created_at=now,
                    activated_by=actor,
                    activated_at=now,
                )
            )
            added += 1

        if not added:
            print(f"{args.rule_set}: already live, nothing to restore")
            return 0
        if not args.apply:
            print(f"\n{added} rule(s) would be restored; re-run with --apply")
            return 0
        await session.commit()
        print(f"\nrestored {added} rule(s) into {args.rule_set}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
