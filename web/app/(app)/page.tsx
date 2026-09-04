"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Play, RefreshCw, Sparkles, Upload } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient } from "@/lib/client";
import { fetchHomeBundle } from "@/lib/page-data";
import { formatCount, formatDurationMs, formatPaiseWhole, formatPercent, shortId } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { fetchCashBridge } from "@/app/(app)/cash/loader";
import { ExceptionsTable } from "@/components/exceptions-table";
import { EmailToggle } from "@/components/email-toggle";
import { MetaRow, PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Stat } from "@/components/ui/stat";
import { Panel } from "@/components/ui/panel";
import { Gauge } from "@/components/ui/gauge";
import { TrendChart } from "@/components/ui/trend-chart";
import { Sparkline } from "@/components/ui/sparkline";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { SourceDot, orderSources, sourceMeta } from "@/components/ui/source-glyph";
import { Pill } from "@/components/ui/pill";

export default function OverviewPage() {
  const { summary, loading, error, refresh } = useRun();
  const router = useRouter();
  const runId = summary?.run.run_id;
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");

  async function runReconciliation() {
    setBusy(true);
    setActionError(null);
    try {
      // Replays the current run's stored events under the active rule book;
      // falls back to the demo corpus only when there is nothing to replay.
      const { error: e } = runId
        ? await apiClient.POST("/api/v1/runs/{run_id}/replay", {
            params: { path: { run_id: runId } },
            body: { reason: "Re-run from Overview", seed: 7 },
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

  const { data: home } = useQuery({ queryKey: queryKeys.homeHistory(runId), queryFn: () => fetchHomeBundle(runId!), enabled: !!runId });
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
  const { data: bridge } = useQuery({ queryKey: queryKeys.cashBridge(runId), queryFn: () => fetchCashBridge(runId!), enabled: !!runId });

  if (loading) {
    return (
      <div className="flex flex-col gap-5">
        <Skeleton className="h-10 w-72" />
        <div className="grid grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[112px]" />
          ))}
        </div>
        <Skeleton className="h-[300px]" />
      </div>
    );
  }

  if (error || !summary) {
    return (
      <div>
        <PageHeader title="Overview" sub="The books at a glance" />
        <EmptyState
          title="No run yet"
          note="Start with the generated demo corpus to see a full reconciliation in about a second, or ingest your own Razorpay, bank and Tally files."
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
        {actionError && <p className="mt-3 text-[12px] text-warn">{actionError}</p>}
      </div>
    );
  }

  const history = home?.history ?? [];
  const prev = home?.prevSummary ?? null;
  const autoMatched = summary.event_count - summary.exception_count;
  const matchRate = summary.event_count > 0 ? autoMatched / summary.event_count : 0;
  const exceptionDelta = prev ? summary.exception_count - prev.exception_count : null;
  const sources = counts ? orderSources(counts.by_source) : [];
  const sourceTotal = sources.reduce((s, x) => s + x.count, 0) || 1;
  const gap = bridge?.unexplained_paise;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Overview"
        sub={
          <MetaRow
            className="num"
            items={[
              `Run ${shortId(summary.run.run_id)}`,
              `${formatCount(summary.event_count)} records${summary.run.runtime_ms != null ? ` in ${formatDurationMs(summary.run.runtime_ms)}` : ""}`,
              `${formatCount(summary.match_count)} matches`,
              `${formatCount(summary.cluster_count)} root causes`,
            ]}
          />
        }
        actions={
          <>
            <EmailToggle />
            <Button icon={<Upload width={14} height={14} />} onClick={() => router.push("/ingest")}>
              Ingest
            </Button>
            <Button variant="primary" icon={<RefreshCw width={14} height={14} />} disabled={busy} onClick={runReconciliation}>
              {busy ? "Reconciling…" : "Run reconciliation"}
            </Button>
          </>
        }
      />
      {actionError && <p className="-mt-3 text-[12px] text-warn">{actionError}</p>}

      <div className="stagger grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Records" numeric={summary.event_count} format={formatCount} size="28" sub="across three sources" />
        <Stat
          label="Auto-resolved"
          numeric={autoMatched}
          format={formatCount}
          size="28"
          tone="ok"
          sub={`${formatPercent(matchRate)} with evidence`}
        />
        <Stat
          label="Needs you"
          numeric={summary.escalated_count}
          format={formatCount}
          size="28"
          tone={summary.escalated_count > 0 ? "bad" : "ok"}
          delta={exceptionDelta != null ? `${exceptionDelta > 0 ? "+" : ""}${exceptionDelta}` : undefined}
          deltaTone={exceptionDelta != null && exceptionDelta > 0 ? "bad" : "ok"}
          sub={exceptionDelta != null ? "exceptions vs last run" : "decisions only you can make"}
        />
        <Stat label="Monitoring" numeric={summary.monitor_count} format={formatCount} size="28" tone="warn" sub="the system will look again" />
        <Stat
          label="Unexplained"
          value={<span className="skeleton inline-block h-7 w-32 align-middle" />}
          numeric={gap == null ? undefined : gap}
          format={(n) => formatPaiseWhole(Math.round(n))}
          size="28"
          tone={gap == null ? undefined : gap === 0 ? "ok" : "warn"}
          sub={gap === 0 ? "the bridge balances" : "gross to bank, after every rule"}
        />
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.6fr_1fr]">
        <Panel
          title="Run history"
          sub={home ? `Records reconciled over the last ${history.length} run${history.length === 1 ? "" : "s"}` : "Records reconciled, run over run"}
          actions={
            <Link href="/activity" className="text-[11.5px] text-ink-3 hover:text-ink">
              Activity →
            </Link>
          }
        >
          {!home ? (
            <Skeleton className="h-[230px]" />
          ) : history.length > 0 ? (
            <>
              <TrendChart points={history.map((h) => ({ label: h.label, value: h.eventCount }))} height={170} />
              <div className="mt-3 grid grid-cols-3 gap-4 border-t border-line pt-3">
                <div>
                  <div className="label">Auto-resolved, per run</div>
                  <Sparkline values={history.map((h) => h.autoMatched)} color="var(--ok)" height={30} className="mt-1.5" />
                </div>
                <div>
                  <div className="label">Latest run</div>
                  <div className="num mt-1.5 text-[15px] text-ink">
                    {formatCount(autoMatched)} auto, {formatCount(summary.exception_count)} open
                  </div>
                </div>
                <div>
                  <div className="label">Previous run</div>
                  <div className="num mt-1.5 text-[15px] text-ink-2">
                    {prev ? `${formatCount(prev.event_count - prev.exception_count)} auto, ${formatCount(prev.exception_count)} open` : "none yet"}
                  </div>
                </div>
              </div>
            </>
          ) : (
            <EmptyState title="No completed runs to chart yet" note="This fills in as runs accumulate." className="py-8" />
          )}
        </Panel>

        <Panel
          title="Match rate"
          sub="Share of records closed with evidence"
          actions={
            <Link href="/eval" className="text-[11.5px] text-ink-3 hover:text-ink">
              Evaluation →
            </Link>
          }
        >
          <div className="flex items-center justify-center py-1">
            <Gauge value={matchRate} readout={formatPercent(matchRate)} label="auto-resolved" tone={matchRate >= 0.9 ? "ok" : "warn"} size={190} />
          </div>
          <div className="mt-2 grid grid-cols-3 gap-3 border-t border-line pt-3">
            <div>
              <div className="label">Precision</div>
              <div className="num mt-1 text-[15px] text-ink">{evalResult?.precision_pct != null ? formatPercent(Number(evalResult.precision_pct)) : "-"}</div>
            </div>
            <div>
              <div className="label">Recall</div>
              <div className="num mt-1 text-[15px] text-ink">{evalResult?.recall_pct != null ? formatPercent(Number(evalResult.recall_pct)) : "-"}</div>
            </div>
            <div>
              <div className="label">False auto-closes</div>
              <div className={"num mt-1 text-[15px] " + (evalResult ? (evalResult.false_auto_resolutions === 0 ? "text-ok" : "text-bad") : "text-ink-3")}>
                {evalResult ? evalResult.false_auto_resolutions : "-"}
              </div>
            </div>
          </div>
          {!evalResult && <p className="mt-2 text-[11px] text-ink-3">Ground truth exists only for the demo corpus.</p>}
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.6fr_1fr]">
        <div>
          <div className="mb-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="text-[13px] font-semibold">Needs you</h2>
              <Pill tone="bad" dot>
                {summary.escalated_count}
              </Pill>
            </div>
            <Link href="/exceptions" className="flex items-center gap-1 text-[11.5px] text-ink-3 hover:text-ink">
              Open the queue <ArrowRight width={12} height={12} />
            </Link>
          </div>
          <ExceptionsTable runId={runId!} limit={6} linkTo={(id) => `/exceptions/${id}`} compact />
        </div>

        <div className="flex flex-col gap-5">
          <Panel
            tone="model"
            title={
              <span className="flex items-center gap-2">
                <Sparkles width={13} height={13} />
                Ask the books
              </span>
            }
            sub="Aggregates, breakdowns, what changed, what-ifs. Answered over SQL, narrated by a model."
          >
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (question.trim()) router.push(`/ask?q=${encodeURIComponent(question.trim())}`);
              }}
              className="flex gap-2"
            >
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="How much is at risk right now?"
                aria-label="Ask a question"
                className="input flex-1 border-model-line focus:border-model"
              />
              <Button variant="model" type="submit" disabled={!question.trim()}>
                Ask
              </Button>
            </form>
            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {["What changed since the last run?", "Break down open exceptions by category."].map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => router.push(`/ask?q=${encodeURIComponent(q)}`)}
                  className="rounded-full border border-model-line px-2.5 py-1 text-[11px] text-model transition-colors hover:bg-model-soft"
                >
                  {q}
                </button>
              ))}
            </div>
          </Panel>

          <Panel title="Sources" sub="Rows in this run, by origin">
            {sources.length === 0 ? (
              <Skeleton className="h-12" />
            ) : (
              <>
                <div className="flex h-2 overflow-hidden rounded-full bg-surface-3">
                  {sources.map((s) => (
                    <div key={s.label} style={{ background: sourceMeta(s.label).color, flex: s.count / sourceTotal }} />
                  ))}
                </div>
                <ul className="mt-3 flex flex-col gap-1.5">
                  {sources.map((s) => (
                    <li key={s.label} className="flex items-center justify-between text-[12.5px]">
                      <span className="flex items-center gap-2 text-ink-2">
                        <SourceDot source={s.label} />
                        {sourceMeta(s.label).label}
                      </span>
                      <span className="num text-[15px] text-ink">{formatCount(s.count)}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
