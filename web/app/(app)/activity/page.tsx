"use client";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { fetchActivityBundle } from "@/lib/page-data";
import { formatCount, formatDurationMs, formatTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { PageHeader } from "@/components/page-header";
import { RunProgressStrip } from "@/components/run-progress-strip";
import { Stat } from "@/components/ui/stat";
import { Panel } from "@/components/ui/panel";
import { Pill } from "@/components/ui/pill";
import { SkeletonRows } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const ACTION_COLOR: Record<string, string> = {
  "run.create": "var(--ok)",
  "run.finalize": "var(--ok)",
  "exception.resolve": "var(--ok)",
  "exception.escalate": "var(--warn)",
  "rule.activate": "var(--accent)",
  "rule.backtest": "var(--accent)",
};

export default function ControllerActivityPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data } = useQuery({ queryKey: queryKeys.activityPage(runId), queryFn: () => fetchActivityBundle(runId) });
  const log = data?.log ?? [];
  const llmCalls = data?.llmCalls ?? [];
  const narrative = data?.narrative ?? null;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Controller Activity" sub="What the agent evaluated, matched and escalated, and every model call it made doing so." />

      <div className="grid grid-cols-3 gap-4">
        <Stat label="Runs today" value={data ? formatCount(data.runsToday) : "—"} />
        <Stat label="Rules in play" value={data ? formatCount(data.activeRuleCount) : "—"} sub="active in the rule book" />
        <Stat label="Avg run time" value={data?.avgRuntimeMs != null ? formatDurationMs(data.avgRuntimeMs) : "—"} sub="across completed runs" />
      </div>

      <RunProgressStrip runId={runId} />

      {narrative && (
        <Panel
          tone="model"
          title={
            <span className="flex items-center gap-2">
              <Sparkles width={13} height={13} />
              Run narrative
            </span>
          }
          sub="Written by a model over the deterministic result. It describes; it never decides."
          actions={
            <span className="num text-[10.5px] text-ink-3">
              {narrative.model_used}
              {narrative.cached ? " · cached" : ""}
            </span>
          }
        >
          <p className="text-[13px] leading-relaxed text-ink">{narrative.narrative}</p>
        </Panel>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.2fr_1fr]">
        <Panel title="Timeline" sub="Audit events for this run, newest first" flush>
          {!data && <SkeletonRows rows={8} />}
          {data && log.length === 0 && <div className="px-[18px] py-8 text-center text-[12.5px] text-ink-3">Nothing logged yet.</div>}
          {log.length > 0 && (
            <ol className="px-[18px] py-2">
              {log.map((e, i) => (
                <li key={e.seq} className="relative flex gap-3.5 py-2.5">
                  {i < log.length - 1 && <span className="absolute top-[22px] left-[3px] h-full w-px bg-line" />}
                  <span className="relative mt-[6px] h-[7px] w-[7px] flex-none rounded-full" style={{ background: ACTION_COLOR[e.action] ?? "var(--ink-4)" }} />
                  <span className="num w-12 flex-none pt-px text-[11px] text-ink-3">{formatTime(e.created_at)}</span>
                  <div className="min-w-0 flex-1">
                    <div className="num text-[12.5px] text-ink">{e.action}</div>
                    <div className="num truncate text-[11px] text-ink-3">
                      {e.actor} · {e.subject_type} {e.subject_id}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Panel>

        <Panel title="Model calls, this run" sub="Six per run budgeted. The count does not grow with the queue." flush>
          {!data && <SkeletonRows rows={5} />}
          {data && llmCalls.length === 0 && <div className="px-[18px] py-8 text-center text-[12.5px] text-ink-3">No model calls recorded for this run.</div>}
          {llmCalls.length > 0 && (
            <ul>
              {llmCalls.map((c) => (
                <li key={c.call_id} className="flex items-center justify-between gap-3 border-b border-line px-[18px] py-2.5 text-[12.5px] last:border-0">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-ink">{c.purpose}</span>
                      <Pill tone="model">{c.tier}</Pill>
                      {c.cached && <Pill tone="neutral">cached</Pill>}
                    </div>
                    <div className="num mt-0.5 truncate text-[11px] text-ink-3">{c.model}</div>
                  </div>
                  <div className="num flex flex-none items-center gap-3 text-[11px] text-ink-3">
                    <span>{(c.input_tokens ?? 0) + (c.output_tokens ?? 0)} tok</span>
                    <span>{c.latency_ms != null ? `${c.latency_ms} ms` : "—"}</span>
                    <span className={cn("font-semibold", c.outcome === "ok" ? "text-ok" : "text-warn")}>{c.outcome}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
