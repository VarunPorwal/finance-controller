"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/lib/client";
import { formatPaise, formatPaiseWhole } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * The bank reconciliation statement an accountant reads first: books against
 * bank, the difference, and what the still-open items add up to under the
 * reasons a difference is ever legitimate. Every figure is `*_paise` off
 * `GET /cash/bridge`; nothing is derived client-side.
 */

const LANE_LABEL: Record<string, string> = {
  gateway: "Gateway",
  marketplace: "Marketplace",
  pos: "POS",
  operating: "Operating",
  other: "Other",
};

const LANE_NOTE: Record<string, string> = {
  gateway: "bank against gateway and books",
  marketplace: "bank against books",
  pos: "bank against books",
  operating: "bank against books",
  other: "bank against books, or unidentified",
};

export function BooksVsBank({ runId }: { runId: string }) {
  const { data: bridge, error } = useQuery({
    queryKey: queryKeys.cashBridge(runId),
    queryFn: async () => {
      const { data, error: e } = await apiClient.GET("/api/v1/cash/bridge", { params: { query: { run_id: runId } } });
      if (e || !data) throw new Error("could not load the reconciliation");
      return data;
    },
  });

  if (error) return <div className="panel p-4 text-[12.5px] text-warn">Could not load the reconciliation statement.</div>;
  if (!bridge) return <Skeleton className="h-[240px]" />;

  const b = bridge.books_vs_bank;
  const risk = bridge.at_risk;
  const composition = [
    { label: "Timing", paise: b.timing_paise, note: "not landed yet" },
    { label: "Unrecorded in books", paise: b.unrecorded_in_books_paise, note: "the entry does not exist" },
    { label: "Under investigation", paise: b.under_investigation_paise, note: "still being worked out" },
    { label: "Unidentified inflows", paise: b.unidentified_inflow_paise, note: "arrived, unattributed" },
    { label: "Reconciled", paise: b.matched_residual_paise, note: "rounding inside matched groups" },
  ];
  const deadline = risk.earliest_deadline;

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.6fr_1fr]">
      <Panel title="Books vs bank" sub={`Opening balance ${formatPaiseWhole(b.opening_balance_paise)}`}>
        <div className="grid grid-cols-3 gap-4 border-b border-line pb-4">
          <Figure label="Per the books" paise={b.books_balance_paise} />
          <Figure label="Per the bank" paise={b.bank_balance_paise} />
          <Figure label="Difference" paise={b.difference_paise} emphasis />
        </div>
        <p className="mt-3 text-[11px] text-ink-3">
          What makes up the difference, signed so these sum to it exactly. A negative line pushes the books below the bank.
        </p>
        <ul className="mt-2 flex flex-col">
          {composition.map((row) => (
            <li key={row.label} className="flex items-baseline justify-between border-b border-line py-2 text-[12.5px] last:border-0">
              <span className="text-ink-2">
                {row.label}
                <span className="ml-2 text-[11px] text-ink-3">{row.note}</span>
              </span>
              <span className={cn("num text-[15px]", row.paise === 0 ? "text-ink-4" : "text-ink")}>{formatPaise(row.paise)}</span>
            </li>
          ))}
          <li className="mt-1 flex items-baseline justify-between border-t border-line-strong pt-2.5 text-[12.5px] font-semibold">
            <span>
              Unexplained
              <span className="ml-2 text-[11px] font-normal text-ink-3">gateway bridge residual</span>
            </span>
            <span className={cn("num text-[15px]", b.unexplained_paise === 0 ? "text-ok" : "text-warn")}>{formatPaise(b.unexplained_paise)}</span>
          </li>
        </ul>
      </Panel>

      <div className="flex flex-col gap-5">
        <Panel title="Cash at risk" sub="Money that can still be lost">
          <div className={cn("num text-[28px] leading-none font-semibold", risk.item_count === 0 ? "text-ok" : "text-bad")}>
            {formatPaise(risk.amount_paise)}
          </div>
          <p className="mt-2 text-[11.5px] text-ink-3">
            {risk.item_count === 0
              ? "Nothing at risk of being lost."
              : `${risk.item_count} item${risk.item_count === 1 ? "" : "s"}${deadline ? ` · earliest deadline ${deadline}` : ""}`}
          </p>
          {bridge.unidentified_inflow_paise !== 0 && (
            <p className="mt-3 border-t border-line pt-2.5 text-[11.5px] text-ink-3">
              Separately, <span className="num text-ink-2">{formatPaiseWhole(bridge.unidentified_inflow_paise)}</span> of unidentified
              inflows sit in the account. Money arrived, not money exposed.
            </p>
          )}
        </Panel>

        <Panel title="Lanes" sub="Each lane reconciles against its own counterpart">
          <ul className="flex flex-col">
            {bridge.lanes.map((lane) => (
              <li key={lane.lane} className="flex items-baseline justify-between border-b border-line py-2 text-[12.5px] last:border-0">
                <span className="text-ink-2">
                  {LANE_LABEL[lane.lane] ?? lane.lane}
                  <span className="ml-2 text-[11px] text-ink-3">{LANE_NOTE[lane.lane] ?? ""}</span>
                </span>
                {lane.exception_count === 0 ? (
                  <span className="text-[11px] font-semibold tracking-[0.06em] text-ok uppercase">clear</span>
                ) : (
                  <span className="num text-[11.5px] text-warn">
                    {lane.exception_count} open · {formatPaiseWhole(lane.unreconciled_paise)}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}

function Figure({ label, paise, emphasis }: { label: string; paise: number; emphasis?: boolean }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className={cn("num mt-1.5 whitespace-nowrap", emphasis ? "text-[22px] font-semibold" : "text-[22px] text-ink-2")}>
        {formatPaiseWhole(paise)}
      </div>
    </div>
  );
}
