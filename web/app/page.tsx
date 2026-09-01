"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { RefreshCw, Download, Upload } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { fetchHomeBundle } from "@/lib/page-data";
import { formatPercent } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { ReconciliationBridge } from "@/components/reconciliation-bridge";
import { BooksVsBank } from "@/components/books-vs-bank";
import { ExceptionsTable } from "@/components/exceptions-table";
import { PlaceholderPanel } from "@/components/placeholder-panel";
import { InteractiveTrendChart } from "@/components/ui/interactive-trend-chart";
import { EmailToggle } from "@/components/email-toggle";

type RunSummary = components["schemas"]["RunSummaryOut"];
const SOURCE_COLOR: Record<string, string> = {
  razorpay: "var(--primary)",
  tally: "var(--success)",
  bank: "var(--amber)",
};

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
            // `seed` is required by ReplayRequest and matches the demo seed the
            // original run used, so a replay stays byte-identical to it
            // (CLAUDE.md hard rule 9) rather than reshuffling ids.
            body: { reason: "Re-run from Reconcile", seed: 7 },
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
  const history = home?.history ?? [];

  if (loading) return <div className="fc-card h-40 animate-pulse" aria-hidden />;
  if (error || !summary) {
    return <PlaceholderPanel title="No run yet" note={error ?? "Start a run to see the reconciliation."} />;
  }


  const autoMatched = summary.event_count - summary.exception_count;
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
            title="Replays this run's stored events under the current rule book. Parser and ingest changes need a re-ingest, not a replay."
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[12.5px] font-semibold text-white disabled:opacity-50"
          >
            <RefreshCw width={15} height={15} />
            {reconciling ? "Reconciling…" : "Run reconciliation"}
          </button>
        </div>
      </div>
      {/*
        The trap this line exists to close: "Run reconciliation" replays the
        run's *stored events* under the current rule book, which is the whole
        point when a rule changed — and silently the wrong tool when the
        change was in ingest. A new narration pattern or reference field only
        exists on rows the new parser wrote, so a replay runs the new engine
        over the old parser's output and the improvement appears not to work.
      */}
      <p className="mb-3 text-[11.5px] text-text-muted">
        Re-runs this run&rsquo;s stored records under the current rule book.
        Changed how a statement is <em>parsed</em>?{" "}
        <button
          type="button"
          onClick={() => router.push("/sources")}
          className="text-primary underline underline-offset-2"
        >
          Re-ingest the files
        </button>{" "}
        instead — a replay reuses rows the previous parser wrote.
      </p>
      {reconcileError && <p className="mb-3 text-xs text-amber-text">{reconcileError}</p>}

      {runId && <BooksVsBank runId={runId} />}

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
