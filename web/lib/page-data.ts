/**
 * Prefetch loaders for the pages the app shell warms on hover.
 *
 * They live here rather than in the page files because Next's App Router
 * type-checks every `app/**\/page.tsx` against a closed set of allowed
 * exports: a page module may export a default component and a fixed list of
 * route config symbols, and *nothing else*. Exporting a loader beside the
 * component fails the production build with "Property 'fetch...Bundle' is
 * incompatible with index signature" - a real constraint, not a lint opinion,
 * so the loaders move out and both the page and the shell import them.
 */

import { apiClient, type components } from "@/lib/client";

type RunSummary = components["schemas"]["RunSummaryOut"];
type AuditEvent = components["schemas"]["AuditEventOut"];
type Rule = components["schemas"]["Rule"];
type LLMCall = components["schemas"]["LLMCallOut"];
type RunOut = components["schemas"]["RunOut"];
type NarrativeOut = components["schemas"]["NarrativeOutModel"];

export interface HistoryPoint {
  label: string;
  eventCount: number;
  autoMatched: number;
}

export interface HomeBundle {
  prevSummary: RunSummary | null;
  history: HistoryPoint[];
}

export interface ActivityBundle {
  runsToday: number;
  activeRuleCount: number;
  avgRuntimeMs: number | null;
  log: AuditEvent[];
  llmCalls: LLMCall[];
  runs: RunOut[];
  narrative: NarrativeOut | null;
}

const HISTORY_WINDOW = 10;

export async function fetchHomeBundle(runId: string): Promise<HomeBundle> {
  const runsRes = await apiClient.GET("/api/v1/runs", {
    params: { query: { status: "complete", kind: "original", limit: HISTORY_WINDOW } },
  });
  const runs = runsRes.data?.items ?? []; // newest first
  let prev: RunSummary | null = null;
  const olderRunId = runs.find((r) => r.run_id !== runId)?.run_id;
  if (olderRunId) {
    const { data } = await apiClient.GET("/api/v1/runs/{run_id}/summary", {
      params: { path: { run_id: olderRunId } },
    });
    prev = data ?? null;
  }

  const chronological = [...runs].reverse(); // oldest first, for a left-to-right trend
  const summaries = await Promise.all(
    chronological.map((r) =>
      apiClient.GET("/api/v1/runs/{run_id}/summary", { params: { path: { run_id: r.run_id } } }),
    ),
  );
  const history: HistoryPoint[] = chronological.map((r, i) => {
    const s = summaries[i].data;
    return {
      label: new Date(r.started_at).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }),
      eventCount: s?.event_count ?? 0,
      autoMatched: s ? s.event_count - s.exception_count : 0,
    };
  });

  return { prevSummary: prev, history };
}

export async function fetchActivityBundle(runId: string | undefined): Promise<ActivityBundle> {
  const [runsRes, rulesRes, auditRes, llmRes, narrativeRes] = await Promise.all([
    apiClient.GET("/api/v1/runs", { params: { query: { status: "complete", limit: 50 } } }),
    apiClient.GET("/api/v1/rules", { params: { query: { status: "active" } } }),
    apiClient.GET("/api/v1/audit", { params: { query: { run_id: runId, limit: 50 } } }),
    apiClient.GET("/api/v1/llm/calls", { params: { query: { run_id: runId, limit: 20 } } }),
    runId
      ? apiClient.GET("/api/v1/agent/narrative/{run_id}", { params: { path: { run_id: runId } } })
      : Promise.resolve({ data: undefined }),
  ]);
  const runsList = runsRes.data?.items ?? [];
  const today = new Date().toDateString();
  const withRuntime = runsList.filter((r) => r.runtime_ms != null);
  const activeRules: Rule[] = rulesRes.data ?? [];
  return {
    runsToday: runsList.filter((r) => new Date(r.started_at).toDateString() === today).length,
    activeRuleCount: new Set(activeRules.map((r) => r.rule_id)).size,
    avgRuntimeMs: withRuntime.length
      ? withRuntime.reduce((s, r) => s + (r.runtime_ms ?? 0), 0) / withRuntime.length
      : null,
    log: auditRes.data?.items ?? [],
    llmCalls: llmRes.data?.items ?? [],
    runs: runsList,
    narrative: narrativeRes.data ?? null,
  };
}
