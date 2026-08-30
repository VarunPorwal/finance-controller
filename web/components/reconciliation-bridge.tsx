"use client";

import { useEffect, useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";

type CashBridge = components["schemas"]["CashBridgeOut"];
type Segment = components["schemas"]["BridgeSegmentOut"];

/**
 * PRD §13.4, the signature element. A finance person draws this by hand when
 * explaining a settlement: gross in, named deductions out, expected net,
 * what the bank actually credited, and the gap between the two. Every figure
 * here is `*_paise` off the wire (CashBridgeOut) — nothing is derived
 * client-side.
 *
 * Hovering a deduction highlights its contributing events; clicking the
 * UNEXPLAINED row filters the queue to its exceptions. Both are lifted to
 * the parent via callbacks so the bridge and the queue share one source of
 * truth for "what's currently highlighted."
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
  const [bridge, setBridge] = useState<CashBridge | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gapSelected, setGapSelected] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const { data, error: fetchError } = await apiClient.GET("/api/v1/cash/bridge", {
        params: { query: { run_id: runId } },
      });
      if (cancelled) return;
      if (fetchError || !data) {
        setError("could not load the cash bridge");
        return;
      }
      setBridge(data);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (error) {
    return <div className="text-sig-amber border-rule bg-ink-800 rounded-lg border p-4 text-sm">{error}</div>;
  }
  if (!bridge) {
    return (
      <div className="border-rule bg-ink-800 h-40 animate-pulse rounded-lg border" aria-hidden />
    );
  }

  const scale = Math.max(Math.abs(bridge.gross_collected_paise), 1);
  const gapNonZero = bridge.unexplained_paise !== 0;

  return (
    <section
      aria-label="Reconciliation Bridge"
      className="border-rule bg-ink-800 rounded-lg border p-5"
    >
      <h2 className="font-heading text-paper-300 mb-4 text-xs font-semibold uppercase tracking-wide">
        Reconciliation Bridge
      </h2>

      <BridgeRow label="Gross collected" amountPaise={bridge.gross_collected_paise} widthPct={100} bold />

      <div className="border-rule my-2 border-l-2 pl-3">
        {bridge.deductions.map((segment) => (
          <BridgeRow
            key={segment.label}
            label={segment.label}
            amountPaise={-segment.amount_paise}
            widthPct={(Math.abs(segment.amount_paise) / scale) * 100}
            onMouseEnter={() => onHoverSegment(segment.event_ids)}
            onMouseLeave={() => onHoverSegment(null)}
          />
        ))}
      </div>

      <BridgeRow label="Expected net" amountPaise={bridge.expected_net_paise} widthPct={100} bold />
      <BridgeRow
        label="vs. bank credited"
        amountPaise={bridge.actual_bank_paise}
        widthPct={(bridge.actual_bank_paise / scale) * 100}
      />

      <div className="border-rule mt-3 border-t pt-3">
        <button
          type="button"
          disabled={!gapNonZero}
          onClick={() => {
            const next = !gapSelected;
            setGapSelected(next);
            const unexplained = bridge.segments.find((s: Segment) => s.label === "Unexplained");
            onSelectGap(next ? (unexplained?.exception_ids ?? []) : null);
          }}
          className={
            "flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rzp-blue " +
            (gapNonZero ? "hover:bg-ink-700 cursor-pointer" : "cursor-default")
          }
          aria-pressed={gapSelected}
        >
          <span className="font-heading font-semibold text-paper-100">Unexplained</span>
          <span
            className={
              "fc-numeric font-semibold " + (gapNonZero ? "text-sig-red" : "text-sig-green")
            }
          >
            {formatPaise(bridge.unexplained_paise)}
            {gapNonZero ? " 🔴" : " ✓"}
          </span>
        </button>
      </div>
    </section>
  );
}

function BridgeRow({
  label,
  amountPaise,
  widthPct,
  bold,
  onMouseEnter,
  onMouseLeave,
}: {
  label: string;
  amountPaise: number;
  widthPct: number;
  bold?: boolean;
  onMouseEnter?: () => void;
  onMouseLeave?: () => void;
}) {
  return (
    <div
      className="group flex items-center justify-between gap-3 rounded-md px-2 py-1 hover:bg-ink-700"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span
          className={
            "truncate text-sm " + (bold ? "text-paper-100 font-semibold" : "text-paper-300")
          }
        >
          {label}
        </span>
        <span className="bg-ink-700 h-1.5 flex-1 overflow-hidden rounded-full">
          <span
            className="bg-rzp-blue/60 block h-full rounded-full transition-[width] duration-200"
            style={{ width: `${Math.min(Math.max(widthPct, 0), 100)}%` }}
          />
        </span>
      </div>
      <span
        className={"fc-numeric shrink-0 text-sm " + (bold ? "text-paper-100 font-semibold" : "text-paper-300")}
      >
        {formatPaise(amountPaise)}
      </span>
    </div>
  );
}
