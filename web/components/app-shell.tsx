"use client";

import { useState } from "react";
import { useRun } from "@/lib/run-context";
import { formatDurationMs, formatRunTimestamp } from "@/lib/format";
import { StatusStrip } from "@/components/status-strip";
import { TabNav, type TabKey } from "@/components/tab-nav";

export function AppShell({
  reconcile,
  rulebook,
  ask,
}: {
  reconcile: React.ReactNode;
  rulebook: React.ReactNode;
  ask: React.ReactNode;
}) {
  const [tab, setTab] = useState<TabKey>("reconcile");
  const { summary, loading, error, refresh } = useRun();

  return (
    <div className="min-h-screen bg-ink-900 text-paper-100">
      <header className="border-rule border-b">
        <div className="flex items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-baseline gap-3">
            <h1 className="font-heading text-lg font-bold tracking-tight">
              Finance Controller
            </h1>
            <span className="fc-numeric text-paper-300 text-sm">
              {loading && "loading run…"}
              {!loading && error && (
                <span className="text-sig-amber">{error}</span>
              )}
              {!loading && summary && (
                <>
                  Run #{summary.run.run_id.slice(-6)} ·{" "}
                  {formatRunTimestamp(summary.run.started_at)}
                  {summary.run.runtime_ms != null &&
                    ` · ${formatDurationMs(summary.run.runtime_ms)}`}
                </>
              )}
            </span>
          </div>
          <button
            type="button"
            onClick={refresh}
            className="border-rule bg-ink-800 hover:bg-ink-700 rounded-md border px-3 py-1.5 text-sm font-medium text-paper-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rzp-blue"
          >
            Run
          </button>
        </div>
        <div className="flex items-center justify-between gap-4 px-6 pb-3">
          <TabNav active={tab} onChange={setTab} />
          <StatusStrip />
        </div>
      </header>

      <main className="px-6 py-6">
        <div hidden={tab !== "reconcile"}>{reconcile}</div>
        <div hidden={tab !== "rulebook"}>{rulebook}</div>
        <div hidden={tab !== "ask"}>{ask}</div>
      </main>
    </div>
  );
}
