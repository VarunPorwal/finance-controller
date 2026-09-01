/**
 * Prefetch loader for this route, kept out of `page.tsx` on purpose.
 *
 * Next's App Router type-checks every `page.tsx` against a closed set of
 * allowed exports — a default component and a fixed list of route config
 * symbols, and nothing else. Exporting a loader beside the component fails the
 * production build with "Property 'fetch...' is incompatible with index
 * signature". A sibling module is not a route file, so it may export whatever
 * the page and the app shell both need to import.
 */


import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";
import { StatusPill } from "@/components/ui/status-pill";
import { PlaceholderPanel } from "@/components/placeholder-panel";
import { queryKeys } from "@/lib/query-keys";

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
  return {
    evalResult: evalRes.data ?? null,
    confusion: confusionRes.data ?? null,
    coverageCurve: coverageRes.data ?? null,
  };
}
