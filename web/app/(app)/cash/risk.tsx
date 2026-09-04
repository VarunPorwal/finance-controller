"use client";

// Money that is held, reserved, at risk of expiring, or arrived unclaimed.
// Amounts are the bridge's own; the only date arithmetic is "days until".

import Link from "next/link";
import { ArrowRight, Clock } from "lucide-react";
import { formatDateLong, money, plural, relativeDays } from "../_lib/format";
import { StatusDot } from "../_components/fc-ui";
import type { CashBridge } from "../_lib/api";

export function HeldAndAtRisk({ bridge, asOf }: { bridge: CashBridge; asOf: string }) {
  const risk = bridge.at_risk;
  return (
    <div className="fc-card h-full">
      <div className="fc-card-title mb-1">Held and at risk</div>
      <div className="fc-faint mb-3" style={{ fontSize: 12 }}>
        Money Razorpay is holding, and money that expires on a date.
      </div>

      <div className="fc-row4" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div>
          <div className="fc-label">On hold at Razorpay</div>
          <div className="fc-metric-val fc-num font-mono mt-1" style={{ color: bridge.held_paise > 0 ? "var(--fc-warn)" : undefined }}>
            {money(bridge.held_paise, { whole: true })}
          </div>
          <div className="fc-label mt-1">
            {bridge.held_paise > 0 ? plural(bridge.held_event_ids.length, "settlement held") : "nothing on hold"}
          </div>
        </div>
        <div>
          <div className="fc-label">Rolling reserve</div>
          <div className="fc-metric-val fc-num font-mono mt-1" style={{ color: bridge.reserve_pending_release_paise === 0 ? "var(--fc-text-3)" : undefined }}>
            {money(bridge.reserve_pending_release_paise, { whole: true })}
          </div>
          <div className="fc-label mt-1">
            {bridge.reserve_pending_release_paise > 0 ? "pending release" : "No rolling reserve pending"}
          </div>
        </div>
      </div>

      <div style={{ borderTop: "1px solid var(--fc-divider)", margin: "16px 0 0" }} />

      {risk.amount_paise > 0 ? (
        <div className="mt-4 flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Clock size={13} color="var(--fc-warn)" />
              <span className="fc-label" style={{ color: "var(--fc-warn)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Expires
              </span>
            </div>
            <div className="fc-hero-num fc-num font-mono mt-1.5" style={{ color: "var(--fc-warn)" }}>
              {money(risk.amount_paise)}
            </div>
            <div className="fc-muted mt-1.5" style={{ fontSize: 12 }}>
              {plural(risk.item_count, "item")} can still be lost.
              {risk.earliest_deadline && (
                <>
                  {" "}
                  The first window closes on {formatDateLong(risk.earliest_deadline)}
                  <span className="ml-2 inline-flex">
                    <StatusDot tone="warn">{relativeDays(risk.earliest_deadline, asOf)}</StatusDot>
                  </span>
                </>
              )}
            </div>
          </div>
          <Link
            href={risk.exception_ids[0] ? `/decisions?open=${risk.exception_ids[0]}` : "/decisions"}
            className="fc-btn shrink-0 inline-flex items-center gap-1.5"
          >
            Act on it <ArrowRight size={13} />
          </Link>
        </div>
      ) : (
        <div className="mt-4">
          <StatusDot tone="ok">Nothing at risk of expiring.</StatusDot>
        </div>
      )}
    </div>
  );
}

/** Unidentified inflows and recoverable amounts, side by side in one card.
 * Recoverable is a single GST-input-credit line with nothing else this run
 * computes (TDS 194-O and TCS totals are omitted, not derived) — rather than
 * render a second card with a mostly-empty bottom half, both live here. */
export function UnidentifiedAndRecoverable({ bridge }: { bridge: CashBridge }) {
  const n = bridge.unidentified_inflow_exception_ids.length;
  const first = bridge.unidentified_inflow_exception_ids[0];
  const gst = bridge.gst_input_credit_claimable_paise;
  return (
    <div className="fc-card">
      <div className="grid gap-6" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <div>
          <div className="fc-card-title mb-1">Unidentified inflows</div>
          <div className="fc-faint mb-2" style={{ fontSize: 12 }}>
            Money that arrived in the bank and nothing claims.
          </div>
          {bridge.unidentified_inflow_paise > 0 ? (
            <>
              <div className="fc-hero-num fc-num font-mono" style={{ color: "var(--fc-accent)" }}>
                {money(bridge.unidentified_inflow_paise)}
              </div>
              <div className="fc-muted mt-2" style={{ fontSize: 12 }}>
                {plural(n, "credit")} in the account with no settlement and no voucher. Money in the account, not
                exposure. Someone knows what it is.
              </div>
              <Link
                href={first ? `/decisions?open=${first}` : "/decisions"}
                className="fc-link mt-3 inline-flex items-center gap-1"
              >
                Identify {money(bridge.unidentified_inflow_paise, { compact: true, whole: true })} <ArrowRight size={12} />
              </Link>
            </>
          ) : (
            <StatusDot tone="ok">Every credit on the statement is claimed by a settlement or a voucher.</StatusDot>
          )}
        </div>
        <div style={{ borderLeft: "1px solid var(--fc-divider)", paddingLeft: 24 }}>
          <div className="fc-card-title mb-1">Recoverable</div>
          <div className="fc-faint mb-3" style={{ fontSize: 12 }}>
            What this run says can be claimed back.
          </div>
          <div className="fc-kv fc-kv--total" style={{ borderTop: 0, paddingTop: 0 }}>
            <span>GST input credit</span>
            <span className="fc-num font-mono" style={{ color: gst > 0 ? "var(--fc-ok)" : "var(--fc-text)" }}>
              {money(gst)}
            </span>
          </div>
          <div className="fc-faint mt-2" style={{ fontSize: 11.5 }}>
            Matchable in GSTR-2B. TDS 194-O and TCS recoverable totals are not computed by this run.
          </div>
        </div>
      </div>
    </div>
  );
}
