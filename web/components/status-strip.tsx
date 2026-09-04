"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient, type components } from "@/lib/client";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

type Health = components["schemas"]["api__routers__agent__HealthOut"];

/**
 * One glance answers "is this thing actually calling a model, and how much."
 * Polls every 15s regardless of the run-scoped staleTime: this is live status.
 */
export function StatusStrip() {
  const { data: health } = useQuery({
    queryKey: queryKeys.agentHealth,
    queryFn: async () => (await apiClient.GET("/api/v1/agent/health", { params: { query: {} } })).data ?? null,
    staleTime: 0,
    refetchInterval: 15_000,
  });

  if (!health) return <span className="text-[11px] text-ink-3">model status</span>;

  const tierEntries = Object.entries((health as Health).tiers ?? {});

  return (
    <div className="flex items-center gap-3 text-[11px]" title="Model router status">
      {tierEntries.map(([tier, models]) => {
        const rows = models as Array<Record<string, unknown>>;
        const anyAvailable = rows.some((row) => row.available);
        return (
          <span key={tier} className="flex items-center gap-1.5 text-ink-2">
            <span className={cn("h-1.5 w-1.5 rounded-full", anyAvailable ? "bg-ok" : "bg-warn")} />
            {tier}
          </span>
        );
      })}
      <span className="num text-ink-3">{health.calls_this_run} calls</span>
      <span className="num text-ink-3">{health.cache_hit_rate} cached</span>
      {health.degraded && <span className="rounded-[5px] bg-warn-soft px-1.5 py-0.5 font-semibold text-warn">degraded</span>}
    </div>
  );
}
