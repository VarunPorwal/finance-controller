"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { RefreshCw, Download, ClipboardList, CircleCheck, TriangleAlert, Clock } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { formatPercent } from "@/lib/format";
import { StatCard } from "@/components/ui/stat-card";
import { ReconciliationBridge } from "@/components/reconciliation-bridge";
import { ExceptionsTable } from "@/components/exceptions-table";
import { PlaceholderPanel } from "@/components/placeholder-panel";
import { cacheGet, cacheSet } from "@/lib/page-cache";

type RunSummary = components["schemas"]["RunSummaryOut"];
type EventCount = components["schemas"]["EventCountOut"];
type EvalResult = components["schemas"]["EvalResultOut"];
interface HomeBundle {
  prevSummary: RunSummary | null;
  counts: EventCount | null;
  evalResult: EvalResult | null;
  runHistoryDepth: number;
}

const SOURCE_COLOR: Record<string, string> = {
  razorpay: "var(--primary)",
  tally: "var(--success)",
  bank: "var(--amber)",
};

export default function ReconcileHome() {
  const { summary, loading, error } = useRun();
  const router = useRouter();
  const runId = summary?.run.run_id;
  const cacheKey = `home:${runId ?? "none"}`;
  const cached = cacheGet<HomeBundle>(cacheKey);
  const [prevSummary, setPrevSummary] = useState<RunSummary | null>(cached?.prevSummary ?? null);
  const [counts, setCounts] = useState<EventCount | null>(cached?.counts ?? null);
  const [evalResult, setEvalResult] = useState<EvalResult | null>(cached?.evalResult ?? null);
  const [runHistoryDepth, setRunHistoryDepth] = useState<number | null>(cached?.runHistoryDepth ?? null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const key = `home:${runId}`;
    const seeded = cacheGet<HomeBundle>(key);
    if (seeded) {
      setPrevSummary(seeded.prevSummary);
      setCounts(seeded.counts);
      setEvalResult(seeded.evalResult);
      setRunHistoryDepth(seeded.runHistoryDepth);
    }
    async function load() {
      const [runsRes, countRes, evalRes] = await Promise.all([
        apiClient.GET("/api/v1/runs", { params: { query: { status: "complete", limit: 2 } } }),
        apiClient.GET("/api/v1/events/count", { params: { query: { run_id: runId } } }),
        apiClient.GET("/api/v1/eval/{run_id}", { params: { path: { run_id: runId! } } }),
      ]);
      if (cancelled) return;
      const runs = runsRes.data?.items ?? [];
      let prev: RunSummary | null = null;
      if (runs.length > 1) {
        const olderRunId = runs.find((r) => r.run_id !== runId)?.run_id;
        if (olderRunId) {
          const { data } = await apiClient.GET("/api/v1/runs/{run_id}/summary", {
            params: { path: { run_id: olderRunId } },
          });
          if (cancelled) return;
          prev = data ?? null;
        }
      }
      const bundle: HomeBundle = {
        prevSummary: prev,
        counts: countRes.data ?? null,
        evalResult: evalRes.data ?? null,
        runHistoryDepth: runs.length,
      };
      cacheSet(key, bundle);
      setPrevSummary(bundle.prevSummary);
      setCounts(bundle.counts);
      setEvalResult(bundle.evalResult);
      setRunHistoryDepth(bundle.runHistoryDepth);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

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

  const hasHistory = (runHistoryDepth ?? 0) >= 7;
  const sources = counts
    ? Object.entries(counts.by_source).map(([label, count]) => ({ label, count, color: SOURCE_COLOR[label] ?? "var(--text-muted)" }))
    : [];
  const totalSourceCount = sources.reduce((s, x) => s + x.count, 0) || 1;

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div className="text-2xl font-semibold tracking-[-0.025em]">Reconciliation</div>
        <div className="flex items-center gap-2.5">
          <button type="button" className="flex items-center gap-1.5 rounded-lg border border-border px-3.5 py-2 text-[12.5px] font-medium text-text-heading">
            <Download width={15} height={15} />
            Export
          </button>
          <button
            type="button"
            onClick={() => router.push("/sources")}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[12.5px] font-semibold text-white"
          >
            <RefreshCw width={15} height={15} />
            Run reconciliation
          </button>
        </div>
      </div>

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
            <div className="px-[22px] pt-4 text-sm font-semibold">Value reconciled</div>
            <div className="px-[22px] pt-3.5 pb-5">
              {hasHistory ? (
                <div className="text-sm text-text-muted">Trend chart — {runHistoryDepth} days of history.</div>
              ) : (
                <div className="rounded-[10px] border border-dashed border-border p-6 text-center text-[13px] text-text-muted">
                  Needs 7 days of runs to chart a trend — fills in as you use it.
                  <span className="fc-numeric ml-1">({runHistoryDepth ?? 0}/7)</span>
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
              {hasHistory ? (
                <div className="mt-4 text-sm text-text-muted">7-day chart — {runHistoryDepth} days of history.</div>
              ) : (
                <div className="mt-4 rounded-[10px] border border-dashed border-border p-4 text-center text-xs text-text-muted">
                  Needs 7 days of runs to chart daily volume.
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
