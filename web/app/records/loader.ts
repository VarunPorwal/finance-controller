/**
 * Prefetch loader for this route, kept out of `page.tsx` on purpose.
 *
 * Next's App Router type-checks every `page.tsx` against a closed set of
 * allowed exports — a default component and a fixed list of route config
 * symbols, and nothing else. Exporting a loader beside the component fails the
 * production build with "Property 'fetch...' is incompatible with index
 * signature". A sibling module is not a route file, so it may export whatever
 * the page and the app shell both need to import.
 */


import { useQuery } from "@tanstack/react-query";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";
import { StatusPill } from "@/components/ui/status-pill";
import { queryKeys } from "@/lib/query-keys";

export type EventCount = components["schemas"]["EventCountOut"];
export type AuditEvent = components["schemas"]["AuditEventOut"];
export type TransactionEvent = components["schemas"]["TransactionEvent"];
export type RecordsBundle = { counts: EventCount | null; history: AuditEvent[]; events: TransactionEvent[] };

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
