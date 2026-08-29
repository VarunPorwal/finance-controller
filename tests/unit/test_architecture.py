"""Architectural rules that CI enforces later, asserted now so they never regress.

PRD §3.7: ``engine/`` imports nothing from ``api/`` or ``db/``, and ``make eval``
runs with no server and no database.

CLAUDE.md hard rule 2: the LLM never decides whether something is reconciled, so
the decision modules must not import ``fc.llm``.

CLAUDE.md hard rule 1: money is integer paise, never float. PRD §12.3 specifies
an AST scan of ``engine/matching``, ``engine/rules`` and ``engine/cash`` for it.
Until stage 5 landed that scan existed only in ``test_money.py``, over
``money.py`` alone - so the most arithmetic-heavy package in the engine was
unscanned, and a weighted fuzzy score written the obvious way
(``0.35 * amount_proximity + ...``) would have introduced float into the money
path with every test still green.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ENGINE_SRC = Path(__file__).resolve().parents[2] / "engine" / "src"

FORBIDDEN_IN_ENGINE = ("api", "db", "sqlalchemy", "alembic", "fastapi", "asyncpg")

#: Modules whose output decides whether money is reconciled (CLAUDE.md rule 2).
DECISION_PACKAGES = ("fc/matching", "fc/rules/evaluator.py", "fc/exceptions/tier.py", "fc/cash")

#: Modules that must run with no network, whatever ``LLM_MODE`` says (hard
#: rule 6: ``make eval`` runs with no database and no network). The mode flag is
#: a runtime switch and can be set wrongly; an import graph cannot. ``fc/llm``
#: reaching any of these would make "the accuracy suite needs no network" a
#: claim about configuration rather than about the code.
NETWORK_FREE_PACKAGES = ("fc/pipeline.py", "fc/eval", "fc/generator")

#: Trees that carry money arithmetic (PRD §12.3), scanned by ``rglob`` so a new
#: module is covered the moment it is written rather than when somebody
#: remembers to add it here.
MONEY_TREES = ("fc/models/money.py", "fc/matching", "fc/rules", "fc/cash")


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


def _imports_the_llm(node: ast.AST) -> bool:
    """Every syntactic way of reaching ``fc.llm`` from a decision module.

    Matching only ``node.module.startswith("fc.llm")`` left two doors open, and
    both are the *natural* thing to write rather than an evasion:

    * ``from fc import llm`` - module is ``"fc"``, which does not start with
      ``"fc.llm"``, and ``llm.route(...)`` then works perfectly well;
    * ``from ..llm import router`` - a relative import from ``fc/matching/``,
      where ``node.module`` is ``"llm"`` and ``node.level`` is 2.

    A ban with a hole that anyone would fall into by accident is not a ban.
    """
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
        # from fc import llm
        return module == "fc" and any(alias.name == "llm" for alias in node.names)
    # Relative: from .llm import x, from ..llm import x, from . import llm
    if module == "llm" or module.startswith("llm."):
        return True
    return not module and any(alias.name == "llm" for alias in node.names)


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
                if _imports_the_llm(node):
                    offenders.append(f"{module.relative_to(ENGINE_SRC)}:{node.lineno}")
    assert offenders == [], f"decision modules import fc.llm: {offenders}"


def test_the_pipeline_eval_and_generator_do_not_import_the_llm() -> None:
    """Broader than the decision ban, and for a different reason.

    ``fc.pipeline`` and ``fc.eval`` are allowed to *decide* things — that is
    their job. What they may not do is need a network to do it. An import here
    would not break any rule about LLMs deciding money; it would break the
    promise that ``make eval`` runs offline and byte-identically, which is the
    one the determinism gate rests on.
    """
    offenders: list[str] = []
    for target in NETWORK_FREE_PACKAGES:
        path = ENGINE_SRC / target
        candidates = (
            sorted(path.rglob("*.py")) if path.is_dir() else ([path] if path.exists() else [])
        )
        assert candidates, f"{target} matched no modules — the scan is mis-rooted"
        for module in candidates:
            tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
            for node in ast.walk(tree):
                if _imports_the_llm(node):
                    offenders.append(f"{module.relative_to(ENGINE_SRC)}:{node.lineno}")
    assert offenders == [], f"network-free modules import fc.llm: {offenders}"


def test_the_llm_package_is_the_only_place_httpx_is_imported() -> None:
    """``httpx`` is an engine dependency now (PRD Appendix A). Confining it to
    ``fc/llm`` is what keeps "the engine opens no sockets" true of everything
    else — including every module ``make eval`` touches."""
    offenders: list[str] = []
    for module in _engine_modules():
        relative = str(module.relative_to(ENGINE_SRC)).replace("\\", "/")
        if relative.startswith("fc/llm/"):
            continue
        if "httpx" in _imported_roots(module):
            offenders.append(relative)
    assert offenders == [], f"httpx imported outside fc/llm: {offenders}"


def _money_modules() -> list[Path]:
    found: list[Path] = []
    for target in MONEY_TREES:
        path = ENGINE_SRC / target
        if path.is_dir():
            found.extend(sorted(path.rglob("*.py")))
        elif path.exists():
            found.append(path)
    return found


def test_the_money_scan_covers_the_matching_package() -> None:
    """Guards the guard: an empty or mis-rooted glob would pass silently."""
    scanned = {str(p.relative_to(ENGINE_SRC)).replace("\\", "/") for p in _money_modules()}
    assert "fc/matching/stages/fuzzy.py" in scanned
    assert "fc/matching/stages/many_to_one.py" in scanned
    assert "fc/matching/three_way.py" in scanned


@pytest.mark.parametrize("module", _money_modules(), ids=lambda p: str(p.name))
def test_no_float_in_the_money_path(module: Path) -> None:
    """PRD §12.3. No float literal, no ``float()``, no ``round()``.

    ``Decimal`` division is deliberately allowed: §6.6 and §6.3's fuzzy score are
    both ratios, and computing them in ``Decimal`` is the *correct* way to keep
    money exact. What is forbidden is the binary float type entering the path at
    all, because a score that drifts by 1e-17 makes "same seed, byte-identical
    output" false in the fourth decimal.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    offences: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            offences.append(f"float literal {node.value!r} at line {node.lineno}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"float", "round"}
        ):
            offences.append(f"{node.func.id}() call at line {node.lineno}")
    assert offences == [], f"{module.relative_to(ENGINE_SRC)}: " + "; ".join(offences)


@pytest.mark.parametrize(
    "source",
    [
        "import fc.llm",
        "import fc.llm.router",
        "from fc.llm import route",
        "from fc.llm.router import route",
        "from fc import llm",
        "from .llm import route",
        "from ..llm import route",
        "from .. import llm",
    ],
)
def test_the_llm_ban_catches_every_import_form(source: str) -> None:
    """Guards the guard. Two of these used to pass."""
    tree = ast.parse(source)
    assert any(_imports_the_llm(node) for node in ast.walk(tree)), source


@pytest.mark.parametrize(
    "source",
    [
        "from fc.models.match import MatchResult",
        "from fc import config",
        "from .stages import StageMatch",
        "import fc.llmx",
        "from fc.llmx import thing",
        "from fc import llm_stub",
    ],
)
def test_the_llm_ban_does_not_fire_on_innocent_imports(source: str) -> None:
    """A ban that also catches ``fc.llmx`` would be quietly worked around."""
    tree = ast.parse(source)
    assert not any(_imports_the_llm(node) for node in ast.walk(tree)), source
