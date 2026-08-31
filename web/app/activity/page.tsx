"use client";

import { useEffect, useState } from "react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { StatCard } from "@/components/ui/stat-card";
import { RunProgressStrip } from "@/components/run-progress-strip";
import { formatPaise, humanizeSnakeCase } from "@/lib/format";
import { cacheGet, cacheSet } from "@/lib/page-cache";

type AuditEvent = components["schemas"]["AuditEventOut"];
type Rule = components["schemas"]["Rule"];
type LLMCall = components["schemas"]["LLMCallOut"];
type RunOut = components["schemas"]["RunOut"];
type ReplayDiff = components["schemas"]["ReplayDiff"];
type DecisionDiff = components["schemas"]["DecisionDiff"];
type NarrativeOut = components["schemas"]["NarrativeOutModel"];

interface ActivityBundle {
  runsToday: number;
  activeRuleCount: number;
  avgRuntimeMs: number | null;
  log: AuditEvent[];
  llmCalls: LLMCall[];
  runs: RunOut[];
  narrative: NarrativeOut | null;
}

const ACTION_COLOR: Record<string, string> = {
  "run.create": "var(--success)",
  "run.finalize": "var(--success)",
  "exception.resolve": "var(--success)",
  "exception.escalate": "var(--amber)",
  "rule.activate": "var(--primary)",
  "rule.backtest": "var(--primary)",
};

export default function ControllerActivityPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const cacheKey = `activity:${runId ?? "none"}`;
  const cached = cacheGet<ActivityBundle>(cacheKey);
  const [runsToday, setRunsToday] = useState<number | null>(cached?.runsToday ?? null);
  const [activeRuleCount, setActiveRuleCount] = useState<number | null>(cached?.activeRuleCount ?? null);
  const [avgRuntimeMs, setAvgRuntimeMs] = useState<number | null>(cached?.avgRuntimeMs ?? null);
  const [log, setLog] = useState<AuditEvent[]>(cached?.log ?? []);
  const [llmCalls, setLlmCalls] = useState<LLMCall[]>(cached?.llmCalls ?? []);
  const [runs, setRuns] = useState<RunOut[]>(cached?.runs ?? []);
  const [narrative, setNarrative] = useState<NarrativeOut | null>(cached?.narrative ?? null);
  const [fromRunId, setFromRunId] = useState(cached?.runs?.[1]?.run_id ?? "");
  const [toRunId, setToRunId] = useState(cached?.runs?.[0]?.run_id ?? "");
  const [diff, setDiff] = useState<ReplayDiff | null>(null);
  const [diffing, setDiffing] = useState(false);
  const [replaying, setReplaying] = useState(false);

  function applyBundle(b: ActivityBundle) {
    setRunsToday(b.runsToday);
    setActiveRuleCount(b.activeRuleCount);
    setAvgRuntimeMs(b.avgRuntimeMs);
    setLog(b.log);
    setLlmCalls(b.llmCalls);
    setRuns(b.runs);
    setNarrative(b.narrative);
  }

  useEffect(() => {
    let cancelled = false;
    const key = `activity:${runId ?? "none"}`;
    const seeded = cacheGet<ActivityBundle>(key);
    if (seeded) applyBundle(seeded);
    async function load() {
      const [runsRes, rulesRes, auditRes, llmRes, narrativeRes] = await Promise.all([
        apiClient.GET("/api/v1/runs", { params: { query: { status: "complete", limit: 50 } } }),
        apiClient.GET("/api/v1/rules", { params: { query: { status: "active" } } }),
        apiClient.GET("/api/v1/audit", { params: { query: { run_id: runId, limit: 50 } } }),
        apiClient.GET("/api/v1/llm/calls", { params: { query: { run_id: runId, limit: 20 } } }),
        runId
          ? apiClient.GET("/api/v1/agent/narrative/{run_id}", { params: { path: { run_id: runId } } })
          : Promise.resolve({ data: undefined }),
      ]);
      if (cancelled) return;
      const runsList = runsRes.data?.items ?? [];
      const today = new Date().toDateString();
      const withRuntime = runsList.filter((r) => r.runtime_ms != null);
      const activeRules: Rule[] = rulesRes.data ?? [];
      const bundle: ActivityBundle = {
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
      cacheSet(key, bundle);
      applyBundle(bundle);
      if (runsList.length >= 2 && !fromRunId && !toRunId) {
        setFromRunId(runsList[1].run_id);
        setToRunId(runsList[0].run_id);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  async function runDiff() {
    if (!fromRunId || !toRunId) return;
    setDiffing(true);
    const { data } = await apiClient.GET("/api/v1/runs/{from_run_id}/diff/{to_run_id}", {
      params: { path: { from_run_id: fromRunId, to_run_id: toRunId } },
    });
    setDiffing(false);
    setDiff(data?.diff ?? null);
  }

  async function replayCurrentRun() {
    if (!runId) return;
    const reason = window.prompt("Reason to replay this run under the active ruleset:");
    if (!reason?.trim()) return;
    setReplaying(true);
    const { data } = await apiClient.POST("/api/v1/runs/{run_id}/replay", {
      params: { path: { run_id: runId } },
      body: { reason: reason.trim(), seed: 8 },
    });
    setReplaying(false);
    if (!data) return;
    setFromRunId(runId);
    setToRunId(data.new_run_id);
    setDiff(data.diff);
  }

  function diffLine(d: DecisionDiff) {
    const before = d.before ? `${humanizeSnakeCase(d.before.category)} (${formatPaise(d.before.residual_paise)})` : "—";
    const after = d.after ? `${humanizeSnakeCase(d.after.category)} (${formatPaise(d.after.residual_paise)})` : "—";
    return { before, after };
  }

  return (
    <div>
      <div className="mb-4.5">
        <div className="text-2xl font-semibold tracking-[-0.025em]">Controller Activity</div>
        <div className="mt-[3px] text-[13px] text-text-muted">
          What the agent evaluated, matched, and escalated
        </div>
      </div>

      <div className="mb-5 grid grid-cols-3 gap-5">
        <StatCard label="Runs today" value={runsToday ?? "—"} valueSize="22" />
        <StatCard label="Rules evaluated" value={activeRuleCount ?? "—"} valueSize="22" />
        <StatCard
          label="Avg run time"
          value={avgRuntimeMs != null ? `${(avgRuntimeMs / 1000).toFixed(1)}s` : "—"}
          valueSize="22"
        />
      </div>

      <RunProgressStrip runId={runId} />

      {narrative && (
        <div className="fc-card mb-5 px-[22px] py-4">
          <div className="mb-1.5 flex items-center justify-between">
            <div className="text-sm font-semibold">Run narrative</div>
            <span className="text-[11px] text-text-muted">
              {narrative.model_used}
              {narrative.cached ? " · cached" : ""}
            </span>
          </div>
          <p className="text-[13px] text-text-body">{narrative.narrative}</p>
        </div>
      )}

      <div className="fc-card mb-5 overflow-hidden">
        <div className="flex items-center justify-between border-b border-border px-[22px] py-3.5">
          <div className="text-sm font-semibold">Replay &amp; diff</div>
          <button
            type="button"
            disabled={!runId || replaying}
            onClick={replayCurrentRun}
            className="rounded-[7px] border border-border px-3 py-1.5 text-xs font-medium disabled:opacity-50"
          >
            {replaying ? "Replaying…" : "Replay current run under active rules"}
          </button>
        </div>
        <div className="flex items-center gap-2.5 px-[22px] py-3.5">
          <select
            value={fromRunId}
            onChange={(e) => setFromRunId(e.target.value)}
            className="rounded-md border border-border bg-background p-1.5 text-xs"
          >
            <option value="">from run…</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                #{r.run_id.slice(-6)} · {new Date(r.started_at).toLocaleString("en-IN")}
              </option>
            ))}
          </select>
          <span className="text-xs text-text-muted">→</span>
          <select
            value={toRunId}
            onChange={(e) => setToRunId(e.target.value)}
            className="rounded-md border border-border bg-background p-1.5 text-xs"
          >
            <option value="">to run…</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                #{r.run_id.slice(-6)} · {new Date(r.started_at).toLocaleString("en-IN")}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!fromRunId || !toRunId || diffing}
            onClick={runDiff}
            className="rounded-[7px] bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
          >
            {diffing ? "Diffing…" : "Diff"}
          </button>
        </div>
        {diff && (
          <div className="border-t border-[color:var(--neutral-bg)]">
            {(["changed", "added", "removed"] as const).map((bucket) => (
              <div key={bucket}>
                <div className="bg-neutral-bg px-[22px] py-2 text-[11px] font-semibold tracking-[0.03em] text-text-muted uppercase">
                  {bucket} — {diff[bucket].length}
                </div>
                {diff[bucket].length === 0 && (
                  <div className="px-[22px] py-2.5 text-xs text-text-muted">None</div>
                )}
                {diff[bucket].map((d, i) => {
                  const { before, after } = diffLine(d);
                  return (
                    <div key={i} className="border-b border-[color:var(--neutral-bg)] px-[22px] py-3 text-[13px] last:border-0">
                      <div className="flex items-center gap-2.5">
                        <span className="text-text-muted">{before}</span>
                        <span className="text-text-faint">→</span>
                        <span>{after}</span>
                      </div>
                      <div className="mt-0.5 text-[11.5px] text-text-muted">{d.why}</div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="fc-card mb-5 overflow-hidden">
        <div className="border-b border-border px-[22px] py-3.5 text-sm font-semibold">Today</div>
        {log.length === 0 && <div className="p-5 text-center text-sm text-text-muted">Nothing logged yet.</div>}
        {log.map((e) => (
          <div key={e.seq} className="flex items-start gap-3.5 border-b border-[color:var(--neutral-bg)] px-[22px] py-3.5 last:border-0">
            <span
              className="mt-1.5 h-[7px] w-[7px] flex-none rounded-full"
              style={{ background: ACTION_COLOR[e.action] ?? "var(--text-muted)" }}
            />
            <div className="fc-numeric w-14 flex-none text-xs text-text-muted">
              {new Date(e.created_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
            </div>
            <div className="text-[13px]">
              {e.action} — {e.subject_type} {e.subject_id}
            </div>
          </div>
        ))}
      </div>

      <div className="fc-card overflow-hidden">
        <div className="border-b border-border px-[22px] py-3.5 text-sm font-semibold">LLM calls, this run</div>
        {llmCalls.length === 0 && <div className="p-5 text-center text-sm text-text-muted">No model calls recorded for this run.</div>}
        {llmCalls.map((c) => (
          <div key={c.call_id} className="flex items-center justify-between border-b border-[color:var(--neutral-bg)] px-[22px] py-3 text-[13px] last:border-0">
            <div>
              <span className="font-medium">{c.purpose}</span>
              <span className="ml-2 text-xs text-text-muted">{c.model} · {c.tier}</span>
            </div>
            <div className="fc-numeric flex items-center gap-3 text-xs text-text-muted">
              {c.cached && <span>cached</span>}
              <span>{(c.input_tokens ?? 0) + (c.output_tokens ?? 0)} tok</span>
              <span>{c.latency_ms != null ? `${c.latency_ms}ms` : "—"}</span>
              <span className={c.outcome === "ok" ? "text-success" : "text-amber-text"}>{c.outcome}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
