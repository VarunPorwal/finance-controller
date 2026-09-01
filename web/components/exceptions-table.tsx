"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Landmark, Database, CreditCard } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise, formatDecimalPercent, humanizeSnakeCase } from "@/lib/format";
import { StatusPill } from "@/components/ui/status-pill";
import { queryKeys } from "@/lib/query-keys";

type ExceptionOut = components["schemas"]["Exception_"];
type ClusterOut = components["schemas"]["Cluster"];
type BulkActionKind = components["schemas"]["BulkAction"]["action"];

const SOURCE_ICON: Record<string, typeof Landmark> = {
  bank: Landmark,
  tally: Database,
  razorpay: CreditCard,
};

type ActionGroup = ExceptionOut["action_group"];

/**
 * What to do, not what went wrong — and the order of the working day.
 *
 * A category names the shape of a discrepancy. It does not say whether
 * somebody has to act this morning, whether the right move is to wait, whether
 * the fix belongs in the daybook, or whether nothing in the files can settle
 * it. Sorting by category interleaves four different jobs.
 *
 * The fifth heading sits beside the four rather than inside them: an
 * unidentified inflow is money that *arrived*, and filing a ₹2,86,440 inward
 * remittance under "cannot resolve" makes that section's total read as
 * exposure when the money is in the account. Assigned server-side by
 * `fc/exceptions/action.py`; this table renders the grouping it is given.
 */
const ACTION_SECTIONS: { group: ActionGroup; label: string; note: string }[] = [
  { group: "act_today", label: "Act today", note: "a window is closing" },
  { group: "waiting", label: "Waiting", note: "the system will look again" },
  { group: "books_fix", label: "Books fix", note: "the daybook is what changes" },
  { group: "cannot_resolve", label: "Cannot resolve", note: "no file here can settle it" },
  {
    group: "unidentified_inflow",
    label: "Unidentified inflows",
    note: "money arrived · nothing at stake",
  },
];

const TIER_LABEL: Record<ExceptionOut["tier"], { label: string; tone: "error" | "amber" | "success" }> = {
  escalate: { label: "HIGH", tone: "error" },
  monitor: { label: "MONITOR", tone: "amber" },
  auto: { label: "AUTO", tone: "success" },
};

interface Row {
  exception: ExceptionOut;
  clusterLabel: string;
  counterparty: string;
  source: string;
  reference: string;
}

async function fetchRows(runId: string, limit: number | undefined): Promise<Row[]> {
  const [excRes, clusterRes] = await Promise.all([
    apiClient.GET("/api/v1/exceptions", { params: { query: { run_id: runId, status: "open", limit: 200 } } }),
    apiClient.GET("/api/v1/clusters", { params: { query: { run_id: runId, limit: 100 } } }),
  ]);
  if (excRes.error || !excRes.data) {
    throw new Error("could not load exceptions");
  }
  const clusters = clusterRes.data?.items ?? [];
  const clusterById = new Map(clusters.map((c: ClusterOut) => [c.cluster_id, c]));
  const visible = limit ? excRes.data.items.slice(0, limit) : excRes.data.items;
  const evidences = await Promise.all(
    visible.map((exc) =>
      apiClient.GET("/api/v1/exceptions/{exception_id}/evidence", {
        params: { path: { exception_id: exc.exception_id } },
      }),
    ),
  );
  return visible.map((exc, i) => {
    const firstEvent = evidences[i].data?.events?.[0];
    return {
      exception: exc,
      clusterLabel: exc.cluster_id
        ? (clusterById.get(exc.cluster_id)?.label ?? humanizeSnakeCase(exc.category))
        : humanizeSnakeCase(exc.category),
      counterparty: firstEvent?.counterparty ?? firstEvent?.source ?? "—",
      source: firstEvent?.source ?? "razorpay",
      reference:
        firstEvent?.utr ??
        firstEvent?.settlement_id ??
        firstEvent?.order_id ??
        firstEvent?.voucher_number ??
        "—",
    };
  });
}

/**
 * design/README.md's "Decisions requiring attention" / Exceptions table,
 * shared by the Reconcile home (top 5, no filters, no link) and the full
 * Exceptions screen (all rows, filter pills). Counterparty and reference
 * live on TransactionEvent, not Exception_, so each row's evidence is
 * fetched once — small N at this app's demo scale (CLAUDE.md: 46
 * exceptions) — rather than adding a bulk-join endpoint for one screen.
 */
export function ExceptionsTable({
  runId,
  limit,
  statusFilter,
  linkTo,
  enableBulk,
}: {
  runId: string;
  limit?: number;
  statusFilter?: "all" | "high" | "auto";
  linkTo?: (exceptionId: string) => string;
  enableBulk?: boolean;
}) {
  const queryClient = useQueryClient();
  const rowsQueryKey = queryKeys.exceptions(runId, { limit: limit ?? "all" });
  const { data: rows, error } = useQuery({
    queryKey: rowsQueryKey,
    queryFn: () => fetchRows(runId, limit),
  });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const router = useRouter();

  const bulkMutation = useMutation({
    mutationFn: async ({ action, reason, exceptionIds }: { action: BulkActionKind; reason: string; exceptionIds: string[] }) => {
      const { data } = await apiClient.POST("/api/v1/exceptions/bulk", {
        body: { exception_ids: exceptionIds, action, reason },
      });
      return data;
    },
    onMutate: async ({ exceptionIds }) => {
      await queryClient.cancelQueries({ queryKey: rowsQueryKey });
      const previous = queryClient.getQueryData<Row[]>(rowsQueryKey);
      // Optimistic: the rows leave the queue immediately. Rolled back in
      // onError if the bulk action doesn't actually apply.
      queryClient.setQueryData<Row[]>(rowsQueryKey, (old) =>
        (old ?? []).filter((r) => !exceptionIds.includes(r.exception.exception_id)),
      );
      setSelected(new Set());
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(rowsQueryKey, context.previous);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: rowsQueryKey });
    },
  });

  const filtered = (rows ?? []).filter((r) => {
    if (!statusFilter || statusFilter === "all") return true;
    if (statusFilter === "high") return r.exception.tier === "escalate";
    return r.exception.tier === "auto";
  });

  if (error) return <div className="fc-card p-4 text-sm text-amber-text">{(error as Error).message}</div>;
  if (!rows) return <div className="fc-card h-64 animate-pulse" aria-hidden />;

  function toggleAll() {
    setSelected((prev) =>
      prev.size === filtered.length ? new Set() : new Set(filtered.map((r) => r.exception.exception_id)),
    );
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
    const reason = window.prompt(`Reason to ${action.replace("_", " ")} ${selected.size} exception(s):`);
    if (!reason?.trim()) return;
    bulkMutation.mutate({ action, reason: reason.trim(), exceptionIds: Array.from(selected) });
  }

  return (
    <div className="fc-card overflow-hidden">
      {enableBulk && selected.size > 0 && (
        <div className="flex items-center justify-between border-b border-border bg-primary-tint px-5 py-2.5 text-[12.5px]">
          <span className="font-semibold text-primary-active-text">{selected.size} selected</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={bulkMutation.isPending}
              onClick={() => runBulk("resolve")}
              className="rounded-[7px] bg-success-bg px-3 py-1.5 text-xs font-semibold text-success disabled:opacity-50"
            >
              Resolve
            </button>
            <button
              type="button"
              disabled={bulkMutation.isPending}
              onClick={() => runBulk("write_off")}
              className="rounded-[7px] border border-border px-3 py-1.5 text-xs font-semibold text-text-body disabled:opacity-50"
            >
              Write off
            </button>
            <button
              type="button"
              disabled={bulkMutation.isPending}
              onClick={() => runBulk("escalate")}
              className="rounded-[7px] bg-error-bg px-3 py-1.5 text-xs font-semibold text-error disabled:opacity-50"
            >
              Escalate
            </button>
          </div>
        </div>
      )}
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-[color:var(--neutral-bg)] text-[11px] font-semibold tracking-[0.03em] text-text-muted">
            {enableBulk && (
              <th className="w-9 px-5 py-2.5 text-left">
                <input
                  type="checkbox"
                  checked={filtered.length > 0 && selected.size === filtered.length}
                  onChange={toggleAll}
                  aria-label="Select all"
                />
              </th>
            )}
            <th className="px-5 py-2.5 text-left">COUNTERPARTY</th>
            <th className="px-3 py-2.5 text-left">EXCEPTION</th>
            <th className="px-3 py-2.5 text-left">CAUSE CLUSTER</th>
            <th className="px-3 py-2.5 text-left">REFERENCE</th>
            <th className="px-3 py-2.5 text-right">AMOUNT</th>
            <th className="px-3 py-2.5 text-right">CONFIDENCE</th>
            <th className="px-5 py-2.5 text-right">TIER</th>
          </tr>
        </thead>
        <tbody>
          {ACTION_SECTIONS.flatMap((section) => {
            const group = filtered.filter((r) => r.exception.action_group === section.group);
            if (group.length === 0) return [];
            const total = group.reduce((sum, r) => sum + r.exception.amount_paise, 0);
            return [
              <tr key={`head-${section.group}`} className="bg-[color:var(--neutral-bg)]">
                <td colSpan={enableBulk ? 8 : 7} className="px-5 py-2">
                  <span className="text-[11.5px] font-semibold uppercase tracking-wide text-text-heading">
                    {section.label} · {group.length}
                  </span>
                  <span className="ml-2 text-[11px] text-text-muted">{section.note}</span>
                  <span className="float-right fc-numeric text-[11.5px] text-text-muted">
                    {formatPaise(total)}
                  </span>
                </td>
              </tr>,
              ...group.map((row) => {
                const Icon = SOURCE_ICON[row.source] ?? CreditCard;
            const tier = TIER_LABEL[row.exception.tier];
            const href = linkTo?.(row.exception.exception_id);
            return (
              <tr
                key={row.exception.exception_id}
                onClick={href ? () => router.push(href) : undefined}
                className={
                  "border-b border-[color:var(--neutral-bg)] text-[13px] last:border-0" +
                  (href ? " cursor-pointer hover:bg-neutral-bg" : "")
                }
              >
                {enableBulk && (
                  <td className="w-9 px-5 py-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(row.exception.exception_id)}
                      onChange={() => toggleOne(row.exception.exception_id)}
                      aria-label={`Select ${row.counterparty}`}
                    />
                  </td>
                )}
                <td className="px-5 py-3">
                  <div className="flex items-center gap-2.5">
                    <span
                      className="flex h-6 w-6 flex-none items-center justify-center rounded-[7px]"
                      style={{
                        background: tier.tone === "error" ? "var(--error-bg)" : "var(--success-bg)",
                        color: tier.tone === "error" ? "var(--error)" : "var(--success)",
                      }}
                    >
                      <Icon width={12} height={12} />
                    </span>
                    {row.counterparty}
                  </div>
                </td>
                <td className="px-3 py-3">{humanizeSnakeCase(row.exception.category)}</td>
                <td className="px-3 py-3 text-text-body">{row.clusterLabel}</td>
                <td className="fc-numeric px-3 py-3 text-[12.5px] text-text-muted">{row.reference}</td>
                <td className="fc-numeric px-3 py-3 text-right text-base font-medium">
                  {formatPaise(row.exception.residual_paise)}
                </td>
                <td className="fc-numeric px-3 py-3 text-right text-base text-text-muted">
                  {row.exception.confidence ? formatDecimalPercent(row.exception.confidence) : "—"}
                </td>
                <td className="px-5 py-3 text-right">
                  <StatusPill tone={tier.tone}>{tier.label}</StatusPill>
                </td>
              </tr>
            );
              }),
            ];
          })}
        </tbody>
      </table>
    </div>
  );
}
