"use client";

import { useQuery } from "@tanstack/react-query";
import { useRun } from "@/lib/run-context";
import { formatPaise, formatPercent } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/ui/panel";
import { Pill } from "@/components/ui/pill";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { cn } from "@/lib/utils";
import { fetchEvalBundle, type CategoryStat, type CoveragePoint } from "./loader";

const STAGE_LABEL: Record<string, string> = {
  exact_ref: "Exact reference",
  fee_adjusted: "Fee-adjusted",
  date_shift: "Date-shift",
  many_to_one: "Many-to-one / subset-sum",
  fuzzy: "Fuzzy (never auto-closes)",
};

export default function EvaluationPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data, isFetched } = useQuery({ queryKey: queryKeys.evalBundle(runId), queryFn: () => fetchEvalBundle(runId!), enabled: !!runId });
  const evalResult = !runId || isFetched ? (data?.evalResult ?? null) : undefined;
  const confusion = data?.confusion ?? null;
  const coverageCurve = data?.coverageCurve ?? null;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Evaluation" sub="Measured against ground truth the generator wrote. Handed over honestly, failures included." />

      {evalResult === undefined && <Skeleton className="h-64" />}
      {evalResult === null && (
        <EmptyState
          title="No evaluation for this run"
          note="Ground truth only exists for the demo corpus. A run from uploaded files has nothing to score against, so nothing is shown rather than a guess."
        />
      )}

      {evalResult && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {evalResult.gates.map((g) => {
              const gate = g as { name: string; passed: boolean; actual: unknown; threshold: unknown };
              return (
                <div key={gate.name} className={cn("panel px-[18px] pt-4 pb-[18px]", !gate.passed && "border-[rgba(255,107,107,0.4)]")}>
                  <div className="flex items-center justify-between">
                    <div className="label">{gate.name.replace(/_/g, " ")}</div>
                    <Pill tone={gate.passed ? "ok" : "bad"} dot>
                      {gate.passed ? "pass" : "fail"}
                    </Pill>
                  </div>
                  <div className={cn("num mt-3 text-[22px] leading-none font-semibold", gate.passed ? "text-ink" : "text-bad")}>{String(gate.actual)}</div>
                  <div className="num mt-1.5 text-[11px] text-ink-3">gate {String(gate.threshold)}</div>
                </div>
              );
            })}
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.3fr_1fr]">
            <Panel title="Precision and recall, by matching stage" sub="Each stage scored on the pairs it formed" flush>
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="th pl-[18px]">Stage</th>
                    <th className="th text-right">Precision</th>
                    <th className="th pr-[18px] text-right">Recall</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(confusion?.by_stage ?? {}).map(([stage, stats]) => {
                    const s = stats as { precision: number; recall: number };
                    return (
                      <tr key={stage} className="text-[12.5px]">
                        <td className="td pl-[18px] text-ink">{STAGE_LABEL[stage] ?? stage}</td>
                        <td className="td num text-right text-[15px]">{(s.precision * 100).toFixed(1)}%</td>
                        <td className="td num pr-[18px] text-right text-[15px]">{(s.recall * 100).toFixed(1)}%</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Panel>

            <div className="flex flex-col gap-5">
              <div className="panel px-[18px] pt-4 pb-[18px]">
                <div className="label">False auto-resolutions</div>
                <div className={cn("num mt-3 text-[28px] leading-none font-semibold", evalResult.false_auto_resolutions === 0 ? "text-ok" : "text-bad")}>
                  {evalResult.false_auto_resolutions}
                </div>
                <div className="num mt-2 text-[11.5px] text-ink-3">
                  across {evalResult.true_positive + evalResult.false_positive} auto-closed decisions · the merge blocker
                </div>
              </div>
              <div className="panel px-[18px] pt-4 pb-[18px]">
                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <div className="label">Precision</div>
                    <div className="num mt-2 text-[22px] font-semibold">{evalResult.precision_pct != null ? formatPercent(Number(evalResult.precision_pct)) : "—"}</div>
                  </div>
                  <div>
                    <div className="label">Recall</div>
                    <div className="num mt-2 text-[22px] font-semibold">{evalResult.recall_pct != null ? formatPercent(Number(evalResult.recall_pct)) : "—"}</div>
                  </div>
                  <div>
                    <div className="label">Abstained</div>
                    <div className="num mt-2 text-[22px] font-semibold text-ink-2">{evalResult.abstention_pct != null ? formatPercent(Number(evalResult.abstention_pct)) : "—"}</div>
                  </div>
                </div>
                <p className="mt-3 border-t border-line pt-2.5 text-[11px] text-ink-3">
                  Abstention is a correct outcome. When several answers are valid the engine emits an exception, never a guess.
                </p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.3fr_1fr]">
            <Panel title="Coverage against precision" sub="What each auto-close threshold would have closed, and how often wrongly" flush>
              {!coverageCurve || coverageCurve.points.length === 0 ? (
                <div className="px-[18px] py-8 text-center text-[12.5px] text-ink-3">No curve points for this run.</div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr>
                      <th className="th pl-[18px]">Threshold</th>
                      <th className="th">Coverage</th>
                      <th className="th text-right">Precision</th>
                      <th className="th pr-[18px] text-right">False pos. / abstain</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(coverageCurve.points as CoveragePoint[]).map((p, i) => (
                      <tr key={i} className="text-[12.5px]">
                        <td className="td num pl-[18px]">{p.threshold}</td>
                        <td className="td">
                          <div className="flex items-center gap-2">
                            <div className="h-1.5 w-28 overflow-hidden rounded-full bg-surface-3">
                              <div className="h-full bg-accent" style={{ width: `${Math.round(p.coverage * 100)}%` }} />
                            </div>
                            <span className="num text-ink-2">{(p.coverage * 100).toFixed(1)}%</span>
                          </div>
                        </td>
                        <td className={cn("td num text-right", p.precision < 1 ? "text-warn" : "text-ok")}>{(p.precision * 100).toFixed(1)}%</td>
                        <td className="td num pr-[18px] text-right text-ink-3">
                          {p.false_positives} / {p.abstentions}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>

            <Panel title="By category" sub="Raised against ground truth" flush>
              {!confusion || Object.keys(confusion.by_category ?? {}).length === 0 ? (
                <div className="px-[18px] py-8 text-center text-[12.5px] text-ink-3">No categories scored for this run.</div>
              ) : (
                <ul>
                  {Object.entries(confusion.by_category).map(([category, stat]) => {
                    const s = stat as CategoryStat;
                    return (
                      <li key={category} className="flex items-center justify-between border-b border-line px-[18px] py-2.5 text-[12.5px] last:border-0">
                        <div>
                          <div className="text-ink">{category.replace(/_/g, " ")}</div>
                          <div className="num text-[11px] text-ink-3">
                            {s.correct}/{s.raised} raised · {s.gt_total} in ground truth
                          </div>
                        </div>
                        <div className="num text-right text-[11.5px] text-ink-2">
                          P {(s.precision * 100).toFixed(0)}% · R {(s.recall * 100).toFixed(0)}%
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Panel>
          </div>

          <Panel title={`What we got wrong · ${evalResult.failures.length}`} sub="Generated from this run, not curated" flush>
            {evalResult.failures.length === 0 && <div className="px-[18px] py-8 text-center text-[12.5px] text-ok">Every scored item agreed with ground truth.</div>}
            {evalResult.failures.map((f, i) => {
              const failure = f as { kind: string; event_ids: string[]; amount_paise: number; gt_label: string | null; our_label: string; why: string };
              return (
                <div key={i} className="border-b border-line px-[18px] py-3 text-[12.5px] last:border-0">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-ink">{failure.kind.replace(/_/g, " ")}</span>
                    <span className="num text-[15px] font-semibold">{formatPaise(failure.amount_paise)}</span>
                  </div>
                  <div className="mt-1 text-[11.5px] text-ink-3">
                    ground truth <span className="num text-ink-2">{failure.gt_label ?? "none"}</span> · ours{" "}
                    <span className="num text-ink-2">{failure.our_label}</span> · {failure.why}
                  </div>
                </div>
              );
            })}
          </Panel>
        </>
      )}
    </div>
  );
}
