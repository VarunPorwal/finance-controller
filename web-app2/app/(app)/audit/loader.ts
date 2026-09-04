/**
 * Prefetch loader for this route, kept out of `page.tsx` on purpose: Next's
 * App Router only allows a fixed set of exports from a page module.
 */
import { apiClient, type components } from "@/lib/client";

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
