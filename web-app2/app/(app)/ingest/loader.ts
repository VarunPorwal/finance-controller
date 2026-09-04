/**
 * Prefetch loader for this route, kept out of `page.tsx` on purpose: Next's
 * App Router only allows a fixed set of exports from a page module.
 */
import { apiClient, type components } from "@/lib/client";

export type EventCount = components["schemas"]["EventCountOut"];
export type AuditEvent = components["schemas"]["AuditEventOut"];
export type SourcesBundle = { counts: EventCount | null; history: AuditEvent[] };

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
