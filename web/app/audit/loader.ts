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


import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, ShieldCheck, ShieldAlert } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { StatusPill } from "@/components/ui/status-pill";
import { PlaceholderPanel } from "@/components/placeholder-panel";
import { queryKeys } from "@/lib/query-keys";

export type AuditEvent = components["schemas"]["AuditEventOut"];
export type VerifyChainOut = components["schemas"]["VerifyChainOut"];
export type AuditBundle = { events: AuditEvent[]; chain: VerifyChainOut | null };

export async function fetchAuditBundle(runId: string | undefined): Promise<AuditBundle> {
  const [eventsRes, chainRes] = await Promise.all([
    apiClient.GET("/api/v1/audit", { params: { query: { run_id: runId, limit: 100 } } }),
    apiClient.GET("/api/v1/audit/verify-chain", { params: { query: {} } }),
  ]);
  return { events: eventsRes.data?.items ?? [], chain: chainRes.data ?? null };
}
