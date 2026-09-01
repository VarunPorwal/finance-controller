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
import { useRouter } from "next/navigation";
import { Landmark, Database, CreditCard } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { IngestPanel } from "@/components/ingest-panel";
import { StatusPill } from "@/components/ui/status-pill";
import { queryKeys } from "@/lib/query-keys";

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
