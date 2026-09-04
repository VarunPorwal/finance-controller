"use client";

// Where money is stuck: by lane (the rail it moved on) and by what a person
// has to do about it. Lane bars are unreconciled as a share of what the
// ledger booked on that lane; the buckets are integer subtotals of open
// exceptions by action group.

import { useMemo } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { money, plural, sumPaise } from "../_lib/format";
import { ACTION_GROUP, type ActionGroup } from "../_lib/labels";
import { StatusDot } from "../_components/fc-ui";
import type { CashBridge, Exception } from "../_lib/api";

const OPEN = new Set<Exception["status"]>(["open", "escalated", "monitoring", "snoozed"]);

const BUCKETS: { key: string; label: string; groups: ActionGroup[]; tone: "ok" | "bad" | "warn" | "neutral" }[] = [
  { key: "waiting", label: "Waiting on timing", groups: ["waiting"], tone: "ok" },
  { key: "decide", label: "Needs a decision", groups: ["act_today", "cannot_resolve"], tone: "bad" },
  { key: "books", label: "Fix the books", groups: ["books_fix"], tone: "warn" },
  { key: "identify", label: "Identify", groups: ["unidentified_inflow"], tone: "neutral" },
];

const toneColor: Record<"ok" | "bad" | "warn" | "neutral", string> = {
  ok: "var(--fc-ok)",
  bad: "var(--fc-bad)",
  warn: "var(--fc-warn)",
  neutral: "var(--fc-text)",
};

function laneName(lane: string): string {
  const l = lane.toLowerCase();
  if (l === "unknown" || l === "other") return "Other";
  return lane.toUpperCase();
}

export function Lanes({ bridge }: { bridge: CashBridge }) {
  const reduced = useReducedMotion();
  const lanes = useMemo(
    () => [...bridge.lanes].sort((a, b) => b.unreconciled_paise - a.unreconciled_paise || b.bank_in_paise - a.bank_in_paise),
    [bridge.lanes],
  );
  return (
    <div className="fc-card h-full">
      <div className="fc-card-title mb-1">By lane</div>
      <div className="fc-faint mb-3" style={{ fontSize: 12 }}>
        Unreconciled as a share of what the ledger booked on each rail.
      </div>
      {lanes.length === 0 ? (
        <div className="fc-body py-6 text-center">No lanes in this run.</div>
      ) : (
        <div className="grid gap-y-3" style={{ gridTemplateColumns: "64px 1fr auto auto", alignItems: "center", columnGap: 16 }}>
          {lanes.map((l, i) => {
            const base = l.ledger_paise > 0 ? l.ledger_paise : l.bank_in_paise;
            const frac = base > 0 ? Math.min(1, l.unreconciled_paise / base) : l.unreconciled_paise > 0 ? 1 : 0;
            const hot = l.unreconciled_paise > 0;
            return (
              <div key={l.lane} className="contents">
                <div className="fc-num" style={{ fontSize: 12 }}>
                  {laneName(l.lane)}
                </div>
                <div className="fc-bar" style={{ margin: 0 }}>
                  <motion.span
                    style={{ background: hot ? "var(--fc-warn)" : "var(--fc-ok)", transformOrigin: "left" }}
                    initial={reduced ? false : { scaleX: 0 }}
                    animate={{ scaleX: Math.max(frac, hot ? 0.02 : 0) }}
                    transition={{ type: "spring", stiffness: 300, damping: 34, delay: i * 0.05 }}
                  />
                </div>
                <div className="text-right">
                  <div className="fc-num font-mono" style={{ fontSize: 12, color: hot ? "var(--fc-warn)" : "var(--fc-ok)" }}>
                    {money(l.unreconciled_paise)}
                  </div>
                  <div className="fc-faint" style={{ fontSize: 10.5 }}>
                    unreconciled
                  </div>
                </div>
                <div className="fc-faint text-right" style={{ width: 128, fontSize: 11 }}>
                  <div className="fc-num font-mono">
                    in <span style={{ color: "var(--fc-accent)" }}>{money(l.bank_in_paise)}</span>
                  </div>
                  <div>{l.exception_count ? plural(l.exception_count, "decision") : "clean"}</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function Buckets({ exceptions }: { exceptions: Exception[] }) {
  const rows = useMemo(() => {
    const open = exceptions.filter((x) => OPEN.has(x.status));
    return BUCKETS.map((b) => {
      const list = open.filter((x) => b.groups.includes(x.action_group));
      return { ...b, count: list.length, paise: sumPaise(list.map((x) => x.amount_paise)) };
    });
  }, [exceptions]);
  const total = sumPaise(rows.map((r) => r.paise));

  return (
    <div className="fc-card h-full">
      <div className="fc-card-title mb-1">
        By what it needs
        <span className="fc-num font-mono" style={{ fontSize: 13, color: total > 0 ? "var(--fc-warn)" : "var(--fc-ok)" }}>
          {money(total)}
        </span>
      </div>
      <div className="fc-faint mb-3" style={{ fontSize: 12 }}>
        Open decisions, grouped by the action that frees the money.
      </div>
      {total === 0 && rows.every((r) => r.count === 0) ? (
        <StatusDot tone="ok">Nothing is stuck. Every rupee that moved is explained.</StatusDot>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {rows.map((r) => (
            <Link
              key={r.key}
              href="/decisions"
              className="flex flex-col gap-1 px-4 py-3"
              style={{ background: "var(--fc-hover)", border: "1px solid var(--fc-divider)", borderRadius: "var(--fc-r-sm)" }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="fc-label" style={{ textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  {r.label}
                </span>
                <ArrowRight size={12} className="fc-faint" />
              </div>
              <span className="fc-metric-val fc-num font-mono" style={{ color: r.count ? toneColor[r.tone] : "var(--fc-text-3)" }}>
                {money(r.paise, { whole: true })}
              </span>
              <span className="fc-faint" style={{ fontSize: 11.5 }}>
                {r.count === 0 ? "none open" : plural(r.count, "decision")}
                {r.count > 0 && <> · {r.groups.map((g) => ACTION_GROUP[g].blurb).join(" ")}</>}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
