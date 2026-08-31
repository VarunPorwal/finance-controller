"use client";

import { useQuery } from "@tanstack/react-query";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";
import { StatusPill } from "@/components/ui/status-pill";
import { queryKeys } from "@/lib/query-keys";

type EventCount = components["schemas"]["EventCountOut"];
type AuditEvent = components["schemas"]["AuditEventOut"];
type TransactionEvent = components["schemas"]["TransactionEvent"];
type RecordsBundle = { counts: EventCount | null; history: AuditEvent[]; events: TransactionEvent[] };

// Ledger rows are stored with source="ledger" (fc/ingest/tally.py: source
// data comes from Tally, but the by_source/audit-action key it writes is
// "ledger", not "tally") — the lookup key has to match that, not the
// connector's display name.
const SOURCES = ["razorpay", "bank", "ledger"] as const;
const SOURCE_LABEL: Record<string, string> = { ledger: "Tally" };

export async function fetchRecordsBundle(runId: string): Promise<RecordsBundle> {
  const [countRes, auditRes, eventsRes] = await Promise.all([
    apiClient.GET("/api/v1/events/count", { params: { query: { run_id: runId } } }),
    apiClient.GET("/api/v1/audit", { params: { query: { subject_id: runId, limit: 50 } } }),
    apiClient.GET("/api/v1/events", { params: { query: { run_id: runId, limit: 30 } } }),
  ]);
  return {
    counts: countRes.data ?? null,
    history: (auditRes.data?.items ?? []).filter((e) => e.action.startsWith("ingest.")),
    events: eventsRes.data?.items ?? [],
  };
}

export default function RecordsPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data } = useQuery({
    queryKey: queryKeys.records(runId),
    queryFn: () => fetchRecordsBundle(runId!),
    enabled: !!runId,
  });
  const counts = data?.counts ?? null;
  const history = data?.history ?? [];
  const events = data?.events ?? [];

  const lastImportBySource = new Map(history.map((h) => [h.action.replace("ingest.", ""), h]));

  return (
    <div>
      <div className="mb-4.5">
        <div className="text-2xl font-semibold tracking-[-0.025em]">Records</div>
        <div className="mt-[3px] text-[13px] text-text-muted">
          Normalized transactions across all connected sources
        </div>
      </div>

      <div className="mb-5 grid grid-cols-3 gap-5">
        {SOURCES.map((source) => {
          const count = counts?.by_source[source] ?? 0;
          const lastImport = lastImportBySource.get(source);
          const rejectionCount = Number((lastImport?.payload as Record<string, unknown> | undefined)?.rejection_count ?? 0);
          return (
            <div key={source} className="fc-card">
              <div className="px-5 pt-4 text-sm font-semibold capitalize">{SOURCE_LABEL[source] ?? source}</div>
              <div className="px-5 pt-3.5 pb-5">
                <div className="fc-numeric text-[22px] font-semibold">{count.toLocaleString("en-IN")}</div>
                <div className="mt-0.5 text-xs text-text-muted">
                  records · {lastImport ? new Date(lastImport.created_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "never"}
                </div>
                <div className="mt-2.5">
                  <StatusPill tone={rejectionCount > 0 ? "amber" : count > 0 ? "success" : "neutral"}>
                    {rejectionCount > 0 ? `${rejectionCount} rejected` : count > 0 ? "Healthy" : "No data"}
                  </StatusPill>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="fc-card overflow-hidden">
        <div className="grid grid-cols-[1fr_1fr_1.4fr_1fr_1fr] border-b border-[color:var(--neutral-bg)] px-5 py-2.5 text-[11px] font-semibold tracking-[0.03em] text-text-muted">
          <div>DATE</div>
          <div>SOURCE</div>
          <div>REFERENCE</div>
          <div className="text-right">AMOUNT</div>
          <div>STATUS</div>
        </div>
        {events.map((e) => (
          <div
            key={e.event_id}
            className="grid grid-cols-[1fr_1fr_1.4fr_1fr_1fr] items-center border-b border-[color:var(--neutral-bg)] px-5 py-3 text-[13px] last:border-0"
          >
            <div className="text-[12.5px] text-text-body">
              {new Date(e.txn_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}
            </div>
            <div className="font-medium capitalize">{e.source}</div>
            <div className="fc-numeric truncate text-[12.5px] text-text-body">
              {e.utr ?? e.settlement_id ?? e.voucher_number ?? e.order_id ?? "—"}
            </div>
            <div className="fc-numeric text-right text-base font-medium">{formatPaise(e.amount_paise)}</div>
            <div>
              <StatusPill tone="success">{e.direction === "credit" ? "Credit" : "Debit"}</StatusPill>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
