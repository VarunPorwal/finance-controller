"use client";

import { useEffect, useState } from "react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { StatCard } from "@/components/ui/stat-card";

type AuditEvent = components["schemas"]["AuditEventOut"];
type Rule = components["schemas"]["Rule"];
type LLMCall = components["schemas"]["LLMCallOut"];

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
  const [runsToday, setRunsToday] = useState<number | null>(null);
  const [activeRuleCount, setActiveRuleCount] = useState<number | null>(null);
  const [avgRuntimeMs, setAvgRuntimeMs] = useState<number | null>(null);
  const [log, setLog] = useState<AuditEvent[]>([]);
  const [llmCalls, setLlmCalls] = useState<LLMCall[]>([]);
  const runId = summary?.run.run_id;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [runsRes, rulesRes, auditRes, llmRes] = await Promise.all([
        apiClient.GET("/api/v1/runs", { params: { query: { status: "complete", limit: 50 } } }),
        apiClient.GET("/api/v1/rules", { params: { query: { status: "active" } } }),
        apiClient.GET("/api/v1/audit", { params: { query: { run_id: runId, limit: 50 } } }),
        apiClient.GET("/api/v1/llm/calls", { params: { query: { run_id: runId, limit: 20 } } }),
      ]);
      if (cancelled) return;
      const runs = runsRes.data?.items ?? [];
      const today = new Date().toDateString();
      setRunsToday(runs.filter((r) => new Date(r.started_at).toDateString() === today).length);
      const withRuntime = runs.filter((r) => r.runtime_ms != null);
      setAvgRuntimeMs(
        withRuntime.length
          ? withRuntime.reduce((s, r) => s + (r.runtime_ms ?? 0), 0) / withRuntime.length
          : null,
      );
      const activeRules: Rule[] = rulesRes.data ?? [];
      setActiveRuleCount(new Set(activeRules.map((r) => r.rule_id)).size);
      setLog(auditRes.data?.items ?? []);
      setLlmCalls(llmRes.data?.items ?? []);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

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
