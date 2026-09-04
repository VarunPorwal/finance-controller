"use client";

// One data layer for every app1 screen. All reads go through react-query on
// the generated client (CLAUDE.md: never hand-write fetch). Keys are prefixed
// "a1" so they never collide with the other app's cache entries; the run
// provider's refresh() invalidates everything regardless.

import { useQuery, useMutation, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { apiClient, type components, type paths } from "@/lib/client";
import { useRun } from "@/lib/run-context";

export type S = components["schemas"];
export type RunOut = S["RunOut"];
export type RunSummary = S["RunSummaryOut"];
export type Exception = S["Exception_"];
export type Cluster = S["Cluster"];
export type CashBridge = S["CashBridgeOut"];
export type EvalResult = S["EvalResultOut"];
export type Rule = S["Rule"];
export type Suggestion = S["SuggestionOut"];
export type AuditEvent = S["AuditEventOut"];
export type LLMCall = S["LLMCallOut"];
export type TransactionEvent = S["TransactionEvent"];
export type MatchResult = S["MatchResult"];
export type IngestedFile = S["IngestedFileOut"];
export type Backtest = S["BacktestOut"];
export type ParseOut = S["ParseOut"];
export type ExecuteOut = S["ExecuteOut"];
export type AskOut = S["AskOut"];
export type TenantSettings = S["TenantSettingsOut"];
export type AgentHealth = S["api__routers__agent__HealthOut"];
export type Evidence = S["ExceptionEvidenceOut"];
export type DiffOut = S["DiffOut"];

type Q<T> = Omit<UseQueryOptions<T, Error>, "queryKey" | "queryFn">;

const PAGE = 2000;

/** Walk a cursor-paginated endpoint to the end. Demo scale: a few pages. */
async function allPages<T>(
  fetchPage: (cursor: string | null) => Promise<{ items: T[]; next_cursor?: string | null } | undefined>,
): Promise<T[]> {
  const out: T[] = [];
  let cursor: string | null = null;
  for (let i = 0; i < 40; i++) {
    const page = await fetchPage(cursor);
    if (!page) break;
    out.push(...page.items);
    if (!page.next_cursor) break;
    cursor = page.next_cursor;
  }
  return out;
}

function need<T>(res: { data?: T; error?: unknown }, what: string): T {
  if (res.error || res.data === undefined) {
    const detail =
      typeof res.error === "object" && res.error && "detail" in res.error
        ? String((res.error as { detail?: unknown }).detail)
        : "";
    throw new Error(detail ? `${what}: ${detail}` : `could not load ${what}`);
  }
  return res.data;
}

/* ---------- run ---------- */

export function useCurrentRun() {
  const { summary, loading, error, refresh } = useRun();
  return { run: summary?.run ?? null, summary, runId: summary?.run.run_id, loading, error, refresh };
}

export function useRunSummary(runId: string | undefined, opts?: Q<RunSummary>) {
  return useQuery({
    queryKey: ["a1", "run", runId, "summary"],
    enabled: !!runId,
    queryFn: async () =>
      need(await apiClient.GET("/api/v1/runs/{run_id}/summary", { params: { path: { run_id: runId! } } }), "summary"),
    ...opts,
  });
}

export function useRuns(kind: "all" | "original" | "replay" = "all", limit = 20) {
  return useQuery({
    queryKey: ["a1", "runs", kind, limit],
    queryFn: async () =>
      need(await apiClient.GET("/api/v1/runs", { params: { query: { kind, limit } } }), "runs").items,
  });
}

export function useRunDiff(fromRunId: string | undefined, toRunId: string | undefined) {
  return useQuery({
    queryKey: ["a1", "diff", fromRunId, toRunId],
    enabled: !!fromRunId && !!toRunId && fromRunId !== toRunId,
    queryFn: async () =>
      need(
        await apiClient.GET("/api/v1/runs/{from_run_id}/diff/{to_run_id}", {
          params: { path: { from_run_id: fromRunId!, to_run_id: toRunId! } },
        }),
        "diff",
      ),
  });
}

/* ---------- exceptions & clusters ---------- */

export function useExceptions(runId: string | undefined, opts?: Q<Exception[]>) {
  return useQuery({
    queryKey: ["a1", "run", runId, "exceptions"],
    enabled: !!runId,
    queryFn: () =>
      allPages<Exception>(async (cursor) =>
        need(
          await apiClient.GET("/api/v1/exceptions", { params: { query: { run_id: runId, limit: PAGE, cursor } } }),
          "exceptions",
        ),
      ),
    ...opts,
  });
}

export function useException(id: string | null) {
  return useQuery({
    queryKey: ["a1", "exception", id],
    enabled: !!id,
    queryFn: async () =>
      need(
        await apiClient.GET("/api/v1/exceptions/{exception_id}", { params: { path: { exception_id: id! } } }),
        "exception",
      ),
  });
}

export function useEvidence(id: string | null) {
  return useQuery({
    queryKey: ["a1", "exception", id, "evidence"],
    enabled: !!id,
    queryFn: async () =>
      need(
        await apiClient.GET("/api/v1/exceptions/{exception_id}/evidence", {
          params: { path: { exception_id: id! } },
        }),
        "evidence",
      ),
  });
}

export function useClusters(runId: string | undefined) {
  return useQuery({
    queryKey: ["a1", "run", runId, "clusters"],
    enabled: !!runId,
    queryFn: () =>
      allPages<Cluster>(async (cursor) =>
        need(
          await apiClient.GET("/api/v1/clusters", { params: { query: { run_id: runId, limit: PAGE, cursor } } }),
          "clusters",
        ),
      ),
  });
}

/* ---------- cash / eval ---------- */

export function useCashBridge(runId: string | undefined) {
  return useQuery({
    queryKey: ["a1", "run", runId, "cash"],
    enabled: !!runId,
    queryFn: async () =>
      need(await apiClient.GET("/api/v1/cash/bridge", { params: { query: { run_id: runId! } } }), "cash bridge"),
  });
}

export function useEval(runId: string | undefined) {
  return useQuery({
    queryKey: ["a1", "run", runId, "eval"],
    enabled: !!runId,
    retry: 0,
    queryFn: async () => {
      const res = await apiClient.GET("/api/v1/eval/{run_id}", { params: { path: { run_id: runId! } } });
      if (res.error) return null;
      return res.data ?? null;
    },
  });
}

export function useCoverageCurve(runId: string | undefined) {
  return useQuery({
    queryKey: ["a1", "run", runId, "coverage"],
    enabled: !!runId,
    retry: 0,
    queryFn: async () => {
      const res = await apiClient.GET("/api/v1/eval/{run_id}/coverage-curve", {
        params: { path: { run_id: runId! } },
      });
      return res.data ?? null;
    },
  });
}

export function useConfusion(runId: string | undefined) {
  return useQuery({
    queryKey: ["a1", "run", runId, "confusion"],
    enabled: !!runId,
    retry: 0,
    queryFn: async () => {
      const res = await apiClient.GET("/api/v1/eval/{run_id}/confusion", { params: { path: { run_id: runId! } } });
      return res.data ?? null;
    },
  });
}

/* ---------- rules ---------- */

export function useRules(status?: Rule["status"]) {
  return useQuery({
    queryKey: ["a1", "rules", status ?? "all"],
    queryFn: async () =>
      need(await apiClient.GET("/api/v1/rules", { params: { query: { status: status ?? null } } }), "rules"),
  });
}

export function useRuleSets() {
  return useQuery({
    queryKey: ["a1", "rule-sets"],
    queryFn: async () => need(await apiClient.GET("/api/v1/rules/sets", {}), "rule sets"),
  });
}

export function useRuleVersions(ruleId: string | null) {
  return useQuery({
    queryKey: ["a1", "rule", ruleId, "versions"],
    enabled: !!ruleId,
    queryFn: async () =>
      need(
        await apiClient.GET("/api/v1/rules/{rule_id}/versions", { params: { path: { rule_id: ruleId! } } }),
        "versions",
      ),
  });
}

export function useSuggestions() {
  return useQuery({
    queryKey: ["a1", "rules", "suggestions"],
    queryFn: async () => need(await apiClient.GET("/api/v1/rules/suggestions", {}), "suggestions"),
  });
}

/* ---------- records ---------- */

export function useEventsCount(runId: string | undefined) {
  return useQuery({
    queryKey: ["a1", "run", runId, "events-count"],
    enabled: !!runId,
    queryFn: async () =>
      need(await apiClient.GET("/api/v1/events/count", { params: { query: { run_id: runId } } }), "event count"),
  });
}

export function useEvents(runId: string | undefined, filter: { source?: TransactionEvent["source"] } = {}) {
  return useQuery({
    queryKey: ["a1", "run", runId, "events", filter],
    enabled: !!runId,
    queryFn: () =>
      allPages<TransactionEvent>(async (cursor) =>
        need(
          await apiClient.GET("/api/v1/events", {
            params: { query: { run_id: runId, source: filter.source ?? null, limit: PAGE, cursor } },
          }),
          "events",
        ),
      ),
  });
}

export function useMatches(runId: string | undefined) {
  return useQuery({
    queryKey: ["a1", "run", runId, "matches"],
    enabled: !!runId,
    queryFn: () =>
      allPages<MatchResult>(async (cursor) =>
        need(
          await apiClient.GET("/api/v1/matches", { params: { query: { run_id: runId, limit: PAGE, cursor } } }),
          "matches",
        ),
      ),
  });
}

export function useRawEvent(eventId: string | null) {
  return useQuery({
    queryKey: ["a1", "event", eventId, "raw"],
    enabled: !!eventId,
    queryFn: async () =>
      need(await apiClient.GET("/api/v1/events/{event_id}/raw", { params: { path: { event_id: eventId! } } }), "raw"),
  });
}

/* ---------- audit / llm / agent ---------- */

export function useAudit(params: { subject_id?: string; subject_type?: string; limit?: number } = {}, refetchMs?: number) {
  return useQuery({
    queryKey: ["a1", "audit", params],
    refetchInterval: refetchMs,
    queryFn: async () =>
      need(
        await apiClient.GET("/api/v1/audit", {
          params: { query: { limit: params.limit ?? 50, subject_id: params.subject_id, subject_type: params.subject_type } },
        }),
        "audit",
      ).items,
  });
}

export function useAuditAll(limit = 200) {
  return useQuery({
    queryKey: ["a1", "audit", "all", limit],
    queryFn: async () =>
      need(await apiClient.GET("/api/v1/audit", { params: { query: { limit: Math.min(limit, PAGE) } } }), "audit").items,
  });
}

export function useLlmCalls(runId: string | undefined, limit = 50) {
  return useQuery({
    queryKey: ["a1", "run", runId, "llm", limit],
    queryFn: async () =>
      need(await apiClient.GET("/api/v1/llm/calls", { params: { query: { run_id: runId, limit } } }), "llm calls").items,
  });
}

export function useNarrative(runId: string | undefined) {
  return useQuery({
    queryKey: ["a1", "run", runId, "narrative"],
    enabled: !!runId,
    retry: 0,
    queryFn: async () => {
      const res = await apiClient.GET("/api/v1/agent/narrative/{run_id}", { params: { path: { run_id: runId! } } });
      return res.data ?? null;
    },
  });
}

export function useAgentHealth() {
  return useQuery({
    queryKey: ["a1", "agent", "health"],
    staleTime: 30_000,
    queryFn: async () => need(await apiClient.GET("/api/v1/agent/health", {}), "agent health"),
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ["a1", "settings"],
    queryFn: async () => need(await apiClient.GET("/api/v1/settings", {}), "settings"),
  });
}

export function useFiles() {
  return useQuery({
    queryKey: ["a1", "files"],
    queryFn: async () => need(await apiClient.GET("/api/v1/ingest/files", {}), "files"),
  });
}

/* ---------- writes ---------- */

type Body<P extends keyof paths, M extends "post" | "patch"> = paths[P] extends {
  [K in M]: { requestBody: { content: { "application/json": infer B } } };
}
  ? B
  : never;

export const writes = {
  parse: (body: Body<"/api/v1/agent/parse", "post">) => apiClient.POST("/api/v1/agent/parse", { body }),
  execute: (body: Body<"/api/v1/agent/execute", "post">) => apiClient.POST("/api/v1/agent/execute", { body }),
  ask: (body: Body<"/api/v1/agent/ask", "post">) => apiClient.POST("/api/v1/agent/ask", { body }),
  resolve: (id: string, body: Body<"/api/v1/exceptions/{exception_id}/resolve", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/exceptions/{exception_id}/resolve", {
      params: { path: { exception_id: id }, query: { dry_run } },
      body,
    }),
  writeOff: (id: string, body: Body<"/api/v1/exceptions/{exception_id}/write-off", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/exceptions/{exception_id}/write-off", {
      params: { path: { exception_id: id }, query: { dry_run } },
      body,
    }),
  escalate: (id: string, body: Body<"/api/v1/exceptions/{exception_id}/escalate", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/exceptions/{exception_id}/escalate", {
      params: { path: { exception_id: id }, query: { dry_run } },
      body,
    }),
  snooze: (id: string, body: Body<"/api/v1/exceptions/{exception_id}/snooze", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/exceptions/{exception_id}/snooze", {
      params: { path: { exception_id: id }, query: { dry_run } },
      body,
    }),
  reclassify: (id: string, body: Body<"/api/v1/exceptions/{exception_id}/reclassify", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/exceptions/{exception_id}/reclassify", {
      params: { path: { exception_id: id }, query: { dry_run } },
      body,
    }),
  applyCluster: (clusterId: string, body: Body<"/api/v1/clusters/{cluster_id}/apply", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/clusters/{cluster_id}/apply", {
      params: { path: { cluster_id: clusterId }, query: { dry_run } },
      body,
    }),
  backtest: (ruleId: string, version: number, body: Body<"/api/v1/rules/{rule_id}/backtest", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/rules/{rule_id}/backtest", {
      params: { path: { rule_id: ruleId }, query: { version, dry_run } },
      body,
    }),
  activate: (ruleId: string, version: number, body: Body<"/api/v1/rules/{rule_id}/activate", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/rules/{rule_id}/activate", {
      params: { path: { rule_id: ruleId }, query: { version, dry_run } },
      body,
    }),
  retire: (ruleId: string, version: number, body: Body<"/api/v1/rules/{rule_id}/retire", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/rules/{rule_id}/retire", {
      params: { path: { rule_id: ruleId }, query: { version, dry_run } },
      body,
    }),
  previewRule: (body: Body<"/api/v1/rules/preview", "post">) => apiClient.POST("/api/v1/rules/preview", { body }),
  createRule: (body: Body<"/api/v1/rules", "post">, dry_run = false) =>
    apiClient.POST("/api/v1/rules", { params: { query: { dry_run } }, body }),
  acceptSuggestion: (signature: string) =>
    apiClient.POST("/api/v1/rules/suggestions/{signature}/accept", { params: { path: { signature } } }),
  dismissSuggestion: (signature: string, body: Body<"/api/v1/rules/suggestions/{signature}/dismiss", "post">) =>
    apiClient.POST("/api/v1/rules/suggestions/{signature}/dismiss", { params: { path: { signature } }, body }),
  createRun: (body: Body<"/api/v1/runs", "post">) => apiClient.POST("/api/v1/runs", { body }),
  finalizeRun: (runId: string) =>
    apiClient.POST("/api/v1/runs/{run_id}/finalize", { params: { path: { run_id: runId } } }),
  replayRun: (runId: string, body: Body<"/api/v1/runs/{run_id}/replay", "post">) =>
    apiClient.POST("/api/v1/runs/{run_id}/replay", { params: { path: { run_id: runId } }, body }),
  verifyChain: () => apiClient.GET("/api/v1/audit/verify-chain", {}),
  updateSettings: (body: Body<"/api/v1/settings", "patch">) => apiClient.PATCH("/api/v1/settings", { body }),
  sendSummary: () => apiClient.POST("/api/v1/settings/send-run-summary", {}),
};

/** Extract a readable message from an openapi-fetch error body. */
export function errorMessage(err: unknown): string {
  if (!err) return "Something went wrong";
  if (typeof err === "string") return err;
  if (err instanceof Error) return err.message;
  if (typeof err === "object") {
    const e = err as { detail?: unknown; title?: string; message?: string };
    if (typeof e.detail === "string") return e.detail;
    if (Array.isArray(e.detail)) return e.detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
    if (e.title) return e.title;
    if (e.message) return e.message;
  }
  return "Something went wrong";
}

/** After any write, drop every cached read. */
export function useInvalidateAll() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

export function useWrite<TArgs, TOut>(fn: (args: TArgs) => Promise<{ data?: TOut; error?: unknown }>) {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: async (args: TArgs) => {
      const res = await fn(args);
      if (res.error || res.data === undefined) throw new Error(errorMessage(res.error));
      return res.data;
    },
    onSuccess: () => void invalidate(),
  });
}
