"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { apiClient, type components } from "@/lib/client";
import { formatPaise, formatDecimalPercent, humanizeSnakeCase } from "@/lib/format";
import { TIER_SHORT, TIER_TONE } from "@/lib/tier";
import { Pill } from "@/components/ui/pill";
import { SourceGlyph } from "@/components/ui/source-glyph";
import { Button } from "@/components/ui/button";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

type ExceptionOut = components["schemas"]["Exception_"];
type ClusterOut = components["schemas"]["Cluster"];
type BulkActionKind = components["schemas"]["BulkAction"]["action"];
type ActionGroup = ExceptionOut["action_group"];

/**
 * What to do, not what went wrong, in the order of the working day. The
 * grouping is assigned server-side by `fc/exceptions/action.py`; this table
 * renders what it is given.
 */
const ACTION_SECTIONS: { group: ActionGroup; label: string; note: string }[] = [
  { group: "act_today", label: "Act today", note: "a window is closing" },
  { group: "waiting", label: "Waiting", note: "the system will look again" },
  { group: "books_fix", label: "Books fix", note: "the daybook is what changes" },
  { group: "cannot_resolve", label: "Cannot resolve", note: "no file here can settle it" },
  { group: "unidentified_inflow", label: "Unidentified inflows", note: "money arrived · nothing at stake" },
];

export interface Row {
  exception: ExceptionOut;
  clusterLabel: string;
}

interface RowDetail {
  counterparty: string;
  source: string;
  reference: string;
}

// The queue itself is one round trip and renders at once. Counterparty and
// reference live on TransactionEvent, not Exception_, so each row's evidence
// is fetched afterwards and filled in as it arrives.
async function fetchRows(runId: string, limit: number | undefined): Promise<Row[]> {
  const [excRes, clusterRes] = await Promise.all([
    apiClient.GET("/api/v1/exceptions", { params: { query: { run_id: runId, status: "open", limit: 200 } } }),
    apiClient.GET("/api/v1/clusters", { params: { query: { run_id: runId, limit: 100 } } }),
  ]);
  if (excRes.error || !excRes.data) throw new Error("could not load exceptions");
  const clusters = clusterRes.data?.items ?? [];
  const clusterById = new Map(clusters.map((c: ClusterOut) => [c.cluster_id, c]));
  const visible = limit ? excRes.data.items.slice(0, limit) : excRes.data.items;
  return visible.map((exc) => ({
    exception: exc,
    clusterLabel: exc.cluster_id ? (clusterById.get(exc.cluster_id)?.label ?? humanizeSnakeCase(exc.category)) : humanizeSnakeCase(exc.category),
  }));
}

async function fetchDetails(ids: string[]): Promise<Record<string, RowDetail>> {
  const evidences = await Promise.all(
    ids.map((id) => apiClient.GET("/api/v1/exceptions/{exception_id}/evidence", { params: { path: { exception_id: id } } })),
  );
  const out: Record<string, RowDetail> = {};
  ids.forEach((id, i) => {
    const firstEvent = evidences[i].data?.events?.[0];
    out[id] = {
      counterparty: firstEvent?.counterparty ?? firstEvent?.source ?? "-",
      source: firstEvent?.source ?? "razorpay",
      reference: firstEvent?.utr ?? firstEvent?.settlement_id ?? firstEvent?.order_id ?? firstEvent?.voucher_number ?? "-",
    };
  });
  return out;
}

export function ExceptionsTable({
  runId,
  limit,
  statusFilter,
  onlyIds,
  highlightEventIds,
  activeId,
  linkTo,
  enableBulk,
  compact,
}: {
  runId: string;
  limit?: number;
  statusFilter?: "all" | "high" | "monitor" | "auto";
  /** When set, only these exception ids show (the bridge gap filter). */
  onlyIds?: string[] | null;
  /** Rows whose events intersect these ids are lit (the bridge hover). */
  highlightEventIds?: string[] | null;
  activeId?: string;
  linkTo?: (exceptionId: string) => string;
  enableBulk?: boolean;
  compact?: boolean;
}) {
  const queryClient = useQueryClient();
  const rowsQueryKey = queryKeys.exceptions(runId, { limit: limit ?? "all" });
  const { data: rows, error } = useQuery({ queryKey: rowsQueryKey, queryFn: () => fetchRows(runId, limit) });
  const ids = (rows ?? []).map((r) => r.exception.exception_id);
  const { data: details } = useQuery({
    queryKey: [...rowsQueryKey, "details", ids],
    queryFn: () => fetchDetails(ids),
    enabled: ids.length > 0,
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkReason, setBulkReason] = useState("");
  const router = useRouter();

  const bulkMutation = useMutation({
    mutationFn: async ({ action, reason, exceptionIds }: { action: BulkActionKind; reason: string; exceptionIds: string[] }) => {
      const { data } = await apiClient.POST("/api/v1/exceptions/bulk", { body: { exception_ids: exceptionIds, action, reason } });
      return data;
    },
    onMutate: async ({ exceptionIds }) => {
      await queryClient.cancelQueries({ queryKey: rowsQueryKey });
      const previous = queryClient.getQueryData<Row[]>(rowsQueryKey);
      queryClient.setQueryData<Row[]>(rowsQueryKey, (old) => (old ?? []).filter((r) => !exceptionIds.includes(r.exception.exception_id)));
      setSelected(new Set());
      setBulkReason("");
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(rowsQueryKey, context.previous);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: rowsQueryKey });
      void queryClient.invalidateQueries({ queryKey: queryKeys.runDefault });
    },
  });

  const highlight = highlightEventIds ? new Set(highlightEventIds) : null;
  const only = onlyIds ? new Set(onlyIds) : null;
  const filtered = (rows ?? []).filter((r) => {
    if (only && !only.has(r.exception.exception_id)) return false;
    if (!statusFilter || statusFilter === "all") return true;
    if (statusFilter === "high") return r.exception.tier === "escalate";
    if (statusFilter === "monitor") return r.exception.tier === "monitor";
    return r.exception.tier === "auto";
  });

  if (error) return <div className="panel p-4 text-[12.5px] text-warn">{(error as Error).message}</div>;
  if (!rows) {
    return (
      <div className="panel">
        <SkeletonRows rows={limit ?? 8} />
      </div>
    );
  }
  if (filtered.length === 0) {
    return (
      <EmptyState
        title={only ? "No exceptions carry this gap" : "Nothing needs you here"}
        note={only ? "Clear the gap filter to see the whole queue." : "Every open item is under another filter, or the run is clean."}
      />
    );
  }

  function toggleAll() {
    setSelected((prev) => (prev.size === filtered.length ? new Set() : new Set(filtered.map((r) => r.exception.exception_id))));
  }
  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function runBulk(action: BulkActionKind) {
    if (!bulkReason.trim()) return;
    bulkMutation.mutate({ action, reason: bulkReason.trim(), exceptionIds: Array.from(selected) });
  }

  const cols = (enableBulk ? 1 : 0) + (compact ? 6 : 7);

  return (
    <div className="panel overflow-hidden">
      {enableBulk && selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2 px-4 py-2.5">
          <span className="num text-[12px] font-semibold text-ink">{selected.size} selected</span>
          <input
            value={bulkReason}
            onChange={(e) => setBulkReason(e.target.value)}
            placeholder="Reason, recorded in the audit trail"
            aria-label="Reason"
            className="input h-[28px] max-w-[360px] flex-1"
          />
          <Button size="sm" variant="ok" disabled={bulkMutation.isPending || !bulkReason.trim()} onClick={() => runBulk("resolve")}>
            Resolve
          </Button>
          <Button size="sm" disabled={bulkMutation.isPending || !bulkReason.trim()} onClick={() => runBulk("write_off")}>
            Write off
          </Button>
          <Button size="sm" variant="bad" disabled={bulkMutation.isPending || !bulkReason.trim()} onClick={() => runBulk("escalate")}>
            Escalate
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              {enableBulk && (
                <th className="th w-9 pl-4">
                  <input
                    type="checkbox"
                    checked={filtered.length > 0 && selected.size === filtered.length}
                    onChange={toggleAll}
                    aria-label="Select all"
                  />
                </th>
              )}
              <th className="th pl-4">Counterparty</th>
              <th className="th">Exception</th>
              {!compact && <th className="th">Cause cluster</th>}
              <th className="th">Reference</th>
              <th className="th text-right">Amount</th>
              <th className="th text-right">Confidence</th>
              <th className="th pr-4 text-right">Tier</th>
            </tr>
          </thead>
          <tbody>
            <AnimatePresence initial={false}>
            {ACTION_SECTIONS.flatMap((section) => {
              const group = filtered.filter((r) => r.exception.action_group === section.group);
              if (group.length === 0) return [];
              const total = group.reduce((sum, r) => sum + r.exception.residual_paise, 0);
              return [
                <tr key={`head-${section.group}`} className="bg-surface-2/70">
                  <td colSpan={cols} className="px-4 py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="label text-ink-2">{section.label}</span>
                      <span className="num text-[10.5px] text-ink-3">{group.length}</span>
                      <span className="text-[11px] text-ink-3">· {section.note}</span>
                      <span className="num ml-auto text-[11px] text-ink-3">{formatPaise(total)}</span>
                    </div>
                  </td>
                </tr>,
                ...group.map((row) => {
                  const tier = row.exception.tier;
                  const detail = details?.[row.exception.exception_id];
                  const href = linkTo?.(row.exception.exception_id);
                  const lit = highlight ? row.exception.event_ids.some((id) => highlight.has(id)) : false;
                  const dim = highlight ? !lit : false;
                  const active = activeId === row.exception.exception_id;
                  return (
                    <motion.tr
                      key={row.exception.exception_id}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0, x: 14 }}
                      transition={{ duration: 0.18, ease: [0.23, 1, 0.32, 1] }}
                      onClick={href ? () => router.push(href) : undefined}
                      tabIndex={href ? 0 : undefined}
                      role={href ? "link" : undefined}
                      onKeyDown={
                        href
                          ? (e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                router.push(href);
                              }
                            }
                          : undefined
                      }
                      className={cn(
                        "text-[12.5px] transition-opacity",
                        href && "row-link",
                        lit && "bg-accent-soft",
                        dim && "opacity-35",
                        active && "bg-surface-3",
                      )}
                    >
                      {enableBulk && (
                        <td className="td w-9 pl-4" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={selected.has(row.exception.exception_id)}
                            onChange={() => toggleOne(row.exception.exception_id)}
                            aria-label={`Select ${detail?.counterparty ?? row.exception.exception_id}`}
                          />
                        </td>
                      )}
                      <td className="td pl-4">
                        <div className="flex items-center gap-2.5">
                          {detail ? <SourceGlyph source={detail.source} size={22} /> : <span className="skeleton h-[22px] w-[22px] rounded-[7px]" />}
                          {detail ? (
                            <span className="truncate font-medium text-ink">{detail.counterparty}</span>
                          ) : (
                            <span className="skeleton h-3 w-24" />
                          )}
                        </div>
                      </td>
                      <td className="td text-ink-2">{humanizeSnakeCase(row.exception.category)}</td>
                      {!compact && <td className="td max-w-[220px] truncate text-ink-3">{row.clusterLabel}</td>}
                      <td className="td num text-[11.5px] text-ink-3">{detail ? detail.reference : <span className="skeleton inline-block h-3 w-28 align-middle" />}</td>
                      <td className="td num text-right text-[15px] font-medium text-ink">{formatPaise(row.exception.residual_paise)}</td>
                      <td className="td num text-right text-[12.5px] text-ink-3">
                        {row.exception.confidence ? formatDecimalPercent(row.exception.confidence) : "-"}
                      </td>
                      <td className="td pr-4 text-right">
                        <Pill tone={TIER_TONE[tier]} dot>
                          {TIER_SHORT[tier]}
                        </Pill>
                      </td>
                    </motion.tr>
                  );
                }),
              ];
            })}
            </AnimatePresence>
          </tbody>
        </table>
      </div>
    </div>
  );
}
