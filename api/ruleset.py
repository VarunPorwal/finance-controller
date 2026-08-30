"""The effective ruleset for a run, resolved from the database.

``data/rules/deductions.yaml`` used to be read at run time, directly, by all
three pipeline entry points. The Rulebook meanwhile authored, back-tested and
activated rules into the ``rules`` table, which nothing in the pipeline ever
queried. The two never met: the tab showed four database rules, the engine ran
thirteen YAML rules, and the two sets shared no ids at all. Every run in
production carried the same ``ruleset_hash`` — including one whose replay
reason was "replay after activating rule_neft_late_credit_v2".

The YAML is now a **provision-time seed**, not a run-time read.
:func:`seed_rules_from_yaml` imports it into ``rules`` once per tenant (it is
idempotent on ``(rule_id, version)``), and :func:`resolve_ruleset` is the only
thing the pipeline asks for a ruleset. Authoring a rule and activating it
therefore changes what the next run computes, which is what the Rulebook
always claimed to do.

**Effective dating.** ``resolve_ruleset`` returns ``status='active'`` rules
only, across all their versions, and lets ``fc.rules.scope`` pick the version
whose ``effective_from``/``effective_to`` window covers each transaction date.
That is how the YAML already expresses a mid-period rate change: two *active*
versions of one rule with adjacent windows, not one retired and one active.

Retired rules are excluded outright. Retirement is an operator saying "stop
using this", and it sets ``effective_to`` to the retirement date while leaving
``effective_from`` untouched — so a rule created and retired on the same day
still spans months of historical dates. Including retired rules would have let
a rule that was live for four minutes reprice a whole quarter. Drafts are
excluded for the plainer reason that nobody has approved them.

**Targeting a historical ruleset.** Each run records the exact rule versions it
used in ``runs.input_hashes['ruleset']``. ``resolve_ruleset(target_hash=...)``
reconstructs that composition, so a replay can be pinned to the ruleset a
previous run actually used rather than whatever is active now. Without it,
``ruleset_hash`` was a stamp nobody could act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from api.converters import rule_from_row
from api.errors import ApiError
from db.models import Rule as RuleRow
from db.models import Run
from fc.models.rule import Rule
from fc.rules.loader import DEFAULT_RULES_PATH, load_rules, ruleset_hash

__all__ = [
    "ResolvedRuleset",
    "composition_of",
    "resolve_ruleset",
    "seed_rules_from_yaml",
]

#: Statuses whose rules take part in a run. Mirrors ``RuleSet.active_on``,
#: which has always filtered on ``status == 'active'``.
_RUNNABLE_STATUSES = ("active",)

#: Key under ``runs.input_hashes`` holding the exact rule versions a run used,
#: as ``"rule_id:version"`` strings.
COMPOSITION_KEY = "ruleset"


@dataclass(frozen=True, slots=True)
class ResolvedRuleset:
    """What a run should compute with, and the stamp that identifies it."""

    rules: tuple[Rule, ...]
    ruleset_hash: str

    @property
    def composition(self) -> list[str]:
        """``["rule_id:version", ...]`` for ``runs.input_hashes``."""
        return [f"{r.rule_id}:{r.version}" for r in self.rules]


def composition_of(run: Run) -> list[str] | None:
    """The rule versions ``run`` recorded, or ``None`` for runs made before this existed."""
    raw = (run.input_hashes or {}).get(COMPOSITION_KEY)
    if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
        return list(raw)
    return None


async def seed_rules_from_yaml(
    session: AsyncSession,
    *,
    tenant_id: str,
    created_at: datetime,
    path: Path | str = DEFAULT_RULES_PATH,
) -> int:
    """Import the YAML ruleset into ``rules`` for ``tenant_id``. Returns rows inserted.

    Idempotent on ``(rule_id, version)``: rules already present are left
    exactly as they are, so a redeploy never disturbs a rule someone has since
    edited, retired or superseded through the Rulebook.
    """
    ruleset = load_rules(path, tenant_id=tenant_id, created_at=created_at)
    existing = {
        (rule_id, version)
        for rule_id, version in (
            await session.execute(
                select(RuleRow.rule_id, RuleRow.version).where(RuleRow.tenant_id == tenant_id)
            )
        ).all()
    }
    inserted = 0
    for rule in ruleset.rules:
        if (rule.rule_id, rule.version) in existing:
            continue
        session.add(
            RuleRow(
                rule_id=rule.rule_id,
                version=rule.version,
                tenant_id=tenant_id,
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
                status=rule.status,
                origin="imported",
                created_by="system:yaml-seed",
                created_at=created_at,
                activated_by="system:yaml-seed" if rule.status == "active" else None,
                activated_at=created_at if rule.status == "active" else None,
            )
        )
        inserted += 1
    if inserted:
        await session.flush()
    return inserted


async def resolve_ruleset(
    session: AsyncSession, *, tenant_id: str, target_hash: str | None = None
) -> ResolvedRuleset:
    """The ruleset a run should use.

    ``target_hash`` pins the result to the composition a previous run recorded
    under that ``ruleset_hash``; omitted, it is everything runnable for the
    tenant right now.
    """
    if target_hash is not None:
        return await _resolve_by_hash(session, tenant_id=tenant_id, target_hash=target_hash)

    rows = (
        await session.scalars(
            select(RuleRow)
            .where(RuleRow.tenant_id == tenant_id, RuleRow.status.in_(_RUNNABLE_STATUSES))
            .order_by(RuleRow.rule_id, RuleRow.version)
        )
    ).all()
    rules = tuple(rule_from_row(r) for r in rows)
    return ResolvedRuleset(rules=rules, ruleset_hash=ruleset_hash(rules))


async def _resolve_by_hash(
    session: AsyncSession, *, tenant_id: str, target_hash: str
) -> ResolvedRuleset:
    run = await session.scalar(
        select(Run)
        .where(Run.tenant_id == tenant_id, Run.ruleset_hash == target_hash)
        .order_by(Run.started_at.desc())
        .limit(1)
    )
    if run is None:
        raise ApiError(
            404,
            "not found",
            f"no run of this tenant used ruleset {target_hash[:12]}…, so its "
            "composition is not on record",
        )
    composition = composition_of(run)
    if composition is None:
        raise ApiError(
            409,
            "not reproducible",
            f"run {run.run_id} predates ruleset composition recording, so the exact "
            "rule versions it used cannot be reconstructed",
        )
    wanted = [(rid, int(ver)) for rid, _, ver in (c.rpartition(":") for c in composition)]
    rows = (
        await session.scalars(
            select(RuleRow)
            .where(
                RuleRow.tenant_id == tenant_id,
                tuple_(RuleRow.rule_id, RuleRow.version).in_(wanted),
            )
            .order_by(RuleRow.rule_id, RuleRow.version)
        )
    ).all()
    if len(rows) != len(wanted):
        found = {(r.rule_id, r.version) for r in rows}
        missing = sorted(f"{rid}:{ver}" for rid, ver in wanted if (rid, ver) not in found)
        raise ApiError(
            409,
            "not reproducible",
            f"{len(missing)} rule version(s) recorded by run {run.run_id} no longer "
            f"exist: {', '.join(missing)}",
        )
    rules = tuple(rule_from_row(r) for r in rows)
    return ResolvedRuleset(rules=rules, ruleset_hash=ruleset_hash(rules))
