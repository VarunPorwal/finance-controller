"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { RefreshCw, Download, Upload, ClipboardList, CircleCheck, TriangleAlert, Clock } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { formatPercent } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { StatCard } from "@/components/ui/stat-card";
import { ReconciliationBridge } from "@/components/reconciliation-bridge";
import { ExceptionsTable } from "@/components/exceptions-table";
import { PlaceholderPanel } from "@/components/placeholder-panel";
import { InteractiveTrendChart } from "@/components/ui/interactive-trend-chart";
import { EmailToggle } from "@/components/email-toggle";

type RunSummary = components["schemas"]["RunSummaryOut"];
interface HistoryPoint {
  label: string;
  eventCount: number;
  autoMatched: number;
}
interface HomeBundle {
  prevSummary: RunSummary | null;
  history: HistoryPoint[];
}

const HISTORY_WINDOW = 10;

const SOURCE_COLOR: Record<string, string> = {
  razorpay: "var(--primary)",
  tally: "var(--success)",
  bank: "var(--amber)",
};

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

export default function ReconcileHome() {
  const { summary, loading, error, refresh } = useRun();
  const router = useRouter();
  const runId = summary?.run.run_id;
  const [reconciling, setReconciling] = useState(false);
  const [reconcileError, setReconcileError] = useState<string | null>(null);

  async function runReconciliation() {
    setReconciling(true);
    setReconcileError(null);
    try {
      // Re-runs the current run's own already-ingested events under whatever
      // ruleset is active right now — the point being to pick up a rule
      // change without re-uploading anything. Only falls back to the demo
      // corpus when there is nothing yet to replay.
      const { error } = runId
        ? await apiClient.POST("/api/v1/runs/{run_id}/replay", {
            params: { path: { run_id: runId } },
            body: { reason: "Re-run from Reconcile" },
          })
        : await apiClient.POST("/api/v1/runs", { body: { mode: "demo", seed: 7 } });
      if (error) {
        setReconcileError("Could not start reconciliation.");
        return;
      }
      refresh();
    } catch {
      setReconcileError("Could not reach the API.");
    } finally {
      setReconciling(false);
    }
  }

  const { data: home } = useQuery({
    queryKey: queryKeys.homeHistory(runId),
    queryFn: () => fetchHomeBundle(runId!),
    enabled: !!runId,
  });
  const { data: counts } = useQuery({
    queryKey: queryKeys.eventsCount(runId),
    queryFn: async () => (await apiClient.GET("/api/v1/events/count", { params: { query: { run_id: runId! } } })).data ?? null,
    enabled: !!runId,
  });
  const { data: evalResult } = useQuery({
    queryKey: queryKeys.eval(runId),
    queryFn: async () => (await apiClient.GET("/api/v1/eval/{run_id}", { params: { path: { run_id: runId! } } })).data ?? null,
    enabled: !!runId,
  });
  const prevSummary = home?.prevSummary ?? null;
  const history = home?.history ?? [];

  if (loading) return <div className="fc-card h-40 animate-pulse" aria-hidden />;
  if (error || !summary) {
    return <PlaceholderPanel title="No run yet" note={error ?? "Start a run to see the reconciliation."} />;
  }

  const delta = (key: keyof RunSummary, curr: number) => {
    if (!prevSummary) return null;
    const prev = prevSummary[key] as number;
    if (prev === 0) return null;
    const pct = ((curr - prev) / prev) * 100;
    return { text: `${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(1)}%`, tone: pct >= 0 ? ("success" as const) : ("error" as const), sub: `vs ${prev} last run` };
  };

  const autoMatched = summary.event_count - summary.exception_count;
  const kpis = [
    { label: "Records", value: summary.event_count, icon: <ClipboardList width={14} height={14} />, iconBg: "var(--primary-tint)", iconColor: "var(--primary)", d: delta("event_count", summary.event_count) },
    { label: "Auto Matched", value: autoMatched, icon: <CircleCheck width={14} height={14} />, iconBg: "var(--success-bg)", iconColor: "var(--success)", d: delta("match_count", summary.match_count) },
    { label: "Exceptions", value: summary.exception_count, icon: <TriangleAlert width={14} height={14} />, iconBg: "var(--amber-bg)", iconColor: "var(--amber-text)", d: delta("exception_count", summary.exception_count) },
    { label: "Queue", value: summary.escalated_count + summary.monitor_count, icon: <Clock width={14} height={14} />, iconBg: "var(--neutral-bg)", iconColor: "var(--text-body)", d: delta("escalated_count", summary.escalated_count) },
  ];

  const sources = counts
    ? Object.entries(counts.by_source).map(([label, count]) => ({ label, count, color: SOURCE_COLOR[label] ?? "var(--text-muted)" }))
    : [];
  const totalSourceCount = sources.reduce((s, x) => s + x.count, 0) || 1;

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div className="text-2xl font-semibold tracking-[-0.025em]">Reconciliation</div>
        <div className="flex items-center gap-2.5">
          <EmailToggle />
          <button type="button" className="flex items-center gap-1.5 rounded-lg border border-border px-3.5 py-2 text-[12.5px] font-medium text-text-heading">
            <Download width={15} height={15} />
            Export
          </button>
          <button
            type="button"
            onClick={() => router.push("/sources")}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3.5 py-2 text-[12.5px] font-medium text-text-heading"
          >
            <Upload width={15} height={15} />
            Ingest
          </button>
          <button
            type="button"
            disabled={reconciling}
            onClick={runReconciliation}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[12.5px] font-semibold text-white disabled:opacity-50"
          >
            <RefreshCw width={15} height={15} />
            {reconciling ? "Reconciling…" : "Run reconciliation"}
          </button>
        </div>
      </div>
      {reconcileError && <p className="mb-3 text-xs text-amber-text">{reconcileError}</p>}

      <div className="mb-5 grid grid-cols-4 gap-5">
        {kpis.map((k) => (
          <StatCard
            key={k.label}
            label={k.label}
            value={k.value.toLocaleString("en-IN")}
            icon={k.icon}
            iconBg={k.iconBg}
            iconColor={k.iconColor}
            delta={k.d?.text}
            deltaTone={k.d?.tone}
            sub={k.d?.sub ?? "no prior run to compare"}
          />
        ))}
      </div>

      <div className="mb-5 grid grid-cols-[1.65fr_1fr] gap-5">
        <div className="flex flex-col gap-5">
          <div className="fc-card">
            <div className="flex items-center justify-between px-[22px] pt-4">
              <div className="text-sm font-semibold">Records reconciled</div>
              <span className="text-[11.5px] text-text-muted">
                last {history.length} run{history.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="px-[22px] pt-3.5 pb-5">
              {history.length > 0 ? (
                <InteractiveTrendChart
                  points={history.map((h) => ({ label: h.label, value: h.eventCount }))}
                  color="var(--primary)"
                />
              ) : (
                <div className="rounded-[10px] border border-dashed border-border p-6 text-center text-[13px] text-text-muted">
                  No completed runs yet — this fills in after your first run.
                </div>
              )}
            </div>
          </div>

          {runId && (
            <ReconciliationBridge runId={runId} onHoverSegment={() => {}} onSelectGap={() => {}} />
          )}

          <div className="fc-card">
            <div className="px-[22px] pt-4 text-sm font-semibold">Sources</div>
            <div className="px-[22px] pt-3.5 pb-5">
              <div className="mb-3 flex gap-7">
                {sources.map((s) => (
                  <div key={s.label} className="fc-numeric flex items-center gap-1.5 text-base font-semibold">
                    <span className="h-[9px] w-[9px] rounded-[2px]" style={{ background: s.color }} />
                    {s.count}
                    <span className="text-[11.5px] font-medium text-text-muted" style={{ fontFamily: "var(--font-inter)" }}>
                      {s.label}
                    </span>
                  </div>
                ))}
              </div>
              <div className="flex h-2 overflow-hidden rounded-full">
                {sources.map((s) => (
                  <div key={s.label} style={{ background: s.color, flex: s.count / totalSourceCount }} />
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-5">
          <div className="fc-card">
            <div className="px-5 pt-4 text-sm font-semibold">Auto-Resolutions</div>
            <div className="px-5 pt-3.5 pb-5">
              <div className="fc-numeric text-[22px] font-semibold">{autoMatched}</div>
              {history.length > 0 ? (
                <div className="mt-3">
                  <InteractiveTrendChart
                    points={history.map((h) => ({ label: h.label, value: h.autoMatched }))}
                    color="var(--success)"
                    height={110}
                  />
                </div>
              ) : (
                <div className="mt-4 rounded-[10px] border border-dashed border-border p-4 text-center text-xs text-text-muted">
                  No completed runs yet to chart.
                </div>
              )}
            </div>
          </div>

          <div className="fc-card">
            <div className="px-5 pt-4 text-sm font-semibold">System Health</div>
            <div className="px-5 pt-3.5 pb-5">
              {evalResult ? (
                <>
                  <div className="fc-numeric text-center text-[22px] font-semibold">
                    {formatPercent(Number(evalResult.recall_pct ?? 0) / 100)}
                  </div>
                  <div className="mt-1.5 text-center text-xs text-text-muted">
                    Recall · {evalResult.false_auto_resolutions} false auto-resolutions
                  </div>
                </>
              ) : (
                <div className="rounded-[10px] border border-dashed border-border p-4 text-center text-xs text-text-muted">
                  No evaluation for this run — ground truth only exists for the demo corpus.
                </div>
              )}
              <div className="mt-3 text-center">
                <Link href="/eval" className="rounded-[7px] border border-border px-3.5 py-1.5 text-xs font-medium text-text-heading">
                  Show details
                </Link>
              </div>
            </div>
          </div>

          <Link
            href="/ask"
            className="block rounded-[var(--radius-card)] border border-model-border p-4 text-center"
            style={{ background: "var(--model-bg)" }}
          >
            <div className="mb-2.5 flex items-center justify-center gap-2">
              <span className="text-sm font-semibold text-model-text">Ask Controller</span>
              <span className="rounded-[6px] bg-model-pill-bg px-[7px] py-[2px] text-[10px] font-semibold text-model-text">
                Model output
              </span>
            </div>
            <div className="mx-auto mb-2.5 h-12 w-12 rounded-full" style={{ background: "radial-gradient(circle at 35% 30%, #C4B5FD, #7C3AED)" }} />
            <div className="rounded-[9px] border border-border bg-white px-3 py-2 text-left text-[12.5px] text-text-muted">
              Ask about your reconciliation…
            </div>
          </Link>
        </div>
      </div>

      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold">Decisions requiring attention</div>
        <Link href="/exceptions" className="text-[12.5px] font-medium text-primary">
          View all →
        </Link>
      </div>
      {runId && (
        <ExceptionsTable runId={runId} limit={5} linkTo={(id) => `/exceptions/${id}`} />
      )}
    </div>
  );
}
