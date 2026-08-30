#!/usr/bin/env python
"""PRD §12.5 quality gates, as the standalone CI entrypoint §12.6's ``eval``
job names.

Runs the same ``evaluate`` / ``check_gates`` pair as ``fc.eval.report.main``
(so there is exactly one place the gate logic lives) and adds the two gates
that need a *second* run to check: recall's cold-run latency budget (a fresh
pipeline run over the corpus, timed) and the cross-process determinism proof
(``fc.eval.report.render``'s in-process determinism gate already re-runs the
cascade once in the same interpreter; PRD §12.4's "same seed twice" claim
about hash-order independence needs a second *process*, which is what
``tests/eval/test_matching_accuracy.py::test_the_run_is_byte_identical_across_processes``
proves — this script does not repeat that subprocess spawn on every CI run,
it only asserts the fast in-process version plus latency).

Writes a JSON report next to the console output when ``--report`` is given,
so CI can upload it as an artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fc.config import load_config
from fc.eval.report import DATA_DIR, GateResult, check_gates, evaluate, load_corpus, render

#: PRD §12.5: "Cold run 500 records < 15 s", release gate.
COLD_RUN_BUDGET_SECONDS = 15.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", type=Path, default=None, help="write gate results as JSON to this path"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="skip the full metrics table, print gates only"
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    if not DATA_DIR.exists():
        print(f"no corpus at {DATA_DIR}; run the generate target first", file=sys.stderr)
        return 1

    corpus = load_corpus()
    report = evaluate(corpus, cfg)
    # ``report.runtime_seconds`` times the pipeline run alone (fc.eval.report
    # wraps only that call). ``evaluate()`` as a whole also sweeps the
    # coverage-precision curve — 31 extra cascade runs that exist to inform
    # threshold selection, not to reconcile anything — so timing the whole
    # call here would gate the eval *harness*'s own instrumentation against a
    # budget PRD §12.5 states for the reconciliation run itself.
    cold_run_seconds = float(report.runtime_seconds)

    if not args.quiet:
        print(render(report))

    gates = [
        *check_gates(report, cfg),
        GateResult(
            name="cold run 500 records",
            passed=cold_run_seconds < COLD_RUN_BUDGET_SECONDS,
            actual=f"{cold_run_seconds:.2f}s",
            threshold=f"< {COLD_RUN_BUDGET_SECONDS:.0f}s",
        ),
    ]

    print("Quality gates (PRD 12.5)")
    for gate in gates:
        mark = "PASS" if gate.passed else "FAIL"
        print(f"  [{mark}] {gate.name:<38} {gate.actual}  (needs {gate.threshold})")
    print("")

    if args.report is not None:
        args.report.write_text(
            json.dumps(
                {
                    "gates": [
                        {
                            "name": g.name,
                            "passed": g.passed,
                            "actual": g.actual,
                            "threshold": g.threshold,
                        }
                        for g in gates
                    ],
                    "records_processed": report.records_processed,
                    "false_auto_resolutions": report.false_auto_resolutions,
                    "recall": str(report.recall),
                    "human_queue_size": report.human_queue_size,
                    "workload_reduction": str(report.workload_reduction),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    failed = [gate for gate in gates if not gate.passed]
    for gate in failed:
        print(f"GATE FAILED: {gate.name} = {gate.actual}, needs {gate.threshold}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
