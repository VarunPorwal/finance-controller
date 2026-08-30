"use client";

import { useCallback, useState } from "react";
import { useRun } from "@/lib/run-context";
import { ReconciliationBridge } from "@/components/reconciliation-bridge";
import { TriageQueue, type QueueSummary } from "@/components/triage-queue";
import { EvidencePack } from "@/components/evidence-pack";
import { PlaceholderPanel } from "@/components/placeholder-panel";

export function ReconcilePanel() {
  const { summary, loading, error } = useRun();
  const [highlightedEventIds, setHighlightedEventIds] = useState<string[] | null>(null);
  const [gapFilterExceptionIds, setGapFilterExceptionIds] = useState<string[] | null>(null);
  const [selectedExceptionId, setSelectedExceptionId] = useState<string | null>(null);
  const [queueSummary, setQueueSummary] = useState<QueueSummary | null>(null);
  const handleQueueSummary = useCallback((s: QueueSummary) => setQueueSummary(s), []);

  if (loading) {
    return (
      <div className="border-rule bg-ink-800 h-40 animate-pulse rounded-lg border" aria-hidden />
    );
  }
  if (error || !summary) {
    return (
      <PlaceholderPanel
        title="No run yet"
        note={error ?? "Trigger a run to see the bridge and queue."}
      />
    );
  }

  const runId = summary.run.run_id;

  return (
    <div className="flex flex-col gap-4">
      <ReconciliationBridge
        runId={runId}
        onHoverSegment={setHighlightedEventIds}
        onSelectGap={setGapFilterExceptionIds}
      />

      <div className="fc-numeric text-paper-300 flex flex-col gap-0.5 text-sm">
        <p>
          {summary.event_count} records · {summary.match_count} match groups ·{" "}
          {summary.exception_count} exceptions
        </p>
        {/* The line that matters for the workload claim: the raw
            escalate/monitor count, never mixed with the auto-resolved
            population, against the actual queue row count after clustering. */}
        {queueSummary && (
          <p className="text-paper-100">
            {queueSummary.needsYouTotal} exceptions needing a human →{" "}
            {queueSummary.clusterRows + queueSummary.standaloneRows} queue items (
            {queueSummary.clusterRows} clusters, {queueSummary.standaloneRows} standalone)
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <TriageQueue
          runId={runId}
          highlightedEventIds={highlightedEventIds}
          gapFilterExceptionIds={gapFilterExceptionIds}
          onClearGapFilter={() => setGapFilterExceptionIds(null)}
          selectedExceptionId={selectedExceptionId}
          onSelect={setSelectedExceptionId}
          onSummary={handleQueueSummary}
        />
        <EvidencePack exceptionId={selectedExceptionId} />
      </div>
    </div>
  );
}
