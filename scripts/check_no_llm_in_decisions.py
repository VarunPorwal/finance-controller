#!/usr/bin/env python
"""CI ``guards`` job (PRD §12.6): fail if ``fc.llm`` is reachable from a
decision module, or from a module hard rule 6 requires to run with no
network.

Mirrors ``tests/unit/test_architecture.py``'s two import-graph tests (same
package lists, same syntactic-forms check, so an import that slips past one
slips past neither) as the standalone CLI entrypoint PRD §12.6 names.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_SRC = ROOT / "engine" / "src"

#: Modules whose output decides whether money is reconciled (CLAUDE.md hard rule 2).
DECISION_PACKAGES = ("fc/matching", "fc/rules/evaluator.py", "fc/exceptions/tier.py", "fc/cash")

#: Modules that must run with no network, whatever ``LLM_MODE`` says (hard
#: rule 6: ``make eval`` runs with no database and no network).
NETWORK_FREE_PACKAGES = ("fc/pipeline.py", "fc/eval", "fc/generator")


def _imports_the_llm(node: ast.AST) -> bool:
    """Every syntactic way of reaching ``fc.llm``, including ``from fc import
    llm`` and a relative ``from ..llm import router`` — a ban with a hole
    anyone would fall into by accident is not a ban."""
    if isinstance(node, ast.Import):
        return any(
            alias.name == "fc.llm" or alias.name.startswith("fc.llm.") for alias in node.names
        )
    if not isinstance(node, ast.ImportFrom):
        return False

    module = node.module or ""
    if node.level == 0:
        if module == "fc.llm" or module.startswith("fc.llm."):
            return True
        return module == "fc" and any(alias.name == "llm" for alias in node.names)
    if module == "llm" or module.startswith("llm."):
        return True
    return not module and any(alias.name == "llm" for alias in node.names)


def _modules_for(target: str) -> list[Path]:
    path = ENGINE_SRC / target
    if path.is_dir():
        return sorted(path.rglob("*.py"))
    return [path] if path.exists() else []


def _scan(targets: tuple[str, ...]) -> list[str]:
    offenders: list[str] = []
    for target in targets:
        for module in _modules_for(target):
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)) and _imports_the_llm(node):
                    offenders.append(f"{module.relative_to(ENGINE_SRC)}:{node.lineno}")
    return offenders


def main() -> int:
    decision_offenders = _scan(DECISION_PACKAGES)
    network_offenders = _scan(NETWORK_FREE_PACKAGES)
    offenders = decision_offenders + network_offenders
    if offenders:
        print("fc.llm imported where CLAUDE.md forbids it:", file=sys.stderr)
        for offender in offenders:
            print(f"  {offender}", file=sys.stderr)
        return 1
    print("no fc.llm import in decision modules or network-free modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
