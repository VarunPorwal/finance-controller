"""Text-to-SQL guardrails — PRD §7.8.

The first of three independent layers. The other two (a read-only transaction
and RLS) are proven in ``tests/integration/test_agent_sql_isolation.py`` against
a real database; this file proves the parser layer on its own, with no database
at all, which is the point of it being pure text in and pure text out.
"""

from __future__ import annotations

import pytest

from fc.llm.sql_guard import ALLOWED_TABLES, MAX_ROWS, SqlRejected, guard

TENANT = "t_lumea"


def _guard(sql: str) -> str:
    return guard(sql, tenant_id=TENANT)


# --- what must be refused ----------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM exceptions",
        "DELETE FROM exceptions WHERE exception_id = 'exc_1'",
        "UPDATE exceptions SET status = 'resolved'",
        "INSERT INTO exceptions (exception_id) VALUES ('x')",
        "DROP TABLE exceptions",
        "TRUNCATE exceptions",
        "ALTER TABLE exceptions ADD COLUMN x text",
        "CREATE TABLE evil (id text)",
        "GRANT ALL ON exceptions TO PUBLIC",
    ],
)
def test_anything_that_writes_is_refused(sql: str) -> None:
    with pytest.raises(SqlRejected):
        _guard(sql)


def test_a_delete_hidden_inside_a_cte_is_refused_too() -> None:
    """The tree is walked, not just its root — a data-modifying CTE is a real
    Postgres feature and would otherwise sail past a top-level type check."""
    with pytest.raises(SqlRejected, match="DELETE"):
        _guard("WITH gone AS (DELETE FROM exceptions RETURNING *) SELECT * FROM gone")


def test_a_second_statement_is_refused_rather_than_ignored() -> None:
    with pytest.raises(SqlRejected, match="exactly one statement"):
        _guard("SELECT exception_id FROM exceptions; DROP TABLE runs")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users",
        "SELECT * FROM pg_catalog.pg_user",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM tenants",
        "SELECT e.x FROM exceptions e JOIN secrets s ON s.id = e.exception_id",
    ],
)
def test_a_table_outside_the_whitelist_is_refused(sql: str) -> None:
    with pytest.raises(SqlRejected, match="unknown or forbidden table"):
        _guard(sql)


def test_a_query_naming_a_tenant_itself_is_refused_not_silently_rewritten() -> None:
    """Refused because it is worth looking at, not because it would work — the
    injected predicate and RLS both stand in the way regardless. Silently
    overwriting it would hide a query that tried."""
    with pytest.raises(SqlRejected, match="tenant_id"):
        _guard("SELECT exception_id FROM exceptions WHERE tenant_id = 't_other'")


def test_a_query_reading_no_table_is_refused() -> None:
    with pytest.raises(SqlRejected, match="reads no table"):
        _guard("SELECT 1")


def test_unparseable_sql_is_refused_with_a_reason() -> None:
    with pytest.raises(SqlRejected, match="parse"):
        _guard("SELECT FROM WHERE ORDER wat")


# --- what must be rewritten --------------------------------------------------


def test_the_tenant_predicate_is_injected_on_a_plain_select() -> None:
    out = _guard("SELECT SUM(residual_paise) FROM exceptions WHERE status = 'open'")
    assert f"exceptions.tenant_id = '{TENANT}'" in out


def test_every_joined_table_gets_its_own_predicate() -> None:
    out = _guard(
        "SELECT e.counterparty_norm FROM exceptions x "
        "JOIN transaction_events e ON e.event_id = ANY(x.event_ids)"
    )
    assert f"x.tenant_id = '{TENANT}'" in out
    assert f"e.tenant_id = '{TENANT}'" in out


def test_a_cte_body_and_a_subquery_are_each_scoped_in_their_own_right() -> None:
    """Every scope, not just the outermost one — an unscoped CTE would read
    another tenant's rows and hand them to a scoped outer query."""
    out = _guard(
        "WITH recent AS (SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1) "
        "SELECT COUNT(*) FROM matches m WHERE m.run_id IN (SELECT run_id FROM recent)"
    )
    assert f"runs.tenant_id = '{TENANT}'" in out
    assert f"m.tenant_id = '{TENANT}'" in out


def test_a_scalar_subquery_in_the_where_clause_is_scoped() -> None:
    out = _guard(
        "SELECT COUNT(*) FROM exceptions WHERE run_id = "
        "(SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1)"
    )
    assert out.count(f"tenant_id = '{TENANT}'") == 2


def test_the_row_cap_is_applied() -> None:
    assert f"LIMIT {MAX_ROWS}" in _guard("SELECT exception_id FROM exceptions")


def test_a_smaller_limit_the_query_asked_for_is_honoured() -> None:
    out = _guard("SELECT exception_id FROM exceptions ORDER BY amount_paise DESC LIMIT 5")
    assert "LIMIT 5" in out
    assert str(MAX_ROWS) not in out


def test_a_larger_limit_is_capped() -> None:
    out = _guard("SELECT exception_id FROM exceptions LIMIT 100000")
    assert f"LIMIT {MAX_ROWS}" in out
    assert "100000" not in out


def test_the_whitelist_is_the_nine_tables_the_prd_names() -> None:
    assert ALLOWED_TABLES == {
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


def test_the_rewrite_refuses_rather_than_emitting_unscoped_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The postcondition that makes the rewrite honest.

    This is a regression test for a failure that actually happened during this
    build: sqlglot renamed the FROM argument key between major versions, which
    turned the injection into a silent no-op. Every existing test still passed,
    because the SQL was still valid and still returned rows — it just returned
    every tenant's. Simulating that by blinding the source-finder proves the
    guard now reports rather than assumes.
    """
    monkeypatch.setattr("fc.llm.sql_guard._sources_of", lambda select: [])
    with pytest.raises(SqlRejected, match="could not scope"):
        _guard("SELECT exception_id FROM exceptions")


def test_a_comma_join_scopes_both_tables() -> None:
    out = _guard("SELECT r.run_id FROM runs r, exceptions e WHERE e.run_id = r.run_id")
    assert f"r.tenant_id = '{TENANT}'" in out
    assert f"e.tenant_id = '{TENANT}'" in out
