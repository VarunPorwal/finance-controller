"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Play, RefreshCw, Upload } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient } from "@/lib/client";
import { formatCount, formatDurationMs, shortId } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { ReconciliationBridge } from "@/components/reconciliation-bridge";
import { BooksVsBank } from "@/components/books-vs-bank";
import { ExceptionsTable } from "@/components/exceptions-table";
import { RunProgressStrip } from "@/components/run-progress-strip";
import { ReplayDiff } from "@/components/replay-diff";
import { MetaRow, PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Pill } from "@/components/ui/pill";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { SourceDot, orderSources, sourceMeta } from "@/components/ui/source-glyph";

export default function ReconcilePage() {
  const { summary, loading, error, refresh } = useRun();
  const router = useRouter();
  const runId = summary?.run.run_id;
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<string[] | null>(null);
  const [gapIds, setGapIds] = useState<string[] | null>(null);

  async function runReconciliation() {
    setBusy(true);
    setActionError(null);
    try {
      const { error: e } = runId
        ? await apiClient.POST("/api/v1/runs/{run_id}/replay", {
            params: { path: { run_id: runId } },
            body: { reason: "Re-run from Reconcile", seed: 7 },
          })
        : await apiClient.POST("/api/v1/runs", { body: { mode: "demo", seed: 7 } });
      if (e) {
        setActionError("Could not start reconciliation.");
        return;
      }
      refresh();
    } catch {
      setActionError("Could not reach the API.");
    } finally {
      setBusy(false);
    }
  }

  const { data: counts } = useQuery({
    queryKey: queryKeys.eventsCount(runId),
    queryFn: async () => (await apiClient.GET("/api/v1/events/count", { params: { query: { run_id: runId! } } })).data ?? null,
    enabled: !!runId,
  });

  if (loading) return <Skeleton className="h-[420px]" />;
  if (error || !summary || !runId) {
    return (
      <div>
        <PageHeader title="Reconcile" sub="Gross to bank, line by line" />
        <EmptyState
          title="Nothing to reconcile yet"
          note="Run the demo corpus or ingest files first."
          action={
            <div className="flex gap-2">
              <Button variant="primary" icon={<Play width={14} height={14} />} disabled={busy} onClick={runReconciliation}>
                {busy ? "Running…" : "Run the demo corpus"}
              </Button>
              <Button icon={<Upload width={14} height={14} />} onClick={() => router.push("/ingest")}>
                Ingest files
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  const sources = counts ? orderSources(counts.by_source) : [];
  const sourceTotal = sources.reduce((s, x) => s + x.count, 0) || 1;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Reconcile"
        sub={
          <MetaRow
            items={[
              <span key="run" className="num">
                Run {shortId(runId)}
              </span>,
              <span key="records" className="num">
                {formatCount(summary.event_count)} records{summary.run.runtime_ms != null && ` in ${formatDurationMs(summary.run.runtime_ms)}`}
              </span>,
              <span key="note">
                Replay uses the stored records. If parsing changed,{" "}
                <button type="button" onClick={() => router.push("/ingest")} className="text-ink underline underline-offset-2 decoration-line-strong hover:decoration-ink">
                  re-ingest the files
                </button>{" "}
                instead.
              </span>,
            ]}
          />
        }
        actions={
          <>
            <Button icon={<Upload width={14} height={14} />} onClick={() => router.push("/ingest")}>
              Re-ingest
            </Button>
            <Button variant="primary" icon={<RefreshCw width={14} height={14} />} disabled={busy} onClick={runReconciliation}>
              {busy ? "Reconciling…" : "Run reconciliation"}
            </Button>
          </>
        }
      />
      {actionError && <p className="-mt-3 text-[12px] text-warn">{actionError}</p>}

      <RunProgressStrip runId={runId} />

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.6fr_1fr]">
        <ReconciliationBridge runId={runId} onHoverSegment={setHighlight} onSelectGap={setGapIds} />
        <Panel title="Sources" sub="Rows in this run, by origin. A match only proves money moved if the bank is one of its legs.">
          {sources.length === 0 ? (
            <Skeleton className="h-12" />
          ) : (
            <>
              <div className="flex h-2 overflow-hidden rounded-full bg-surface-3">
                {sources.map((s) => (
                  <div key={s.label} style={{ background: sourceMeta(s.label).color, flex: s.count / sourceTotal }} />
                ))}
              </div>
              <ul className="mt-3 flex flex-col">
                {sources.map((s) => (
                  <li key={s.label} className="flex items-center justify-between border-b border-line py-2 text-[12.5px] last:border-0">
                    <span className="flex items-center gap-2 text-ink-2">
                      <SourceDot source={s.label} />
                      {sourceMeta(s.label).label}
                    </span>
                    <span className="num text-[15px] text-ink">{formatCount(s.count)}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-3 grid grid-cols-3 gap-3 border-t border-line pt-3">
                <div>
                  <div className="label">Matches</div>
                  <div className="num mt-1 text-[15px] text-ink">{formatCount(summary.match_count)}</div>
                </div>
                <div>
                  <div className="label">Exceptions</div>
                  <div className="num mt-1 text-[15px] text-ink">{formatCount(summary.exception_count)}</div>
                </div>
                <div>
                  <div className="label">Root causes</div>
                  <div className="num mt-1 text-[15px] text-ink">{formatCount(summary.cluster_count)}</div>
                </div>
              </div>
            </>
          )}
        </Panel>
      </div>

      <div>
        <div className="mb-2.5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-[13px] font-semibold">Open exceptions</h2>
            {gapIds ? (
              <Pill tone="warn" dot>
                filtered to the gap · {gapIds.length}
              </Pill>
            ) : (
              <Pill tone="neutral">{summary.exception_count}</Pill>
            )}
            {highlight && <span className="text-[11px] text-ink-3">rows lit by the hovered bridge line</span>}
          </div>
          {gapIds && (
            <button type="button" onClick={() => setGapIds(null)} className="text-[11.5px] text-ink-3 hover:text-ink">
              Clear filter
            </button>
          )}
        </div>
        <ExceptionsTable runId={runId} highlightEventIds={highlight} onlyIds={gapIds} linkTo={(id) => `/exceptions/${id}`} />
      </div>

      <BooksVsBank runId={runId} />

      <ReplayDiff currentRunId={runId} />
    </div>
  );
}
