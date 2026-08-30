"""Put the pure engine on the import path. Tests need no database and no network."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "engine" / "src")):
    if path not in sys.path:
        sys.path.insert(0, path)


# --- a skipped test is an unrun proof, not a pass ----------------------------

REQUIRE_DB_ENV = "FC_REQUIRE_DB"

#: Suites whose skips are never acceptable on a gating run. Unit tests may skip
#: freely — nothing there needs a database — but an integration or eval test
#: that skips has proved nothing while reporting success.
_GATED = ("tests/integration", "tests/eval", "tests\integration", "tests\eval")


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # type: ignore[no-untyped-def]
    """Fail the run when a gated test skipped, and say which.

    Earlier in this build 21-29 integration tests skipped silently because Neon
    was cold, on a run that reported green. That meant the RLS and
    read-only-transaction proofs — the two things the text-to-SQL safety claim
    rests on — had never executed on the run that was used to justify them.
    pytest counts a skip as success, so this makes ``check`` disagree.

    Only active when ``FC_REQUIRE_DB=1``, which ``dev.ps1 check`` sets. A
    developer running ``pytest`` on a plane still gets skips.
    """
    import os

    if os.environ.get(REQUIRE_DB_ENV) != "1":
        return
    skipped = [
        report
        for report in terminalreporter.stats.get("skipped", [])
        if any(part in str(getattr(report, "nodeid", "")) for part in _GATED)
    ]
    if not skipped:
        return

    terminalreporter.write_sep("=", "SKIPPED PROOFS", red=True, bold=True)
    terminalreporter.write_line(
        f"{len(skipped)} gated test(s) skipped. A skipped test proves nothing, and this "
        "run was supposed to prove things. Fix the environment and re-run."
    )
    for report in skipped:
        reason = ""
        longrepr = getattr(report, "longrepr", None)
        if isinstance(longrepr, tuple) and len(longrepr) == 3:
            reason = str(longrepr[2])
        terminalreporter.write_line(f"  {report.nodeid}  --  {reason}")
    # pytest has already decided the run passed; override it.
    terminalreporter._session.exitstatus = 1
    config.option.__dict__.setdefault("_fc_skipped_proofs", True)


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-untyped-def]
    """Belt and braces: the summary hook sets exitstatus, this makes it stick."""
    import os

    if os.environ.get(REQUIRE_DB_ENV) != "1":
        return
    skipped = [
        report
        for report in session.config.pluginmanager.get_plugin("terminalreporter").stats.get(
            "skipped", []
        )
        if any(part in str(getattr(report, "nodeid", "")) for part in _GATED)
    ]
    if skipped:
        session.exitstatus = 1
