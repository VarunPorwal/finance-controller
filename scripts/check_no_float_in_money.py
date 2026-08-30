#!/usr/bin/env python
"""CI ``guards`` job (PRD §12.6): fail if a float literal or ``float()``/
``round()`` call reaches a money-arithmetic module.

Mirrors ``tests/unit/test_architecture.py::test_no_float_in_the_money_path``
exactly (same trees, same AST check) so the two can never silently disagree —
that test is the one CLAUDE.md and PRD §12.3 actually describe; this script is
the standalone CLI entrypoint PRD §12.6's ``guards`` job names, for a job that
should fail fast without paying for the rest of the pytest run.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE_SRC = ROOT / "engine" / "src"

#: Trees that carry money arithmetic (PRD §12.3), scanned by ``rglob`` so a new
#: module is covered the moment it is written.
MONEY_TREES = ("fc/models/money.py", "fc/matching", "fc/rules", "fc/cash")


def _money_modules() -> list[Path]:
    found: list[Path] = []
    for target in MONEY_TREES:
        path = ENGINE_SRC / target
        if path.is_dir():
            found.extend(sorted(path.rglob("*.py")))
        elif path.exists():
            found.append(path)
    return found


def _offences(module: Path) -> list[str]:
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    offences: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offences.append(
                f"{module.relative_to(ENGINE_SRC)}:{node.lineno}: float literal {node.value!r}"
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"float", "round"}
        ):
            offences.append(
                f"{module.relative_to(ENGINE_SRC)}:{node.lineno}: {node.func.id}() call"
            )
    return offences


def main() -> int:
    modules = _money_modules()
    if not modules:
        print("no money modules found; the scan is mis-rooted", file=sys.stderr)
        return 1
    offences = [offence for module in modules for offence in _offences(module)]
    if offences:
        print("float found in a money module (CLAUDE.md hard rule 1):", file=sys.stderr)
        for offence in offences:
            print(f"  {offence}", file=sys.stderr)
        return 1
    print(f"no float in {len(modules)} money module(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
