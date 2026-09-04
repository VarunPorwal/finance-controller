"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, type components } from "./client";
import { queryKeys } from "./query-keys";

type RunSummary = components["schemas"]["RunSummaryOut"];

interface RunContextValue {
  summary: RunSummary | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const RunContext = createContext<RunContextValue | null>(null);

async function fetchRunSummary(): Promise<RunSummary> {
  // The run the tenant pinned, resolved server-side. Deriving it here from
  // "newest original and complete" meant an upload made to test the ingest
  // slot could become the run that loads on open.
  const { data: pinned, error: listError } = await apiClient.GET("/api/v1/runs/default", {});
  if (listError || !pinned) {
    throw new Error(listError ? "could not reach the API" : "no runs yet");
  }
  const { data: runSummary, error: summaryError } = await apiClient.GET(
    "/api/v1/runs/{run_id}/summary",
    { params: { path: { run_id: pinned.run_id } } },
  );
  if (summaryError || !runSummary) {
    throw new Error("could not load the run summary");
  }
  return runSummary;
}

/**
 * Loads the most recent run's summary once, at the app shell, so the header
 * strip and every tab share one fetch instead of each re-deriving "which run
 * is this" on its own. `refresh()` invalidates the entire query cache - it
 * is the single call site every action that completes a run (ingest
 * finalize, demo corpus, replay) routes through, so a completed run
 * propagates to exceptions/rules/cash/eval/etc. without each of them
 * separately knowing "a run just finished." The cache is small at this
 * app's demo scale, so a blanket invalidation over a narrower predicate
 * that has to be kept in sync with every new query key is the right trade.
 */
export function RunProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.runDefault,
    queryFn: fetchRunSummary,
  });

  return (
    <RunContext.Provider
      value={{
        summary: data ?? null,
        loading: isLoading,
        error: error instanceof Error ? error.message : null,
        refresh: () => {
          void queryClient.invalidateQueries();
        },
      }}
    >
      {children}
    </RunContext.Provider>
  );
}

export function useRun(): RunContextValue {
  const ctx = useContext(RunContext);
  if (!ctx) throw new Error("useRun must be used inside <RunProvider>");
  return ctx;
}
