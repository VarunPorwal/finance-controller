"use client";

import { useEffect, useState } from "react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";
import { StatCard } from "@/components/ui/stat-card";
import { PlaceholderPanel } from "@/components/placeholder-panel";
import { cacheGet, cacheSet } from "@/lib/page-cache";

type CashBridgeOut = components["schemas"]["CashBridgeOut"];

export default function CashPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const [bridge, setBridge] = useState<CashBridgeOut | null | undefined>(() =>
    cacheGet<CashBridgeOut>(runId ? `cash:${runId}` : null) ?? undefined,
  );

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const seeded = cacheGet<CashBridgeOut>(`cash:${runId}`);
    if (seeded) setBridge(seeded);
    apiClient
      .GET("/api/v1/cash/bridge", { params: { query: { run_id: runId } } })
      .then((res) => {
        if (cancelled) return;
        const data = res.data ?? null;
        if (data) cacheSet(`cash:${runId}`, data);
        setBridge(data);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return (
    <div>
      <div className="mb-4.5">
        <div className="text-2xl font-semibold tracking-[-0.025em]">Cash</div>
        <div className="mt-[3px] text-[13px] text-text-muted">
          What was collected, what was deducted, and where the rest is sitting
        </div>
      </div>

      {bridge === undefined && <div className="fc-card h-40 animate-pulse" aria-hidden />}

      {bridge === null && (
        <PlaceholderPanel title="No cash bridge for this run" note="Start or select a run to compute the cash position." />
      )}

      {bridge && (
        <>
          <div className="mb-5 grid grid-cols-4 gap-5">
            <StatCard label="Gross collected" value={formatPaise(bridge.gross_collected_paise)} valueSize="22" />
            <StatCard label="Expected net" value={formatPaise(bridge.expected_net_paise)} valueSize="22" />
            <StatCard label="Actual bank credit" value={formatPaise(bridge.actual_bank_paise)} valueSize="22" />
            <StatCard
              label="Unexplained"
              value={formatPaise(bridge.unexplained_paise)}
              valueSize="22"
              badge={{
                label: bridge.unexplained_paise === 0 ? "CLEAN" : "GAP",
                tone: bridge.unexplained_paise === 0 ? "success" : "amber",
              }}
            />
          </div>

          <div className="mb-5 grid grid-cols-3 gap-5">
            <StatCard label="Cash at risk" value={formatPaise(bridge.cash_at_risk_paise)} valueSize="22" sub="tied up in open exceptions" />
            <StatCard
              label="Reserve pending release"
              value={formatPaise(bridge.reserve_pending_release_paise)}
              valueSize="22"
              sub="Razorpay rolling reserve"
            />
            <StatCard
              label="GST input credit claimable"
              value={formatPaise(bridge.gst_input_credit_claimable_paise)}
              valueSize="22"
              sub="from fees paid on settlements"
            />
          </div>

          <div className="fc-card overflow-hidden">
            <div className="border-b border-border px-5 py-3.5 text-sm font-semibold">
              Bridge — gross to actual, by deduction
            </div>
            <table className="w-full">
              <thead>
                <tr className="border-b border-[color:var(--neutral-bg)] text-[11px] font-semibold tracking-[0.03em] text-text-muted">
                  <th className="px-5 py-2.5 text-left">SEGMENT</th>
                  <th className="px-3 py-2.5 text-right">AMOUNT</th>
                  <th className="px-5 py-2.5 text-right">ATTRIBUTED</th>
                </tr>
              </thead>
              <tbody>
                {bridge.deductions.map((d, i) => (
                  <tr key={i} className="border-b border-[color:var(--neutral-bg)] text-[13px] last:border-0">
                    <td className="px-5 py-3">{d.label}</td>
                    <td className="fc-numeric px-3 py-3 text-right">{formatPaise(d.amount_paise)}</td>
                    <td className="fc-numeric px-5 py-3 text-right text-text-muted">{formatPaise(d.attributed_paise)}</td>
                  </tr>
                ))}
                {bridge.deductions.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-5 py-5 text-center text-sm text-text-muted">
                      No deduction segments for this run.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {bridge.segments.length > 0 && (
            <div className="fc-card mt-5 overflow-hidden">
              <div className="border-b border-border px-5 py-3.5 text-sm font-semibold">
                Unexplained segments — evidence
              </div>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-[color:var(--neutral-bg)] text-[11px] font-semibold tracking-[0.03em] text-text-muted">
                    <th className="px-5 py-2.5 text-left">SEGMENT</th>
                    <th className="px-3 py-2.5 text-right">AMOUNT</th>
                    <th className="px-5 py-2.5 text-right">EXCEPTIONS</th>
                  </tr>
                </thead>
                <tbody>
                  {bridge.segments.map((s, i) => (
                    <tr key={i} className="border-b border-[color:var(--neutral-bg)] text-[13px] last:border-0">
                      <td className="px-5 py-3">{s.label}</td>
                      <td className="fc-numeric px-3 py-3 text-right">{formatPaise(s.amount_paise)}</td>
                      <td className="fc-numeric px-5 py-3 text-right text-text-muted">{s.exception_ids.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
