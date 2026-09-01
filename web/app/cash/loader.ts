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
import { StatCard } from "@/components/ui/stat-card";
import { PlaceholderPanel } from "@/components/placeholder-panel";
import { queryKeys } from "@/lib/query-keys";

export type CashBridgeOut = components["schemas"]["CashBridgeOut"];

export async function fetchCashBridge(runId: string): Promise<CashBridgeOut | null> {
  return (await apiClient.GET("/api/v1/cash/bridge", { params: { query: { run_id: runId } } })).data ?? null;
}
