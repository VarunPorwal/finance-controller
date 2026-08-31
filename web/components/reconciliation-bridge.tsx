"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient, type components } from "@/lib/client";
import { formatPaiseWhole } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";

type CashBridge = components["schemas"]["CashBridgeOut"];

/**
 * design/README.md's Cash Bridge card: 4 segments (gross settled, deductions
 * collapsed into one "fees/GST/TDS/reserve" block, credited to bank,
 * unexplained gap), each with a 3px colour rule, an icon tile and a mono
 * amount. Every figure is `*_paise` off `GET /cash/bridge` — nothing here is
 * derived client-side except the deduction total, which is a plain sum of
 * server-supplied integers, not a new financial computation.
 *
 * Hovering the deductions segment highlights every event any deduction
 * attributes to; clicking the gap filters the queue to its exceptions — the
 * same two callbacks the exceptions screen wires into the triage queue.
 */
export function ReconciliationBridge({
  runId,
  onHoverSegment,
  onSelectGap,
}: {
  runId: string;
  onHoverSegment: (eventIds: string[] | null) => void;
  onSelectGap: (exceptionIds: string[] | null) => void;
}) {
  const [gapSelected, setGapSelected] = useState(false);

  const { data: bridge, error: queryError } = useQuery({
    queryKey: queryKeys.cashBridge(runId),
    queryFn: async () => {
      const { data, error: fetchError } = await apiClient.GET("/api/v1/cash/bridge", {
        params: { query: { run_id: runId } },
      });
      if (fetchError || !data) throw new Error("could not load the cash bridge");
      return data;
    },
  });
  const error = queryError ? "could not load the cash bridge" : null;

  if (error) {
    return <div className="fc-card p-4 text-sm text-amber-text">{error}</div>;
  }
  if (!bridge) {
    return <div className="fc-card h-[180px] animate-pulse" aria-hidden />;
  }

  const deductionTotalPaise = bridge.deductions.reduce((sum, d) => sum + d.amount_paise, 0);
  const deductionEventIds = bridge.deductions.flatMap((d) => d.event_ids);
  const unexplainedSegment = bridge.segments.find((s) => s.label === "Unexplained");
  const gapNonZero = bridge.unexplained_paise !== 0;

  const segments = [
    {
      key: "gross",
      color: "var(--primary)",
      iconBg: "var(--primary-tint)",
      amount: formatPaiseWhole(bridge.gross_collected_paise),
      caption: "Gross settled",
      onEnter: () => onHoverSegment(bridge.gross_event_ids),
      onLeave: () => onHoverSegment(null),
    },
    { key: "fees", color: "var(--text-body)", iconBg: "var(--neutral-bg)", amount: `−${formatPaiseWhole(deductionTotalPaise)}`, caption: "Fees, GST, TDS, reserve", onEnter: () => onHoverSegment(deductionEventIds), onLeave: () => onHoverSegment(null) },
    {
      key: "credited",
      color: "var(--success)",
      iconBg: "var(--success-bg)",
      amount: formatPaiseWhole(bridge.actual_bank_paise),
      caption: "Credited to bank",
      onEnter: () => onHoverSegment(bridge.actual_bank_event_ids),
      onLeave: () => onHoverSegment(null),
    },
    {
      key: "gap",
      color: gapNonZero ? "var(--amber-text)" : "var(--success)",
      iconBg: gapNonZero ? "var(--amber-bg)" : "var(--success-bg)",
      amount: formatPaiseWhole(bridge.unexplained_paise),
      caption: "Unexplained gap",
      clickable: gapNonZero,
      onClick: gapNonZero
        ? () => {
            const next = !gapSelected;
            setGapSelected(next);
            onSelectGap(next ? (unexplainedSegment?.exception_ids ?? []) : null);
          }
        : undefined,
    },
  ];

  return (
    <div className="fc-card">
      <div className="flex items-center justify-between px-[22px] pt-4">
        <div className="text-sm font-semibold">Cash Bridge</div>
      </div>
      <div className="px-[22px] pt-3.5 pb-5">
        <div className="grid grid-cols-4 gap-4">
          {segments.map((s) => (
            <div
              key={s.key}
              className={s.clickable ? "cursor-pointer" : undefined}
              style={{ borderTop: `3px solid ${s.color}`, paddingTop: 12 }}
              onMouseEnter={s.onEnter}
              onMouseLeave={s.onLeave}
              onClick={s.onClick}
              aria-pressed={s.key === "gap" ? gapSelected : undefined}
            >
              <div
                className="mb-2.5 h-[26px] w-[26px] rounded-[8px]"
                style={{ background: s.iconBg }}
              />
              <div className="fc-numeric text-[22px] font-semibold whitespace-nowrap" style={{ color: s.color }}>
                {s.amount}
              </div>
              <div className="mt-[3px] text-xs text-text-muted">{s.caption}</div>
            </div>
          ))}
        </div>
        <div className="mt-4 border-t border-[color:var(--neutral-bg)] pt-3.5 text-[12.5px] text-text-body">
          Expected in bank was {formatPaiseWhole(bridge.expected_net_paise)}. The{" "}
          {formatPaiseWhole(bridge.unexplained_paise)} shortfall is what the review queue exists
          to close.
        </div>
      </div>
    </div>
  );
}
