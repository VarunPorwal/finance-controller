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


import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Plus, Sparkle, Upload } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { humanizeSnakeCase } from "@/lib/format";
import { FilterPills } from "@/components/ui/filter-pills";
import { StatusPill } from "@/components/ui/status-pill";
import { RuleAuthoringForm, type RuleSubmitPayload } from "@/components/rule-authoring-form";
import { BacktestDialog } from "@/components/backtest-dialog";
import { queryKeys } from "@/lib/query-keys";

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
