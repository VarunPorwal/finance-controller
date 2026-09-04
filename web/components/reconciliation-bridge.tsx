"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/client";
import { formatPaise, formatPaiseWhole } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The signature element: the bridge a finance person draws by hand when
 * explaining a settlement. Gross collected, each deduction taken off it,
 * the expected net, what the bank actually credited, and the gap between
 * them. Every figure is `*_paise` off `GET /cash/bridge`. Bar widths are
 * proportions of gross for the eye only; no figure is derived here.
 *
 * Hover a line: the events it attributes to highlight in the queue below.
 * Click the gap: the queue filters to exactly its exceptions.
 */
export function ReconciliationBridge({
  runId,
  onHoverSegment,
  onSelectGap,
  compact,
}: {
  runId: string;
  onHoverSegment?: (eventIds: string[] | null) => void;
  onSelectGap?: (exceptionIds: string[] | null) => void;
  compact?: boolean;
}) {
  const [gapSelected, setGapSelected] = useState(false);
  // Bars grow from zero once the data is on screen, top to bottom, 40ms
  // apart: the ledger reconciling itself in front of you.
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(t);
  }, []);
  const { data: bridge, error } = useQuery({
    queryKey: queryKeys.cashBridge(runId),
    queryFn: async () => {
      const { data, error: fetchError } = await apiClient.GET("/api/v1/cash/bridge", { params: { query: { run_id: runId } } });
      if (fetchError || !data) throw new Error("could not load the cash bridge");
      return data;
    },
  });

  if (error) return <div className="panel p-4 text-[12.5px] text-warn">Could not load the cash bridge.</div>;
  if (!bridge) return <Skeleton className="h-[260px]" />;

  const gross = Math.max(Math.abs(bridge.gross_collected_paise), 1);
  const pct = (paise: number) => `${Math.min(100, Math.max(0, (Math.abs(paise) / gross) * 100)).toFixed(2)}%`;
  const gapNonZero = bridge.unexplained_paise !== 0;
  const unexplainedSegment = bridge.segments.find((s) => s.label === "Unexplained");
  const hover = (ids: string[] | null) => onHoverSegment?.(ids);

  return (
    <div className={cn("panel overflow-hidden", compact ? "" : "")}>
      <div className="flex items-center justify-between border-b border-line px-[18px] py-3.5">
        <div>
          <div className="text-[13px] font-semibold">Reconciliation bridge</div>
          {!compact && <div className="mt-0.5 text-[11.5px] text-ink-3">Gross to bank, line by line. Hover a line to see its rows; click the gap to see its exceptions.</div>}
        </div>
        <span
          className={cn(
            "num rounded-[6px] border px-2 py-1 text-[11px] font-semibold",
            gapNonZero ? "border-[rgba(245,165,36,0.3)] bg-warn-soft text-warn" : "border-[rgba(61,220,151,0.3)] bg-ok-soft text-ok",
          )}
        >
          {gapNonZero ? `${formatPaise(bridge.unexplained_paise)} unexplained` : "balances to the paise"}
        </span>
      </div>

      <div className="px-[18px] py-3">
        <Line index={0} grown={grown}
          label="Gross collected"
          amount={formatPaise(bridge.gross_collected_paise)}
          width="100%"
          color="var(--src-razorpay)"
          strong
          onEnter={() => hover(bridge.gross_event_ids)}
          onLeave={() => hover(null)}
        />
        {bridge.deductions.map((d, i) => (
          <Line index={1 + i} grown={grown}
            key={i}
            label={d.label}
            prefix="−"
            amount={formatPaise(d.amount_paise)}
            sub={d.attributed_paise !== d.amount_paise ? `${formatPaiseWhole(d.attributed_paise)} attributed` : undefined}
            width={pct(d.amount_paise)}
            color="var(--ink-4)"
            indent
            onEnter={() => hover(d.event_ids)}
            onLeave={() => hover(null)}
          />
        ))}
        <Line index={1 + bridge.deductions.length} grown={grown}
          label="Expected net"
          amount={formatPaise(bridge.expected_net_paise)}
          width={pct(bridge.expected_net_paise)}
          color="var(--accent-strong)"
          strong
          divider
        />
        <Line index={2 + bridge.deductions.length} grown={grown}
          label="Credited to bank"
          amount={formatPaise(bridge.actual_bank_paise)}
          width={pct(bridge.actual_bank_paise)}
          color="var(--ok)"
          strong
          onEnter={() => hover(bridge.actual_bank_event_ids)}
          onLeave={() => hover(null)}
        />
        {bridge.held_paise !== 0 && (
          <Line index={3 + bridge.deductions.length} grown={grown}
            label="Held by gateway"
            amount={formatPaise(bridge.held_paise)}
            width={pct(bridge.held_paise)}
            color="var(--warn)"
            indent
            onEnter={() => hover(bridge.held_event_ids)}
            onLeave={() => hover(null)}
          />
        )}
        <button
          type="button"
          disabled={!gapNonZero || !onSelectGap}
          aria-pressed={gapSelected}
          onClick={() => {
            const next = !gapSelected;
            setGapSelected(next);
            onSelectGap?.(next ? (unexplainedSegment?.exception_ids ?? []) : null);
          }}
          className={cn(
            "mt-2 flex w-full items-center gap-3 rounded-[8px] border px-3 py-2.5 text-left transition-colors",
            gapNonZero
              ? gapSelected
                ? "border-[rgba(245,165,36,0.5)] bg-warn-soft"
                : "border-line-strong bg-bg hover:border-[rgba(245,165,36,0.4)]"
              : "border-line bg-bg",
            !onSelectGap && "cursor-default",
          )}
        >
          <span className={cn("label", gapNonZero ? "text-warn" : "text-ok")}>Unexplained</span>
          <span className="flex-1 text-[11.5px] text-ink-3">
            {gapNonZero
              ? `${unexplainedSegment?.exception_ids.length ?? 0} exceptions carry this gap${onSelectGap ? " · click to filter the queue" : ""}`
              : "the books and the bank agree"}
          </span>
          <span className={cn("num text-[22px] leading-none font-semibold", gapNonZero ? "text-warn" : "text-ok")}>
            {formatPaise(bridge.unexplained_paise)}
          </span>
        </button>
      </div>
    </div>
  );
}

function Line({
  label,
  amount,
  prefix,
  sub,
  width,
  color,
  strong,
  indent,
  divider,
  onEnter,
  onLeave,
  index,
  grown,
}: {
  index: number;
  grown: boolean;
  label: string;
  amount: string;
  prefix?: string;
  sub?: string;
  width: string;
  color: string;
  strong?: boolean;
  indent?: boolean;
  divider?: boolean;
  onEnter?: () => void;
  onLeave?: () => void;
}) {
  return (
    <div
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      className={cn(
        "group grid grid-cols-[200px_1fr_auto] items-center gap-3 rounded-[6px] px-2 py-[7px] transition-colors hover:bg-surface-2",
        divider && "mt-1 border-t border-dashed border-line-strong pt-[9px]",
      )}
    >
      <div className={cn("flex items-center gap-2 truncate text-[12.5px]", indent && "pl-4", strong ? "font-medium text-ink" : "text-ink-2")}>
        {indent && <span className="text-ink-4">└</span>}
        <span className="truncate">{label}</span>
      </div>
      <div className="relative h-[10px] overflow-hidden rounded-[3px] bg-surface-3">
        <div
          className="bar-fill absolute inset-y-0 left-0 w-full rounded-[3px]"
          style={{ transform: `scaleX(${grown ? parseFloat(width) / 100 : 0})`, background: color, transitionDelay: `${index * 40}ms` }}
        />
      </div>
      <div className="text-right">
        <div className={cn("num text-[15px] whitespace-nowrap", strong ? "font-semibold text-ink" : "text-ink-2")}>
          {prefix && <span className="text-ink-3">{prefix}</span>}
          {amount}
        </div>
        {sub && <div className="num text-[10.5px] text-ink-3">{sub}</div>}
      </div>
    </div>
  );
}
