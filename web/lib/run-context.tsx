"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { apiClient, type components } from "./client";

type RunSummary = components["schemas"]["RunSummaryOut"];

interface RunContextValue {
  summary: RunSummary | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const RunContext = createContext<RunContextValue | null>(null);

/**
 * Loads the most recent run's summary once, at the app shell, so the header
 * strip and every tab share one fetch instead of each re-deriving "which run
 * is this" on its own. Re-fetched on `refresh()` (wired to the header's
 * "Run" button once triggering a new run is built).
 */
export function RunProvider({ children }: { children: ReactNode }) {
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      const { data: runs, error: listError } = await apiClient.GET("/api/v1/runs", {
        params: { query: { limit: 1 } },
      });
      if (cancelled) return;
      if (listError || !runs || runs.items.length === 0) {
        setLoading(false);
        setError(listError ? "could not reach the API" : "no runs yet");
        return;
      }
      const runId = runs.items[0].run_id;
      const { data: runSummary, error: summaryError } = await apiClient.GET(
        "/api/v1/runs/{run_id}/summary",
        { params: { path: { run_id: runId } } },
      );
      if (cancelled) return;
      if (summaryError || !runSummary) {
        setLoading(false);
        setError("could not load the run summary");
        return;
      }
      setSummary(runSummary);
      setLoading(false);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [generation]);

  return (
    <RunContext.Provider
      value={{ summary, loading, error, refresh: () => setGeneration((g) => g + 1) }}
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
