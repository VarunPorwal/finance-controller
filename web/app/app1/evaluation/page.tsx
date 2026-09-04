"use client";

// Evaluation. How accurate is it, measured? Ground truth only exists for the
// generated demo corpus, so this screen is empty for a run without one.

import { useQueries } from "@tanstack/react-query";
import { apiClient } from "@/lib/client";
import { FcCard, FcChip, FcEmpty, FcErrorNote, FcHead, FcPage, FcSection, FcSkeleton } from "../_components/fc-ui";
import { useCoverageCurve, useConfusion, useRuns, errorMessage, type EvalResult } from "../_lib/api";
import { Headline } from "./headline";
import { CoverageCurve } from "./curve";
import { ConfusionTables } from "./confusion";
import { HonestList } from "./failures";
import { Determinism } from "./determinism";
import { curveOf, failuresOf, gatesOf } from "./shape";

/** Evaluation only ever produces a result for the demo corpus run — that's
 * the only data with ground truth to check against. Whatever run happens to
 * be "current" elsewhere in the app is irrelevant here: this screen always
 * shows the demo corpus's own evaluation, found by checking every run for
 * one that actually has a result, newest first. */
function useDemoCorpusEval() {
  const runs = useRuns("all", 30);
  const candidates = runs.data ?? [];
  const results = useQueries({
    queries: candidates.map((r) => ({
      queryKey: ["a1", "run", r.run_id, "eval"],
      retry: 0,
      enabled: candidates.length > 0,
      queryFn: async () => {
        const res = await apiClient.GET("/api/v1/eval/{run_id}", { params: { path: { run_id: r.run_id } } });
        return res.error ? null : (res.data ?? null);
      },
    })),
  });

  const loading = runs.isLoading || (candidates.length > 0 && results.some((r) => r.isLoading));
  const best = candidates.reduce<{ run: (typeof candidates)[number]; ev: EvalResult } | null>((acc, r, i) => {
    const ev = results[i]?.data;
    if (ev && (!acc || r.started_at > acc.run.started_at)) return { run: r, ev };
    return acc;
  }, null);
  return { data: best, loading, error: runs.error };
}

export default function EvaluationPage() {
  const demo = useDemoCorpusEval();
  const runId = demo.data?.run.run_id;
  const run = demo.data?.run;
  const ev = demo.data?.ev;
  const { data: curve } = useCoverageCurve(runId);
  const { data: confusion } = useConfusion(runId);

  const anyError = demo.error ? errorMessage(demo.error) : undefined;
  const loading = demo.loading;

  return (
    <FcPage>
      <FcHead
        title="Evaluation"
        sub="How accurate is it, measured?"
        actions={<FcChip>Always the demo corpus run — the only one with ground truth</FcChip>}
      />

      {anyError ? (
        <FcErrorNote message={anyError} />
      ) : loading ? (
        <FcCard>
          <FcSkeleton className="h-40" />
        </FcCard>
      ) : !ev ? (
        <FcCard>
          <FcEmpty
            title="No demo corpus run yet"
            sub="Evaluation is measured against the generated demo corpus, because only that corpus carries ground truth. Run the demo corpus once and its evaluation will always show here, regardless of whatever run is active elsewhere."
          />
        </FcCard>
      ) : (
        <div className="flex flex-col gap-6">
          <p className="fc-faint" style={{ fontSize: 12 }}>
            This evaluation is measured on the generated demo corpus, run #{run?.run_id.slice(-6).toUpperCase()},
            because that corpus is the only data carrying ground truth to check against.
          </p>
          <Headline ev={ev} />

          <div className="fc-split" style={{ alignItems: "stretch" }}>
            <FcSection title="Coverage against precision" sub="Lower the threshold and more closes on its own, at the cost of wrong closures.">
              {curve?.points?.length ? (
                <CoverageCurve points={curveOf(curve.points)} shipped={Number(ev.auto_threshold)} />
              ) : (
                <FcCard>
                  <FcEmpty title="No coverage curve for this run" />
                </FcCard>
              )}
            </FcSection>

            <div className="fc-stack" style={{ display: "grid", gridTemplateRows: "auto 1fr", height: "100%" }}>
              <FcSection title="Same seed, same output" sub="Replay a run under the same ruleset and the diff is empty.">
                <Determinism runId={runId} rulesetHash={run?.ruleset_hash} gates={gatesOf(ev)} />
              </FcSection>

              <FcSection title="Where ground truth exists" sub="Evaluation only runs where a labelled answer exists to check against.">
                <FcCard style={{ flex: "1 1 auto", display: "flex", flexDirection: "column", justifyContent: "center", boxSizing: "border-box" }}>
                  <p className="fc-body" style={{ margin: 0 }}>
                    This run carries ground truth from the generated demo corpus, so every figure above is measured
                    against a known-correct answer for each item, not estimated.
                  </p>
                </FcCard>
              </FcSection>
            </div>
          </div>

          <div id="fc-eval-confusion">
            <FcSection title="By category and by stage" sub="Diagnostic, not headline: where precision and recall actually break down.">
              {confusion ? (
                <ConfusionTables confusion={confusion} />
              ) : (
                <FcCard>
                  <FcSkeleton className="h-40" />
                </FcCard>
              )}
            </FcSection>
          </div>

          <div id="fc-eval-failures">
            <FcSection title="What it got wrong, and why" sub="Every disagreement with ground truth, largest first.">
              <HonestList failures={failuresOf(ev)} />
            </FcSection>
          </div>
        </div>
      )}
    </FcPage>
  );
}
