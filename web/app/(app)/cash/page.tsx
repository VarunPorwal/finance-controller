"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRun } from "@/lib/run-context";
import { formatPaise } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { PageHeader } from "@/components/page-header";
import { Stat } from "@/components/ui/stat";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { fetchCashBridge } from "./loader";

export default function CashPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data: bridgeData, isFetched } = useQuery({ queryKey: queryKeys.cashBridge(runId), queryFn: () => fetchCashBridge(runId!), enabled: !!runId });
  const bridge = !runId || isFetched ? (bridgeData ?? null) : undefined;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Cash" sub="What was collected, what was deducted, what is still exposed, and what can be claimed back." />

      {bridge === undefined && <Skeleton className="h-64" />}
      {bridge === null && <EmptyState title="No cash position for this run" note="Start or select a run to compute the bridge." />}

      {bridge && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat label="Gross collected" value={formatPaise(bridge.gross_collected_paise)} sub="stated by the gateway, per row" />
            <Stat label="Expected net" value={formatPaise(bridge.expected_net_paise)} sub="after fees, GST, TDS and reserve" />
            <Stat label="Credited to bank" value={formatPaise(bridge.actual_bank_paise)} tone="ok" sub="the only figure that proves money moved" />
            <Stat
              label="Unexplained"
              value={formatPaise(bridge.unexplained_paise)}
              tone={bridge.unexplained_paise === 0 ? "ok" : "warn"}
              badge={{ label: bridge.unexplained_paise === 0 ? "clean" : "gap", tone: bridge.unexplained_paise === 0 ? "ok" : "warn" }}
              sub={
                <Link href="/reconcile" className="text-accent hover:underline">
                  See the bridge →
                </Link>
              }
            />
          </div>

          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Stat
              label="Cash at risk"
              value={formatPaise(bridge.cash_at_risk_paise)}
              tone={bridge.cash_at_risk_paise === 0 ? "ok" : "bad"}
              sub={
                bridge.at_risk.item_count === 0
                  ? "nothing can still be lost"
                  : `${bridge.at_risk.item_count} item${bridge.at_risk.item_count === 1 ? "" : "s"}${bridge.at_risk.earliest_deadline ? ` · earliest deadline ${bridge.at_risk.earliest_deadline}` : ""}`
              }
            />
            <Stat label="Held by gateway" value={formatPaise(bridge.held_paise)} tone={bridge.held_paise === 0 ? undefined : "warn"} sub="on hold, not yet settled" />
            <Stat label="Reserve pending release" value={formatPaise(bridge.reserve_pending_release_paise)} sub="rolling reserve, released later" />
            <Stat label="GST input credit" value={formatPaise(bridge.gst_input_credit_claimable_paise)} tone="accent" sub="claimable on fees paid" />
          </div>

          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_1fr]">
            <Panel title="Deductions" sub="Gross to expected net, by kind. Attributed is the part traced to specific rows." flush>
              <table className="w-full">
                <thead>
                  <tr>
                    <th className="th pl-[18px]">Deduction</th>
                    <th className="th text-right">Amount</th>
                    <th className="th text-right">Attributed</th>
                    <th className="th pr-[18px] text-right">Rows</th>
                  </tr>
                </thead>
                <tbody>
                  {bridge.deductions.map((d, i) => (
                    <tr key={i} className="text-[12.5px]">
                      <td className="td pl-[18px] text-ink">{d.label}</td>
                      <td className="td num text-right text-[15px]">{formatPaise(d.amount_paise)}</td>
                      <td className="td num text-right text-ink-3">{formatPaise(d.attributed_paise)}</td>
                      <td className="td num pr-[18px] text-right text-ink-3">{d.event_ids.length}</td>
                    </tr>
                  ))}
                  {bridge.deductions.length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-[18px] py-6 text-center text-[12.5px] text-ink-3">
                        No deductions in this run.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Panel>

            <Panel title="Unexplained, by segment" sub="Each segment names the exceptions that carry it." flush>
              {bridge.segments.length === 0 ? (
                <div className="px-[18px] py-6 text-center text-[12.5px] text-ink-3">Nothing unexplained.</div>
              ) : (
                <table className="w-full">
                  <thead>
                    <tr>
                      <th className="th pl-[18px]">Segment</th>
                      <th className="th text-right">Amount</th>
                      <th className="th pr-[18px] text-right">Exceptions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bridge.segments.map((s, i) => (
                      <tr key={i} className="text-[12.5px]">
                        <td className="td pl-[18px] text-ink">{s.label}</td>
                        <td className="td num text-right text-[15px]">{formatPaise(s.amount_paise)}</td>
                        <td className="td num pr-[18px] text-right text-ink-3">{s.exception_ids.length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
