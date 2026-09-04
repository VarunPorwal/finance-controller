"use client";

// Fees and deductions in a controller's words: what Razorpay charged, what
// can be claimed back, what to match against Form 26AS, and which marketplace
// commissions the Rulebook explained. The effective rate is a display ratio
// of two server figures; nothing here computes a fee.

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { money, pct, plural, sumPaise } from "../_lib/format";
import { Identifier } from "../_components/fc-ui";
import type { CashBridge, Exception } from "../_lib/api";

function find(bridge: CashBridge, prefix: string) {
  const p = prefix.toLowerCase();
  return bridge.deductions.find((d) => d.label.toLowerCase().startsWith(p)) ?? null;
}

function Row({
  label,
  amount,
  gross,
  note,
  noteTone,
}: {
  label: string;
  amount: number | null;
  gross: number;
  note: React.ReactNode;
  noteTone?: "ok" | "neutral";
}) {
  const rate = amount !== null && gross > 0 ? amount / gross : null;
  return (
    <div className="fc-lrow" style={{ display: "grid", gridTemplateColumns: "1fr auto auto", alignItems: "baseline", columnGap: 24 }}>
      <div className="min-w-0">
        <div style={{ fontSize: 13 }}>{label}</div>
        <div className="mt-0.5" style={{ fontSize: 11.5, color: noteTone === "ok" ? "var(--fc-ok)" : "var(--fc-text-3)" }}>
          {note}
        </div>
      </div>
      <div className="text-right">
        <div className="fc-faint" style={{ fontSize: 10.5, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          rate on gross
        </div>
        <div className="fc-num font-mono" style={{ fontSize: 12.5 }}>
          {rate === null ? "—" : pct(rate, 2)}
        </div>
      </div>
      <div className="text-right fc-num font-mono" style={{ fontSize: 13 }}>
        {amount === null ? <span className="fc-faint">not in this run</span> : money(amount)}
      </div>
    </div>
  );
}

export function Fees({ bridge, exceptions }: { bridge: CashBridge; exceptions: Exception[] }) {
  const router = useRouter();
  const gross = bridge.gross_collected_paise;
  const mdr = find(bridge, "mdr");
  const gst = find(bridge, "gst");
  const tds = find(bridge, "tds");

  const commissions = useMemo(() => {
    const byRule = new Map<string, { ruleId: string; version: number; paise: number; count: number }>();
    for (const x of exceptions) {
      if (x.status === "superseded") continue;
      for (const r of x.rules_applied ?? []) {
        const cur = byRule.get(r.rule_id);
        if (cur) {
          cur.paise += r.explained_paise;
          cur.count++;
          if (r.version > cur.version) cur.version = r.version;
        } else byRule.set(r.rule_id, { ruleId: r.rule_id, version: r.version, paise: r.explained_paise, count: 1 });
      }
    }
    return [...byRule.values()].sort((a, b) => b.paise - a.paise);
  }, [exceptions]);

  return (
    <div className="fc-card h-full">
      <div className="fc-card-title mb-1">Fees and deductions</div>
      <div className="fc-faint mb-2" style={{ fontSize: 12 }}>
        What left the gross before it reached the bank, and what comes back.
      </div>
      <div>
        <Row label="MDR" amount={mdr?.amount_paise ?? null} gross={gross} note="What Razorpay charged to process the payments." />
        <Row
          label="GST on MDR"
          amount={gst?.amount_paise ?? null}
          gross={gross}
          note={
            bridge.gst_input_credit_claimable_paise > 0
              ? `Claimable as input credit: ${money(bridge.gst_input_credit_claimable_paise)}`
              : "Nothing claimable as input credit in this run."
          }
          noteTone={bridge.gst_input_credit_claimable_paise > 0 ? "ok" : "neutral"}
        />
        <Row label="TDS 194-O" amount={tds?.amount_paise ?? null} gross={gross} note="Match against Form 26AS before claiming the credit." />
      </div>

      <div style={{ borderTop: "1px solid var(--fc-divider)", margin: "14px 0" }} />

      <div className="fc-label mb-2" style={{ textTransform: "uppercase", letterSpacing: "0.04em" }}>
        Marketplace commissions
      </div>
      {commissions.length === 0 ? (
        <p className="fc-faint" style={{ fontSize: 12.5 }}>
          No Rulebook rule explained a commission in this run.
        </p>
      ) : (
        <div className="flex flex-col">
          {commissions.map((c) => (
            <div
              key={c.ruleId}
              role="button"
              tabIndex={0}
              onClick={() => router.push(`/rules/${c.ruleId}`)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") router.push(`/rules/${c.ruleId}`);
              }}
              className="fc-card-hover flex cursor-pointer items-center justify-between gap-4 py-2"
              style={{ fontSize: 12.5, borderBottom: "1px solid var(--fc-divider)" }}
            >
              <span className="min-w-0 inline-flex items-baseline gap-1.5">
                <Identifier value={c.ruleId} /> <span className="fc-faint">v{c.version}</span>
                <span className="fc-faint"> · explained </span>
                <span className="fc-num font-mono">{money(c.paise)}</span>
                <span className="fc-faint"> across {plural(c.count, "settlement")}</span>
              </span>
              <ArrowRight size={12} className="fc-faint shrink-0" />
            </div>
          ))}
          <div className="mt-2 flex items-baseline justify-between" style={{ fontSize: 12 }}>
            <span className="fc-muted">Explained by rules, in total</span>
            <span className="fc-num font-mono fc-strong">{money(sumPaise(commissions.map((c) => c.paise)))}</span>
          </div>
        </div>
      )}
    </div>
  );
}
