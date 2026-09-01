"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";
import { StatusPill } from "@/components/ui/status-pill";
import { PlaceholderPanel } from "@/components/placeholder-panel";
import { queryKeys } from "@/lib/query-keys";
import { CategoryStat, ConfusionOut, CoverageCurveOut, CoveragePoint, EvalBundle, EvalResult, fetchEvalBundle } from "./loader";


const STAGE_LABEL: Record<string, string> = {
  exact_ref: "Exact reference match",
  fuzzy: "Amount + date fuzzy match",
  fee_adjusted: "Fee-adjusted match",
  date_shift: "Date-shift match",
  many_to_one: "Many-to-one / subset-sum match",
};

export default function EvaluationPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data, isFetched } = useQuery({
    queryKey: queryKeys.evalBundle(runId),
    queryFn: () => fetchEvalBundle(runId!),
    enabled: !!runId,
  });
  const evalResult = !runId || isFetched ? (data?.evalResult ?? null) : undefined;
  const confusion = data?.confusion ?? null;
  const coverageCurve = data?.coverageCurve ?? null;

  return (
    <div>
      <div className="mb-4.5">
        <div className="text-2xl font-semibold tracking-[-0.025em]">Evaluation</div>
        <div className="mt-[3px] text-[13px] text-text-muted">Measured accuracy, handed over honestly</div>
      </div>

      {evalResult === undefined && <div className="fc-card h-40 animate-pulse" aria-hidden />}

      {evalResult === null && (
        <PlaceholderPanel
          title="No evaluation for this run"
          note="Ground truth only exists for the demo corpus — a run started from real uploaded data (Data Sources) has nothing to score against, so nothing is shown here rather than a guess."
        />
      )}

      {evalResult && (
        <>
          <div className="mb-5 grid grid-cols-4 gap-5">
            {evalResult.gates.map((g) => (
              <div key={g.name as string} className="fc-card">
                <div className="flex items-center justify-between px-[18px] pt-4">
                  <div className="text-[13px] text-text-body">{String(g.name)}</div>
                  <StatusPill tone={g.passed ? "success" : "error"}>{g.passed ? "PASS" : "FAIL"}</StatusPill>
                </div>
                <div className="px-[18px] pt-3.5 pb-5">
                  <div className="fc-numeric text-[22px] font-semibold">{String(g.actual)}</div>
                  <div className="mt-1 text-[11.5px] text-text-muted">threshold {String(g.threshold)}</div>
                </div>
              </div>
            ))}
          </div>

          <div className="mb-5 grid grid-cols-[1.3fr_1fr] gap-5">
            <div className="fc-card overflow-hidden">
              <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
                <div className="text-sm font-semibold">Precision &amp; recall by matching stage</div>
                <button type="button" className="flex items-center gap-1.5 rounded-[7px] border border-border px-3 py-1.5 text-xs font-medium">
                  <Download width={13} height={13} />
                  Export metrics
                </button>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[color:var(--neutral-bg)] text-[11px] font-semibold tracking-[0.03em] text-text-muted">
                    <th className="px-5 py-2.5 text-left">STAGE</th>
                    <th className="px-3 py-2.5 text-right">PRECISION</th>
                    <th className="px-5 py-2.5 text-right">RECALL</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(confusion?.by_stage ?? {}).map(([stage, stats]) => {
                    const s = stats as { precision: number; recall: number };
                    return (
                      <tr key={stage} className="border-b border-[color:var(--neutral-bg)] text-[13px] last:border-0">
                        <td className="px-5 py-3">{STAGE_LABEL[stage] ?? stage}</td>
                        <td className="fc-numeric px-3 py-3 text-right text-base">{(s.precision * 100).toFixed(1)}%</td>
                        <td className="fc-numeric px-5 py-3 text-right text-base">{(s.recall * 100).toFixed(1)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="flex flex-col gap-5">
              <div className="fc-card">
                <div className="px-5 pt-4 text-[13px] text-text-body">False resolutions</div>
                <div className="px-5 pt-3.5 pb-5">
                  <div className="fc-numeric text-[28px] font-semibold">{evalResult.false_auto_resolutions}</div>
                  <div className="mt-1 text-xs text-text-muted">
                    across {evalResult.true_positive + evalResult.false_positive} auto-closed decisions
                  </div>
                </div>
              </div>
              <div className="fc-card">
                <div className="px-5 pt-4 text-[13px] text-text-body">Recall, this run</div>
                <div className="px-5 pt-3.5 pb-5">
                  <div className="rounded-[10px] border border-dashed border-border p-4 text-center text-xs text-text-muted">
                    Trend needs multiple evaluated runs — the demo corpus loads once per tenant, so
                    this fills in as replays accumulate.
                  </div>
                  <div className="fc-numeric mt-2 text-base font-semibold">
                    {evalResult.recall_pct != null ? `${evalResult.recall_pct}%` : "—"}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="mb-5 grid grid-cols-[1.3fr_1fr] gap-5">
            <div className="fc-card overflow-hidden">
              <div className="border-b border-border px-5 py-3.5 text-sm font-semibold">
                Coverage vs. precision, by auto-close threshold
              </div>
              {(!coverageCurve || coverageCurve.points.length === 0) && (
                <div className="p-5 text-center text-sm text-text-muted">No curve points for this run.</div>
              )}
              {coverageCurve && coverageCurve.points.length > 0 && (
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[color:var(--neutral-bg)] text-[11px] font-semibold tracking-[0.03em] text-text-muted">
                      <th className="px-5 py-2.5 text-left">THRESHOLD</th>
                      <th className="px-3 py-2.5 text-right">COVERAGE</th>
                      <th className="px-3 py-2.5 text-right">PRECISION</th>
                      <th className="px-5 py-2.5 text-right">FALSE POS. / ABSTAIN</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(coverageCurve.points as CoveragePoint[]).map((p, i) => (
                      <tr key={i} className="border-b border-[color:var(--neutral-bg)] text-[13px] last:border-0">
                        <td className="fc-numeric px-5 py-2.5">{p.threshold}</td>
                        <td className="fc-numeric px-3 py-2.5 text-right">{(p.coverage * 100).toFixed(1)}%</td>
                        <td className="fc-numeric px-3 py-2.5 text-right">{(p.precision * 100).toFixed(1)}%</td>
                        <td className="fc-numeric px-5 py-2.5 text-right text-text-muted">
                          {p.false_positives} / {p.abstentions}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="fc-card overflow-hidden">
              <div className="border-b border-border px-5 py-3.5 text-sm font-semibold">Precision &amp; recall by category</div>
              {(!confusion || Object.keys(confusion.by_category ?? {}).length === 0) && (
                <div className="p-5 text-center text-sm text-text-muted">No categories scored for this run.</div>
              )}
              {confusion && Object.entries(confusion.by_category ?? {}).length > 0 && (
                <div className="flex flex-col">
                  {Object.entries(confusion.by_category).map(([category, stat]) => {
                    const s = stat as CategoryStat;
                    return (
                      <div
                        key={category}
                        className="flex items-center justify-between border-b border-[color:var(--neutral-bg)] px-5 py-3 text-[13px] last:border-0"
                      >
                        <div>
                          <div>{category.replace(/_/g, " ")}</div>
                          <div className="text-[11.5px] text-text-muted">
                            {s.correct}/{s.raised} raised · {s.gt_total} in ground truth
                          </div>
                        </div>
                        <div className="fc-numeric text-right text-xs text-text-muted">
                          P {(s.precision * 100).toFixed(0)}% · R {(s.recall * 100).toFixed(0)}%
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="fc-card overflow-hidden">
            <div className="border-b border-border px-5 py-3.5 text-sm font-semibold">
              What we got wrong — {evalResult.failures.length} item(s), generated from this run
            </div>
            {evalResult.failures.length === 0 && (
              <div className="p-5 text-center text-sm text-text-muted">
                Every scored item agreed with ground truth.
              </div>
            )}
            {evalResult.failures.map((f, i) => {
              const failure = f as {
                kind: string;
                event_ids: string[];
                amount_paise: number;
                gt_label: string | null;
                our_label: string;
                why: string;
              };
              return (
                <div key={i} className="border-b border-[color:var(--neutral-bg)] px-5 py-3.5 text-[13px] last:border-0">
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{failure.kind.replace(/_/g, " ")}</span>
                    <span className="fc-numeric text-base font-semibold">{formatPaise(failure.amount_paise)}</span>
                  </div>
                  <div className="mt-1 text-xs text-text-muted">
                    ground truth: {failure.gt_label ?? "none"} · ours: {failure.our_label} — {failure.why}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
