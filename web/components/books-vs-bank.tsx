"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Landmark } from "lucide-react";
import { apiClient } from "@/lib/client";
import { formatPaiseWhole } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";

/**
 * The headline an accountant reads first: the bank reconciliation statement.
 *
 * Books movement against bank movement, the difference between them, and what
 * the still-open items add up to under the three reasons a difference is ever
 * legitimate: timing, unrecorded in books, under investigation. Those three are
 * sums of open items, not a decomposition of the difference, and the server
 * does not pretend otherwise — see `BooksVsBank` in `fc/cash/bridge.py`. The
 * unexplained line is the gateway bridge's own residual, which balances by
 * construction. Beside it, the only figure here that is a countdown: money that
 * can still be *lost*, with the day it expires.
 *
 * Underneath, the lane strip. A bank account carries gateway settlements,
 * marketplace payouts, POS terminal credits, payroll and rent, and each lane
 * reconciles against a different counterpart; a lane whose two sides agree is
 * finished whatever the others look like. Every figure is `*_paise` off
 * `GET /cash/bridge` — nothing is derived client-side.
 */

const LANE_LABEL: Record<string, string> = {
  gateway: "Gateway",
  marketplace: "Marketplace",
  pos: "POS",
  operating: "Operating",
  other: "Other",
};

const LANE_NOTE: Record<string, string> = {
  gateway: "bank · gateway · books",
  marketplace: "bank · books",
  pos: "bank · books",
  operating: "bank · books",
  other: "bank · books, or unidentified",
};

export function BooksVsBank({ runId }: { runId: string }) {
  const { data: bridge, error: queryError } = useQuery({
    queryKey: queryKeys.cashBridge(runId),
    queryFn: async () => {
      const { data, error } = await apiClient.GET("/api/v1/cash/bridge", {
        params: { query: { run_id: runId } },
      });
      if (error || !data) throw new Error("could not load the reconciliation");
      return data;
    },
  });

  if (queryError) {
    return (
      <div className="fc-card text-amber-text p-4 text-sm">
        Could not load the reconciliation.
      </div>
    );
  }
  if (!bridge) return <div className="fc-card h-[168px] animate-pulse" aria-hidden />;

  const b = bridge.books_vs_bank;
  const risk = bridge.at_risk;
  const composition = [
    { label: "Timing", paise: b.timing_paise, note: "not landed yet" },
    {
      label: "Unrecorded in books",
      paise: b.unrecorded_in_books_paise,
      note: "the entry does not exist",
    },
    {
      label: "Under investigation",
      paise: b.under_investigation_paise,
      note: "still being worked out",
    },
  ];

  const deadline = risk.earliest_deadline;
  const riskLine =
    risk.item_count === 0
      ? "Nothing at risk of being lost"
      : `At risk of being lost — ${risk.item_count} item${risk.item_count === 1 ? "" : "s"}` +
        (deadline ? `, earliest deadline ${deadline}` : "");

  return (
    <div className="mb-5 grid grid-cols-[1.65fr_1fr] gap-5">
      <div className="fc-card p-[22px]">
        <div className="mb-3 flex items-center gap-2">
          <Landmark width={15} height={15} className="text-text-muted" />
          <h2 className="text-sm font-semibold">Books vs bank</h2>
        </div>

        <div className="mb-4 flex items-end gap-8">
          <Figure label="Per the books" paise={b.books_movement_paise} />
          <Figure label="Per the bank" paise={b.bank_movement_paise} />
          <Figure label="Difference" paise={b.difference_paise} emphasis />
        </div>

        <div className="text-text-muted border-border border-t pt-3 text-[11px]">
          Still open, by what to do about it
        </div>
        <ul className="mt-1.5 flex flex-col gap-1.5">
          {composition.map((row) => (
            <li key={row.label} className="flex items-baseline justify-between text-[12.5px]">
              <span className="text-text-body">
                {row.label}
                <span className="text-text-muted ml-2 text-[11px]">{row.note}</span>
              </span>
              <span className="font-mono tabular-nums">{formatPaiseWhole(row.paise)}</span>
            </li>
          ))}
          <li className="border-border mt-1 flex items-baseline justify-between border-t pt-2 text-[12.5px] font-semibold">
            <span>
              Unexplained
              <span className="text-text-muted ml-2 text-[11px] font-normal">
                gateway bridge residual
              </span>
            </span>
            <span className="font-mono tabular-nums">
              {formatPaiseWhole(b.unexplained_paise)}
            </span>
          </li>
        </ul>
      </div>

      <div className="flex flex-col gap-5">
        <div className="fc-card p-[22px]">
          <div className="mb-2 flex items-center gap-2">
            <AlertTriangle width={15} height={15} className="text-amber-text" />
            <h2 className="text-sm font-semibold">Cash at risk</h2>
          </div>
          <div className="font-mono text-2xl font-semibold tabular-nums">
            {formatPaiseWhole(risk.amount_paise)}
          </div>
          <p className="text-text-muted mt-1 text-[12px]">{riskLine}</p>
          {bridge.unidentified_inflow_paise !== 0 && (
            <p className="text-text-muted border-border mt-3 border-t pt-2 text-[11.5px]">
              Separately, {formatPaiseWhole(bridge.unidentified_inflow_paise)} of unidentified
              inflows are sitting in the account — money arrived, not money exposed.
            </p>
          )}
        </div>

        <div className="fc-card p-[22px]">
          <h2 className="mb-2.5 text-sm font-semibold">Lanes</h2>
          <ul className="flex flex-col gap-1.5">
            {bridge.lanes.map((lane) => (
              <li key={lane.lane} className="flex items-baseline justify-between text-[12.5px]">
                <span className="text-text-body">
                  {LANE_LABEL[lane.lane] ?? lane.lane}
                  <span className="text-text-muted ml-2 text-[11px]">
                    {LANE_NOTE[lane.lane] ?? ""}
                  </span>
                </span>
                <span
                  className={
                    lane.exception_count === 0
                      ? "text-text-muted text-[11.5px]"
                      : "text-amber-text font-mono text-[11.5px] tabular-nums"
                  }
                >
                  {lane.exception_count === 0
                    ? "clear"
                    : `${lane.exception_count} open · ${formatPaiseWhole(lane.unreconciled_paise)}`}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function Figure({
  label,
  paise,
  emphasis,
}: {
  label: string;
  paise: number;
  emphasis?: boolean;
}) {
  return (
    <div>
      <div className="text-text-muted text-[11.5px]">{label}</div>
      <div
        className={
          emphasis
            ? "font-mono text-xl font-semibold tabular-nums"
            : "font-mono text-lg tabular-nums"
        }
      >
        {formatPaiseWhole(paise)}
      </div>
    </div>
  );
}
