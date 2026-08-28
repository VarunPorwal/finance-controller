"""Architectural rules that CI enforces later, asserted now so they never regress.

PRD §3.7: ``engine/`` imports nothing from ``api/`` or ``db/``, and ``make eval``
runs with no server and no database.

CLAUDE.md hard rule 2: the LLM never decides whether something is reconciled, so
the decision modules must not import ``fc.llm``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ENGINE_SRC = Path(__file__).resolve().parents[2] / "engine" / "src"

FORBIDDEN_IN_ENGINE = ("api", "db", "sqlalchemy", "alembic", "fastapi", "asyncpg")

#: Modules whose output decides whether money is reconciled (CLAUDE.md rule 2).
DECISION_PACKAGES = ("fc/matching", "fc/rules/evaluator.py", "fc/exceptions/tier.py", "fc/cash")


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _engine_modules() -> list[Path]:
    return sorted(ENGINE_SRC.rglob("*.py"))


def test_engine_modules_exist() -> None:
    assert _engine_modules(), "no engine modules found; the path is wrong"


@pytest.mark.parametrize("module", _engine_modules(), ids=lambda p: str(p.name))
def test_engine_imports_nothing_from_api_or_db(module: Path) -> None:
    offending = _imported_roots(module) & set(FORBIDDEN_IN_ENGINE)
    assert not offending, f"{module.relative_to(ENGINE_SRC)} imports {sorted(offending)}"


def test_decision_modules_do_not_import_the_llm() -> None:
    """fc.matching, fc.rules.evaluator, fc.exceptions.tier and fc.cash stay LLM-free."""
    offenders: list[str] = []
    for target in DECISION_PACKAGES:
        path = ENGINE_SRC / target
        if path.is_dir():
            candidates = sorted(path.rglob("*.py"))
        else:
            candidates = [path] if path.exists() else []
        for module in candidates:
            source = module.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(module))
            for node in ast.walk(tree):
                imports_llm = (
                    isinstance(node, ast.ImportFrom)
                    and node.module is not None
                    and node.module.startswith("fc.llm")
                ) or (
                    isinstance(node, ast.Import)
                    and any(alias.name.startswith("fc.llm") for alias in node.names)
                )
                if imports_llm:
                    offenders.append(f"{module.relative_to(ENGINE_SRC)}:{node.lineno}")
    assert offenders == [], f"decision modules import fc.llm: {offenders}"
