/**
 * Prefetch loader for this route, kept out of `page.tsx` on purpose: Next's
 * App Router only allows a fixed set of exports from a page module.
 */
import { apiClient, type components } from "@/lib/client";

export type EvalResult = components["schemas"]["EvalResultOut"];
export type ConfusionOut = components["schemas"]["ConfusionOut"];
export type CoverageCurveOut = components["schemas"]["CoverageCurveOut"];
export type CoveragePoint = { threshold: string; coverage: number; precision: number; false_positives: number; abstentions: number };
export type CategoryStat = { raised: number; gt_total: number; correct: number; precision: number; recall: number };
export type EvalBundle = { evalResult: EvalResult | null; confusion: ConfusionOut | null; coverageCurve: CoverageCurveOut | null };

export async function fetchEvalBundle(runId: string): Promise<EvalBundle> {
  const [evalRes, confusionRes, coverageRes] = await Promise.all([
    apiClient.GET("/api/v1/eval/{run_id}", { params: { path: { run_id: runId } } }),
    apiClient.GET("/api/v1/eval/{run_id}/confusion", { params: { path: { run_id: runId } } }),
    apiClient.GET("/api/v1/eval/{run_id}/coverage-curve", { params: { path: { run_id: runId } } }),
  ]);
  return { evalResult: evalRes.data ?? null, confusion: confusionRes.data ?? null, coverageCurve: coverageRes.data ?? null };
}
