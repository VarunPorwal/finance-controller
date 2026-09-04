// Central key hierarchy so every screen invalidates/prefetches the same
// keys another screen reads. Keyed by run_id first (nothing here changes
// unless a run happens - CLAUDE.md's staleTime rationale) so a completed
// run can be invalidated with one predicate: queryKey[0] === "run" ||
// queryKey[1] === runId, see lib/run-context.tsx's refresh().
export const queryKeys = {
  runDefault: ["runs", "default"] as const,
  runsList: (params: Record<string, unknown>) => ["runs", "list", params] as const,
  runSummary: (runId: string | undefined) => ["run", runId, "summary"] as const,
  runDiff: (fromRunId: string, toRunId: string) => ["run", "diff", fromRunId, toRunId] as const,

  eventsCount: (runId: string | undefined) => ["run", runId, "events-count"] as const,
  events: (runId: string | undefined, limit: number) => ["run", runId, "events", limit] as const,

  exceptions: (runId: string | undefined, params: Record<string, unknown>) =>
    ["exceptions", runId, params] as const,
  exceptionEvidence: (exceptionId: string | null) => ["exception", exceptionId, "evidence"] as const,
  clusters: (runId: string | undefined) => ["run", runId, "clusters"] as const,

  rules: (params: Record<string, unknown>) => ["rules", params] as const,
  ruleSuggestions: ["rules", "suggestions"] as const,
  ruleVersions: (ruleId: string) => ["rule", ruleId, "versions"] as const,
  ruleBacktest: (ruleId: string, version: number) => ["rule", ruleId, "backtest", version] as const,

  audit: (params: Record<string, unknown>) => ["audit", params] as const,
  auditVerifyChain: ["audit", "verify-chain"] as const,

  llmCalls: (runId: string | undefined, limit: number) => ["run", runId, "llm-calls", limit] as const,
  narrative: (runId: string | undefined) => ["run", runId, "narrative"] as const,

  // Home's KPI card only needs the bare EvalResult, so it fetches under its
  // own key rather than sharing evalBundle's - that bundle wraps EvalResult
  // in {evalResult, confusion, coverageCurve} and two shapes must never land
  // under the same cache key.
  eval: (runId: string | undefined) => ["run", runId, "eval"] as const,
  evalBundle: (runId: string | undefined) => ["run", runId, "eval-bundle"] as const,

  cashBridge: (runId: string | undefined) => ["run", runId, "cash-bridge"] as const,

  agentHealth: ["agent", "health"] as const,

  homeHistory: (runId: string | undefined) => ["run", runId, "home-history"] as const,
  sources: (runId: string | undefined) => ["run", runId, "sources"] as const,
  records: (runId: string | undefined) => ["run", runId, "records"] as const,
  activityPage: (runId: string | undefined) => ["run", runId, "activity"] as const,
  auditPage: (runId: string | undefined) => ["run", runId ?? "all", "audit-page"] as const,
};
