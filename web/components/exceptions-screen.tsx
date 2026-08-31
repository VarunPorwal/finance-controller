"use client";

import { useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useRun } from "@/lib/run-context";
import { FilterPills } from "@/components/ui/filter-pills";
import { ExceptionsTable } from "@/components/exceptions-table";
import { EvidencePack } from "@/components/evidence-pack";
import { PlaceholderPanel } from "@/components/placeholder-panel";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "high", label: "High" },
  { value: "auto", label: "Auto-resolved" },
];

export function ExceptionsScreen({ activeId }: { activeId?: string }) {
  const { summary, loading, error } = useRun();
  const router = useRouter();
  const searchParams = useSearchParams();
  const status = (searchParams.get("status") as "all" | "high" | "auto") ?? "all";

  const setStatus = useCallback(
    (value: string) => {
      const params = new URLSearchParams(searchParams);
      if (value === "all") params.delete("status");
      else params.set("status", value);
      const base = activeId ? `/exceptions/${activeId}` : "/exceptions";
      router.push(`${base}?${params.toString()}`, { scroll: false });
    },
    [router, searchParams, activeId],
  );

  if (loading) return <div className="fc-card h-40 animate-pulse" aria-hidden />;
  if (error || !summary) {
    return <PlaceholderPanel title="No run yet" note={error ?? "Start a run to see exceptions."} />;
  }
  const runId = summary.run.run_id;

  return (
    <div>
      <div className="mb-4.5">
        <div className="text-2xl font-semibold tracking-[-0.025em]">Exceptions</div>
        <div className="mt-[3px] text-[13px] text-text-muted">
          {summary.exception_count} open · {summary.escalated_count} needing you
        </div>
      </div>
      <FilterPills options={FILTERS} active={status} onChange={setStatus} />
      <ExceptionsTable
        runId={runId}
        statusFilter={status}
        linkTo={(id) => `/exceptions/${id}${status !== "all" ? `?status=${status}` : ""}`}
        enableBulk
      />
      {activeId && (
        <div className="mt-5">
          <EvidencePack
            exceptionId={activeId}
            onApplied={() => router.push(status !== "all" ? `/exceptions?status=${status}` : "/exceptions")}
          />
        </div>
      )}
    </div>
  );
}
