/**
 * Prefetch loader for this route, kept out of `page.tsx` on purpose: Next's
 * App Router only allows a fixed set of exports from a page module.
 */
import { apiClient, type components } from "@/lib/client";

export type CashBridgeOut = components["schemas"]["CashBridgeOut"];

export async function fetchCashBridge(runId: string): Promise<CashBridgeOut | null> {
  return (await apiClient.GET("/api/v1/cash/bridge", { params: { query: { run_id: runId } } })).data ?? null;
}
