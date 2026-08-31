"use client";

import { useQuery } from "@tanstack/react-query";
import { Landmark, Database, CreditCard } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { IngestPanel } from "@/components/ingest-panel";
import { StatusPill } from "@/components/ui/status-pill";
import { queryKeys } from "@/lib/query-keys";

type EventCount = components["schemas"]["EventCountOut"];
type AuditEvent = components["schemas"]["AuditEventOut"];
type SourcesBundle = { counts: EventCount | null; history: AuditEvent[] };

const CONNECTORS = [
  { key: "razorpay", name: "Razorpay", icon: CreditCard, iconBg: "var(--primary-tint)", iconColor: "var(--primary)" },
  { key: "bank", name: "HDFC Bank", icon: Landmark, iconBg: "var(--amber-bg)", iconColor: "var(--amber-text)" },
  { key: "tally", name: "Tally", icon: Database, iconBg: "var(--success-bg)", iconColor: "var(--success)" },
];

export async function fetchSourcesBundle(runId: string): Promise<SourcesBundle> {
  const [countRes, auditRes] = await Promise.all([
    apiClient.GET("/api/v1/events/count", { params: { query: { run_id: runId } } }),
    apiClient.GET("/api/v1/audit", { params: { query: { subject_id: runId, limit: 50 } } }),
  ]);
  return {
    counts: countRes.data ?? null,
    history: (auditRes.data?.items ?? []).filter((e) => e.action.startsWith("ingest.")),
  };
}

export default function DataSourcesPage() {
  const { summary, refresh } = useRun();
  const runId = summary?.run.run_id;
  const { data } = useQuery({
    queryKey: queryKeys.sources(runId),
    queryFn: () => fetchSourcesBundle(runId!),
    enabled: !!runId,
  });
  const counts = data?.counts ?? null;
  const history = data?.history ?? [];

  return (
    <div>
      <div className="mb-4.5">
        <div className="text-2xl font-semibold tracking-[-0.025em]">Data Sources</div>
        <div className="mt-[3px] text-[13px] text-text-muted">
          Bring your financial records into Finco
        </div>
      </div>

      <div className="mb-5 grid grid-cols-3 gap-5">
        {CONNECTORS.map((c) => {
          const Icon = c.icon;
          const count = counts?.by_source[c.key] ?? 0;
          const connected = count > 0;
          return (
            <div key={c.key} className="fc-card">
              <div className="flex items-center justify-between px-5 pt-4">
                <div
                  className="flex h-8 w-8 items-center justify-center rounded-[9px]"
                  style={{ background: c.iconBg, color: c.iconColor }}
                >
                  <Icon width={15} height={15} />
                </div>
                <StatusPill tone={connected ? "success" : "neutral"}>
                  {connected ? "Connected" : "Not yet uploaded"}
                </StatusPill>
              </div>
              <div className="px-5 pt-3.5 pb-5">
                <div className="text-[15px] font-semibold">{c.name}</div>
                <div className="mt-1 text-xs text-text-muted">
                  {connected ? `${count.toLocaleString("en-IN")} rows this run` : "No rows ingested yet"}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="fc-card mb-5 overflow-hidden">
        <div className="border-b border-border px-5 py-3.5 text-sm font-semibold">Import history</div>
        <div className="grid grid-cols-[1fr_1.6fr_0.8fr_0.8fr_1fr] border-b border-[color:var(--neutral-bg)] px-5 py-2.5 text-[11px] font-semibold tracking-[0.03em] text-text-muted">
          <div>SOURCE</div>
          <div>FILE</div>
          <div className="text-right">ROWS</div>
          <div>STATUS</div>
          <div>TIME</div>
        </div>
        {history.length === 0 && (
          <div className="p-5 text-center text-sm text-text-muted">Nothing imported yet.</div>
        )}
        {history.map((h) => {
          const payload = h.payload as Record<string, unknown>;
          const rejectionCount = Number(payload.rejection_count ?? 0);
          return (
            <div
              key={h.seq}
              className="grid grid-cols-[1fr_1.6fr_0.8fr_0.8fr_1fr] items-center border-b border-[color:var(--neutral-bg)] px-5 py-3 text-[13px] last:border-0"
            >
              <div className="font-medium">{h.action.replace("ingest.", "")}</div>
              <div className="fc-numeric text-[12.5px] text-text-body">
                {String(payload.filename ?? "—")}
              </div>
              <div className="fc-numeric text-right text-base">{String(payload.event_count ?? 0)}</div>
              <div>
                <StatusPill tone={rejectionCount > 0 ? "amber" : "success"}>
                  {rejectionCount > 0 ? `${rejectionCount} rejected` : "Healthy"}
                </StatusPill>
              </div>
              <div className="text-[12.5px] text-text-muted">
                {new Date(h.created_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
              </div>
            </div>
          );
        })}
      </div>

      <IngestPanel onComplete={refresh} />
    </div>
  );
}
