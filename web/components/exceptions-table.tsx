"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Landmark, Database, CreditCard } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise, formatDecimalPercent, humanizeSnakeCase } from "@/lib/format";
import { StatusPill } from "@/components/ui/status-pill";

type ExceptionOut = components["schemas"]["Exception_"];
type ClusterOut = components["schemas"]["Cluster"];

const SOURCE_ICON: Record<string, typeof Landmark> = {
  bank: Landmark,
  tally: Database,
  razorpay: CreditCard,
};

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
}: {
  runId: string;
  limit?: number;
  statusFilter?: "all" | "high" | "auto";
  linkTo?: (exceptionId: string) => string;
}) {
  const [exceptions, setExceptions] = useState<ExceptionOut[] | null>(null);
  const [clusters, setClusters] = useState<ClusterOut[]>([]);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setRows(null);
      const [excRes, clusterRes] = await Promise.all([
        apiClient.GET("/api/v1/exceptions", {
          params: { query: { run_id: runId, status: "open", limit: 200 } },
        }),
        apiClient.GET("/api/v1/clusters", { params: { query: { run_id: runId, limit: 100 } } }),
      ]);
      if (cancelled) return;
      if (excRes.error || !excRes.data) {
        setError("could not load exceptions");
        return;
      }
      setExceptions(excRes.data.items);
      setClusters(clusterRes.data?.items ?? []);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const clusterById = useMemo(
    () => new Map(clusters.map((c) => [c.cluster_id, c])),
    [clusters],
  );

  useEffect(() => {
    if (!exceptions) return;
    let cancelled = false;
    async function loadEvidence() {
      const visible = limit ? exceptions!.slice(0, limit) : exceptions!;
      const evidences = await Promise.all(
        visible.map((exc) =>
          apiClient.GET("/api/v1/exceptions/{exception_id}/evidence", {
            params: { path: { exception_id: exc.exception_id } },
          }),
        ),
      );
      if (cancelled) return;
      setRows(
        visible.map((exc, i) => {
          const firstEvent = evidences[i].data?.events?.[0];
          return {
            exception: exc,
            clusterLabel: exc.cluster_id
              ? (clusterById.get(exc.cluster_id)?.label ?? humanizeSnakeCase(exc.category))
              : humanizeSnakeCase(exc.category),
            counterparty: firstEvent?.counterparty ?? firstEvent?.source ?? "—",
            source: firstEvent?.source ?? "razorpay",
            reference: firstEvent?.utr ?? firstEvent?.settlement_id ?? firstEvent?.order_id ?? "—",
          };
        }),
      );
    }
    void loadEvidence();
    return () => {
      cancelled = true;
    };
  }, [exceptions, clusterById, limit]);

  const filtered = (rows ?? []).filter((r) => {
    if (!statusFilter || statusFilter === "all") return true;
    if (statusFilter === "high") return r.exception.tier === "escalate";
    return r.exception.tier === "auto";
  });

  if (error) return <div className="fc-card p-4 text-sm text-amber-text">{error}</div>;
  if (!rows) return <div className="fc-card h-64 animate-pulse" aria-hidden />;

  return (
    <div className="fc-card overflow-hidden">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-[color:var(--neutral-bg)] text-[11px] font-semibold tracking-[0.03em] text-text-muted">
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
          {filtered.map((row) => {
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
          })}
        </tbody>
      </table>
    </div>
  );
}
