"""Text-to-SQL guardrails — PRD §7.8.

Parse, reject, constrain, rewrite. Pure text in, pure text out: this module
never touches a database, which is what lets the whole guard be unit-tested
without one.

It is the first of three independent layers, and it is deliberately not the
only one. The other two live in ``api/routers/agent.py``: the query runs inside
a ``SET TRANSACTION READ ONLY`` transaction, on the RLS-scoped application
role. Each layer is sufficient on its own — a mutating statement that somehow
got past this parser is still refused by Postgres, and a cross-tenant predicate
that got past the rewrite below still returns nothing under RLS.

(The PRD originally named a dedicated read-only database role as the second
layer. On Neon, the role that connection string points at carries
``rolbypassrls`` through ``neon_superuser``, so using it would have traded RLS
away to gain a read-only guarantee the transaction already provides. The
read-only role is optional hardening now, not the mechanism.)
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlglot
from sqlglot import exp

__all__ = [
    "ALLOWED_TABLES",
    "FORBIDDEN_NODES",
    "MAX_ROWS",
    "STATEMENT_TIMEOUT_MS",
    "TENANT_SCOPED_TABLES",
    "SqlRejected",
    "guard",
]

#: §7.8. Nothing outside this set is visible to a generated query.
ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "transaction_events",
        "matches",
        "exceptions",
        "clusters",
        "rules",
        "runs",
        "eval_results",
        "audit_events",
        "llm_calls",
    }
)

#: Every allowed table carries ``tenant_id``, so every one gets a predicate.
TENANT_SCOPED_TABLES: frozenset[str] = ALLOWED_TABLES

FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.Grant,
    exp.Command,
    exp.Merge,
    exp.Into,
    exp.Set,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)

MAX_ROWS = 500
STATEMENT_TIMEOUT_MS = 3000


class SqlRejected(ValueError):
    """The generated SQL did not survive the guard. Carries a reason the user
    can be shown: a refusal that does not say why is indistinguishable from a
    bug, and this one is a feature."""


def guard(sql: str, *, tenant_id: str, max_rows: int = MAX_ROWS) -> str:
    """Validate and rewrite one generated statement, or raise :class:`SqlRejected`.

    Order matters: reject before rewriting, so a hostile statement is never
    partially processed, and inject the tenant predicate before applying the
    limit, so the limit applies to already-scoped rows.
    """
    statements = _parse(sql)
    if len(statements) != 1:
        raise SqlRejected(
            f"expected exactly one statement, got {len(statements)} — "
            "a second statement is never part of an answer"
        )
    tree = statements[0]

    # sqlglot models a query as ``Query`` and a node as ``Expression``; a SELECT
    # is both, and anything that is not a Query is not a read.
    if not isinstance(tree, exp.Query):
        raise SqlRejected(f"only SELECT is allowed, got {type(tree).__name__.upper()}")

    _assert_no_forbidden_nodes(tree)
    _assert_tables_allowed(tree)
    _assert_no_tenant_literal(tree)

    tree = _inject_tenant_predicate(tree, tenant_id)
    tree = _apply_limit(tree, max_rows)
    return tree.sql(dialect="postgres")


def _parse(sql: str) -> list[exp.Expression]:
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.ParseError as exc:
        raise SqlRejected(f"could not parse the generated SQL: {exc}") from exc
    return [statement for statement in parsed if isinstance(statement, exp.Expression)]


def _assert_no_forbidden_nodes(tree: exp.Expression) -> None:
    """Walks the whole tree, so a DELETE hidden inside a CTE is caught too."""
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SqlRejected(
                f"{type(node).__name__.upper()} is not allowed — this path can only read"
            )


def _table_names(tree: exp.Expression) -> set[str]:
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    names: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if name and name not in cte_names:
            names.add(name)
    return names


def _assert_tables_allowed(tree: exp.Expression) -> None:
    referenced = _table_names(tree)
    if not referenced:
        raise SqlRejected("the query reads no table")
    unknown = sorted(referenced - ALLOWED_TABLES)
    if unknown:
        raise SqlRejected(
            f"unknown or forbidden table(s): {', '.join(unknown)}. "
            f"Readable tables are: {', '.join(sorted(ALLOWED_TABLES))}"
        )


def _assert_no_tenant_literal(tree: exp.Expression) -> None:
    """A model-supplied tenant filter is refused rather than trusted.

    Not because it would work — RLS and the injected predicate both stand in
    the way — but because a query that tries to name a tenant is a query that
    should be looked at, and silently overwriting it hides that.
    """
    for column in tree.find_all(exp.Column):
        if column.name.lower() != "tenant_id":
            continue
        parent = column.parent
        if isinstance(parent, exp.Binary | exp.In) and any(
            isinstance(operand, exp.Literal) for operand in parent.iter_expressions()
        ):
            raise SqlRejected(
                "the query filters on tenant_id itself — tenant scoping is applied "
                "automatically and must not be written into a generated query"
            )


def _inject_tenant_predicate(tree: exp.Expression, tenant_id: str) -> exp.Expression:
    """Defence in depth on top of RLS (§9.5).

    Every table reference in every scope — top level, subquery, CTE body — gets
    ``<alias>.tenant_id = '<tenant>'`` added to its own SELECT's WHERE clause.

    Then it checks its own work, and refuses the query if any tenant-scoped
    table reference went uncovered. That postcondition is not defensive
    programming for its own sake: this rewrite is the tenant-isolation layer,
    and the way it fails is *silently* — sqlglot renamed the FROM argument key
    between major versions, which turned the whole injection into a no-op that
    every existing test still passed, because the SQL was still valid and still
    returned rows. A layer that can quietly stop working is worse than no layer,
    so it now reports rather than assumes.
    """
    covered = 0
    for select in _all_selects(tree):
        for source in _sources_of(select):
            if source.name.lower() not in TENANT_SCOPED_TABLES:
                continue
            select.where(
                exp.EQ(
                    this=exp.column("tenant_id", table=source.alias_or_name),
                    expression=exp.Literal.string(tenant_id),
                ),
                copy=False,
            )
            covered += 1

    expected = _tenant_scoped_reference_count(tree)
    if covered < expected:
        raise SqlRejected(
            f"could not scope every table reference to the tenant "
            f"({covered} of {expected} covered) — the query shape is not one this "
            "guard can prove safe, so it is refused rather than run"
        )
    return tree


def _tenant_scoped_reference_count(tree: exp.Expression) -> int:
    """How many table references *should* have received a predicate."""
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    return sum(
        1
        for table in tree.find_all(exp.Table)
        if table.name.lower() in TENANT_SCOPED_TABLES and table.name.lower() not in cte_names
    )


def _all_selects(tree: exp.Expression) -> Iterable[exp.Select]:
    return list(tree.find_all(exp.Select))


def _sources_of(select: exp.Select) -> list[exp.Table]:
    """Tables named directly by this SELECT's FROM and JOINs, not by its
    subqueries — those have their own SELECT node and are handled there.

    ``from_`` is sqlglot 30's argument key; ``from`` was 25's. Both are read so
    that a dependency bump degrades into a rejected query (via the caller's
    postcondition) rather than into an unscoped one.
    """
    sources: list[exp.Table] = []
    from_clause = select.args.get("from_") or select.args.get("from")
    if from_clause is not None and isinstance(from_clause.this, exp.Table):
        sources.append(from_clause.this)
    for join in select.args.get("joins") or []:
        if isinstance(join.this, exp.Table):
            sources.append(join.this)
    return sources


def _apply_limit(tree: exp.Expression, max_rows: int) -> exp.Expression:
    """Cap the row count, honouring a smaller limit the query asked for itself."""
    if not isinstance(tree, exp.Query):  # pragma: no cover - guard() rejects these first
        return tree
    existing = tree.args.get("limit")
    if existing is not None:
        try:
            asked = int(existing.expression.name)
        except (AttributeError, ValueError):
            asked = max_rows
        if asked <= max_rows:
            return tree
    limited = tree.limit(max_rows)
    assert isinstance(limited, exp.Expression)
    return limited
