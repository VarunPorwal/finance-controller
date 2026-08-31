"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient, type components } from "@/lib/client";
import { queryKeys } from "@/lib/query-keys";

type Health = components["schemas"]["api__routers__agent__HealthOut"];

/**
 * PRD §13.5 header: "Flash-Lite ✓ Flash ✓ · Groq standby · 4 calls · 2 cached".
 * One glance answers "is this thing actually calling a model, and how much."
 * Polls every 15s regardless of the 5-minute default staleTime — this is
 * live status, not run-scoped data that only changes when a run happens.
 */
export function StatusStrip() {
  const { data: health } = useQuery({
    queryKey: queryKeys.agentHealth,
    queryFn: async () => (await apiClient.GET("/api/v1/agent/health", { params: { query: {} } })).data ?? null,
    staleTime: 0,
    refetchInterval: 15_000,
  });

  if (!health) {
    return <span className="text-text-muted text-xs">model status —</span>;
  }

  const tierEntries = Object.entries(health.tiers ?? {});

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      {tierEntries.map(([tier, models]) => {
        const rows = models as Array<Record<string, unknown>>;
        const anyAvailable = rows.some((row) => row.available);
        return (
          <span key={tier} className="text-text-body">
            {tier}
            <span
              className={anyAvailable ? "text-success ml-1" : "text-amber-text ml-1"}
              aria-label={anyAvailable ? "available" : "standby"}
            >
              {anyAvailable ? "✓" : "standby"}
            </span>
          </span>
        );
      })}
      <span className="text-text-muted">·</span>
      <span className="fc-numeric text-text-body">{health.calls_this_run} calls</span>
      <span className="text-text-muted">·</span>
      <span className="fc-numeric text-text-body">{health.cache_hit_rate} cached</span>
      {health.degraded && <span className="text-amber-text">degraded</span>}
    </div>
  );
}
