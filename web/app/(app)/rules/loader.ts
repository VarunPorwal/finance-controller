/**
 * Prefetch loader for this route, kept out of `page.tsx` on purpose: Next's
 * App Router only allows a fixed set of exports from a page module.
 */
import { apiClient, type components } from "@/lib/client";

export type Rule = components["schemas"]["Rule"];
export type SuggestionOut = components["schemas"]["SuggestionOut"];
export type BacktestOut = components["schemas"]["BacktestOut"];

export async function fetchRulesAndSuggestions() {
  const [rulesRes, suggestionsRes] = await Promise.all([
    apiClient.GET("/api/v1/rules", { params: { query: {} } }),
    apiClient.GET("/api/v1/rules/suggestions", {}),
  ]);
  return { rules: rulesRes.data ?? [], suggestions: suggestionsRes.data ?? [] };
}
