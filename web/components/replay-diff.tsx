"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { GitCompareArrows } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { formatDateTime, formatPaise, humanizeSnakeCase, shortId } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ReplayDiff = components["schemas"]["ReplayDiff"];
type DecisionDiff = components["schemas"]["DecisionDiff"];

/**
 * Replay a run under the active rule set and diff the decisions. The diff
 * is structural (fc.audit.replay.diff_exceptions), not a SQL aggregate.
 */
export function ReplayDiff({ currentRunId }: { currentRunId: string }) {
  const { data: runs = [] } = useQuery({
    queryKey: queryKeys.runsList({ status: "complete", limit: 50 }),
    queryFn: async () => (await apiClient.GET("/api/v1/runs", { params: { query: { status: "complete", limit: 50 } } })).data?.items ?? [],
  });
  const [fromOverride, setFromOverride] = useState<string | null>(null);
  const [toOverride, setToOverride] = useState<string | null>(null);
  const fromRunId = fromOverride ?? runs[1]?.run_id ?? "";
  const toRunId = toOverride ?? runs[0]?.run_id ?? "";
  const [diff, setDiff] = useState<ReplayDiff | null>(null);
  const [diffing, setDiffing] = useState(false);
  const [replaying, setReplaying] = useState(false);
  const [reason, setReason] = useState("");

  async function runDiff() {
    if (!fromRunId || !toRunId) return;
    setDiffing(true);
    const { data } = await apiClient.GET("/api/v1/runs/{from_run_id}/diff/{to_run_id}", {
      params: { path: { from_run_id: fromRunId, to_run_id: toRunId } },
    });
    setDiffing(false);
    setDiff(data?.diff ?? null);
  }

  async function replay() {
    if (!reason.trim()) return;
    setReplaying(true);
    const { data } = await apiClient.POST("/api/v1/runs/{run_id}/replay", {
      params: { path: { run_id: currentRunId } },
      body: { reason: reason.trim(), seed: 8 },
    });
    setReplaying(false);
    if (!data) return;
    setFromOverride(currentRunId);
    setToOverride(data.new_run_id);
    setDiff(data.diff);
    setReason("");
  }

  function line(d: DecisionDiff) {
    const before = d.before ? `${humanizeSnakeCase(d.before.category)} (${formatPaise(d.before.residual_paise)})` : "-";
    const after = d.after ? `${humanizeSnakeCase(d.after.category)} (${formatPaise(d.after.residual_paise)})` : "-";
    return { before, after };
  }

  return (
    <Panel
      title="Replay & diff"
      sub="Same seed, same rules: byte-identical. Change a rule and the diff shows exactly which decisions moved."
      flush
      bodyClassName="px-[18px] py-4"
    >
      <div className="flex flex-wrap items-center gap-2">
        <select value={fromRunId} onChange={(e) => setFromOverride(e.target.value)} className="input num w-[230px]" aria-label="From run">
          <option value="">from run…</option>
          {runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {shortId(r.run_id)} · {formatDateTime(r.started_at)}
            </option>
          ))}
        </select>
        <span className="text-ink-4">→</span>
        <select value={toRunId} onChange={(e) => setToOverride(e.target.value)} className="input num w-[230px]" aria-label="To run">
          <option value="">to run…</option>
          {runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {shortId(r.run_id)} · {formatDateTime(r.started_at)}
            </option>
          ))}
        </select>
        <Button icon={<GitCompareArrows width={13} height={13} />} disabled={!fromRunId || !toRunId || diffing} onClick={runDiff}>
          {diffing ? "Diffing…" : "Diff"}
        </Button>
        <div className="ml-auto flex items-center gap-2">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason to replay under active rules"
            aria-label="Replay reason"
            className="input w-[260px]"
          />
          <Button disabled={!reason.trim() || replaying} onClick={replay}>
            {replaying ? "Replaying…" : "Replay current run"}
          </Button>
        </div>
      </div>

      {diff && (
        <div className="mt-4 overflow-hidden rounded-[8px] border border-line">
          {(["changed", "added", "removed"] as const).map((bucket) => (
            <div key={bucket}>
              <div className="flex items-center gap-2 bg-surface-2 px-3 py-1.5">
                <span className="label">{bucket}</span>
                <span className="num text-[10.5px] text-ink-3">{diff[bucket].length}</span>
              </div>
              {diff[bucket].length === 0 && <div className="px-3 py-2 text-[11.5px] text-ink-3">None</div>}
              {diff[bucket].map((d, i) => {
                const { before, after } = line(d);
                return (
                  <div key={i} className="border-b border-line px-3 py-2.5 text-[12.5px] last:border-0">
                    <div className="flex items-center gap-2.5">
                      <span className={cn("text-ink-3", bucket === "removed" && "line-through")}>{before}</span>
                      <span className="text-ink-4">→</span>
                      <span className="text-ink">{after}</span>
                    </div>
                    <div className="mt-0.5 text-[11px] text-ink-3">{d.why}</div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
