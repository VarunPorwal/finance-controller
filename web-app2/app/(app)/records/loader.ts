/**
 * Prefetch loader for this route, kept out of `page.tsx` on purpose: Next's
 * App Router only allows a fixed set of exports from a page module.
 */
import { apiClient, type components } from "@/lib/client";

export type EventCount = components["schemas"]["EventCountOut"];
export type AuditEvent = components["schemas"]["AuditEventOut"];
export type TransactionEvent = components["schemas"]["TransactionEvent"];
export type RecordsBundle = { counts: EventCount | null; history: AuditEvent[]; events: TransactionEvent[] };

export async function fetchRecordsBundle(runId: string): Promise<RecordsBundle> {
  const [countRes, auditRes, eventsRes] = await Promise.all([
    apiClient.GET("/api/v1/events/count", { params: { query: { run_id: runId } } }),
    apiClient.GET("/api/v1/audit", { params: { query: { subject_id: runId, limit: 50 } } }),
    apiClient.GET("/api/v1/events", { params: { query: { run_id: runId, limit: 60 } } }),
  ]);
  return {
    counts: countRes.data ?? null,
    history: (auditRes.data?.items ?? []).filter((e) => e.action.startsWith("ingest.")),
    events: eventsRes.data?.items ?? [],
  };
}
