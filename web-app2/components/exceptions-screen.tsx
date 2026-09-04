"use client";

import { useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useRun } from "@/lib/run-context";
import { Segmented } from "@/components/ui/segmented";
import { ExceptionsTable } from "@/components/exceptions-table";
import { EvidencePack } from "@/components/evidence-pack";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { MetaRow, PageHeader } from "@/components/page-header";
import { Pill } from "@/components/ui/pill";
import { cn } from "@/lib/utils";

type Filter = "all" | "high" | "monitor" | "auto";

/**
 * The queue on the left, the evidence for the selected item on the right.
 * The human reads the evidence, then says what they know; the instruction
 * box lives at the bottom of the evidence, in context.
 */
export function ExceptionsScreen({ activeId }: { activeId?: string }) {
  const { summary, loading, error } = useRun();
  const router = useRouter();
  const searchParams = useSearchParams();
  const status = (searchParams.get("status") as Filter) ?? "all";

  const setStatus = useCallback(
    (value: string) => {
      const params = new URLSearchParams(searchParams);
      if (value === "all") params.delete("status");
      else params.set("status", value);
      const base = activeId ? `/exceptions/${activeId}` : "/exceptions";
      const qs = params.toString();
      router.push(qs ? `${base}?${qs}` : base, { scroll: false });
    },
    [router, searchParams, activeId],
  );

  if (loading) return <Skeleton className="h-64" />;
  if (error || !summary) {
    return <EmptyState title="No run yet" note={error ?? "Ingest files or run the demo corpus to see the queue."} />;
  }
  const runId = summary.run.run_id;
  const qs = status !== "all" ? `?status=${status}` : "";

  return (
    <div>
      <PageHeader
        title="Exceptions"
        sub={
          <MetaRow
            items={[
              <span key="open">
                <span className="num text-ink">{summary.exception_count}</span> open
              </span>,
              <span key="you">
                <span className="num text-bad">{summary.escalated_count}</span> need you
              </span>,
              <span key="mon">
                <span className="num text-warn">{summary.monitor_count}</span> monitoring
              </span>,
            ]}
          />
        }
        actions={
          <Segmented
            active={status}
            onChange={setStatus}
            options={[
              { value: "all", label: "All", count: summary.exception_count },
              { value: "high", label: "Needs you", count: summary.escalated_count },
              { value: "monitor", label: "Monitor", count: summary.monitor_count },
              { value: "auto", label: "Auto", count: Math.max(summary.exception_count - summary.escalated_count - summary.monitor_count, 0) },
            ]}
          />
        }
      />

      <div className={cn("grid grid-cols-1 gap-5", activeId && "xl:grid-cols-[minmax(0,1fr)_460px]")}>
        <div className="min-w-0">
          <ExceptionsTable
            runId={runId}
            statusFilter={status}
            activeId={activeId}
            linkTo={(id) => `/exceptions/${id}${qs}`}
            enableBulk
            compact={!!activeId}
          />
        </div>
        {activeId && (
          <aside className="xl:sticky xl:top-[72px] xl:self-start">
            <div className="mb-2 flex items-center justify-between">
              <Pill tone="accent">Evidence</Pill>
              <button type="button" onClick={() => router.push(`/exceptions${qs}`)} className="text-[11.5px] text-ink-3 hover:text-ink">
                Close
              </button>
            </div>
            <EvidencePack exceptionId={activeId} onApplied={() => router.push(`/exceptions${qs}`)} />
          </aside>
        )}
      </div>
    </div>
  );
}
