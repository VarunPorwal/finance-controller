"use client";

// Overview. The one question: is my money under control? Reskinned to the
// Finco design system — see `finco-tokens.css` and `_overview-fc/blocks.tsx`.
// Fixed summary: no filters, nothing here is recomputed from other pages'
// figures (CLAUDE.md: "a figure appears on one screen only").

import { useMemo } from "react";
import { ErrorNote } from "./_components/ui";
import { sumPaise } from "./_lib/format";
import {
  useCashBridge,
  useEvents,
  useEventsCount,
  useExceptions,
  useMatches,
  useCurrentRun,
  useRuns,
  type CashBridge,
  type Exception,
} from "./_lib/api";
import {
  AgentBanner,
  CashPosition,
  NeedsDecision,
  OverviewHeader,
  SourceTrace,
  SubBar,
  Tiles,
  UnmatchedByDay,
  openExceptionsOf,
  openSubtotalOf,
} from "./_overview-fc/blocks";

function reconciledPctOf(bridge: CashBridge | undefined): number | undefined {
  if (!bridge) return undefined;
  const gross = bridge.gross_collected_paise;
  return gross > 0 ? Math.max(0, 1 - Math.abs(bridge.unexplained_paise) / gross) : 1;
}

export default function OverviewPage() {
  const { run, loading, error } = useCurrentRun();
  const bridge = useCashBridge(run?.run_id);
  const exceptions = useExceptions(run?.run_id);
  const matches = useMatches(run?.run_id);
  const eventsCount = useEventsCount(run?.run_id);
  const runs = useRuns("original", 5);

  const prevRun = (runs.data ?? [])
    .filter((r) => r.run_id !== run?.run_id && run && r.started_at < run.started_at && r.finished_at !== null)
    .sort((a, b) => (a.started_at < b.started_at ? 1 : a.started_at > b.started_at ? -1 : 0))[0];
  const prevBridge = useCashBridge(prevRun?.run_id);

  const anyError = error ?? bridge.error?.message ?? exceptions.error?.message;

  const open = exceptions.data ? openExceptionsOf(exceptions.data) : undefined;
  const autoResolvedCount = matches.data ? matches.data.filter((m) => m.auto_closed).length : undefined;
  const topNeeds = open ? [...open].sort((a, b) => b.amount_paise - a.amount_paise).slice(0, 3) : undefined;

  const events = useEvents(topNeeds && topNeeds.length > 0 ? run?.run_id : undefined);
  const counterpartyById = useMemo(() => {
    const map = new Map<string, string>();
    for (const ev of events.data ?? []) {
      if (ev.counterparty) map.set(ev.event_id, ev.counterparty);
    }
    return map;
  }, [events.data]);
  const counterpartyOf = (e: Exception) => {
    for (const id of e.event_ids) {
      const c = counterpartyById.get(id);
      if (c) return c;
    }
    return undefined;
  };

  const reconciledPct = reconciledPctOf(bridge.data);
  const reconciledPrevPct = prevRun ? reconciledPctOf(prevBridge.data) : null;
  const reconciledDelta = prevRun && reconciledPct !== undefined && reconciledPrevPct != null ? reconciledPct - reconciledPrevPct : prevRun ? undefined : null;

  const inflow = open ? sumPaise(open.filter((e) => e.status === "monitoring" || e.category === "timing_lag").map((e) => e.amount_paise)) : undefined;
  const outflow = open ? sumPaise(open.filter((e) => e.category === "chargeback_unrecorded").map((e) => e.amount_paise)) : undefined;

  return (
    <div style={{ minHeight: "100%", padding: "20px 26px 40px" }}>
      <OverviewHeader run={run} />

      {anyError ? (
        <ErrorNote message={anyError} />
      ) : !run ? (
        <div className="fc-faint" style={{ fontSize: 13 }}>
          {loading ? "Loading run…" : "No run yet."}
        </div>
      ) : (
        <>
          <SubBar reconciledPct={reconciledPct} asOfIso={run.period_end} />

          <Tiles
            totalCash={bridge.data?.books_vs_bank.bank_balance_paise}
            asOfIso={run.period_end}
            reconciledPct={reconciledPct}
            reconciledDeltaPct={reconciledDelta}
            openCount={open?.length}
            openSubtotal={open ? openSubtotalOf(open) : undefined}
            autoResolvedCount={autoResolvedCount}
          />

          <SourceTrace bySource={eventsCount.data?.by_source} matches={matches.data} openExceptions={open} />

          <div className="fc-split mb-3" style={{ alignItems: "stretch" }}>
            <UnmatchedByDay exceptions={open} asOfIso={run.period_end ?? run.started_at} index={0} />
            <div className="flex flex-col gap-3">
              <CashPosition balance={bridge.data?.books_vs_bank.bank_balance_paise} inflow={inflow} outflow={outflow} index={0} />
              <NeedsDecision items={topNeeds} counterpartyOf={counterpartyOf} index={1} />
            </div>
          </div>

          <AgentBanner run={run} index={2} />
        </>
      )}
    </div>
  );
}
