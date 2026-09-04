"use client";

// Three ratios, never blended into one number. Each answers a different
// question: did the bank statement get read, did the day book get read, did
// every settlement get traced to something. Stacked vertically, ring beside
// its own label, so the card reads as a list rather than three wide columns.

import { motion } from "framer-motion";
import { FcCard, FcCardHeader, WhyLabel, WhyWrap } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";
import { plural } from "../_lib/format";
import type { Register } from "../settlements/register";
import type { TransactionEvent } from "../_lib/api";

/** Complete reads ok green; short of 100% earns amber — the eye goes to
 * what's actually still open, but a full ratio still reads as a result. */
function Ratio({ label, hint, count, total, href }: { label: string; hint: string; count: number; total: number; href: string }) {
  const fraction = total ? count / total : 0;
  const pct = Math.round(fraction * 100);
  const complete = total > 0 && count >= total;
  const color = complete ? "var(--fc-ok)" : "var(--fc-warn)";
  return (
    <div className="flex flex-1 items-center gap-6">
      <div className="relative shrink-0" style={{ width: 108, height: 108 }}>
        <svg viewBox="0 0 108 108" width={108} height={108}>
          <circle cx={54} cy={54} r={46} fill="none" stroke="var(--fc-divider)" strokeWidth={9} />
          <motion.circle
            cx={54}
            cy={54}
            r={46}
            fill="none"
            stroke={color}
            strokeWidth={9}
            strokeDasharray={289}
            strokeLinecap="round"
            transform="rotate(-90 54 54)"
            initial={{ strokeDashoffset: 289 }}
            animate={{ strokeDashoffset: 289 * (1 - fraction) }}
            transition={{ duration: 0.8, ease: [0.23, 1, 0.32, 1] }}
          />
        </svg>
        <span className="fc-num absolute inset-0 flex items-center justify-center" style={{ fontSize: 22, fontWeight: 600, color }}>
          <CountUp value={pct} format={(n) => `${Math.round(n)}%`} />
        </span>
      </div>
      <div className="min-w-0">
        <div className="fc-label" style={{ fontSize: 13 }}>{label}</div>
        <WhyWrap className="mt-1.5">
          <span className="fc-num fc-why-figure fc-strong" style={{ fontSize: 19 }}>
            <CountUp value={count} /> of {total}
          </span>
          <WhyLabel href={href} />
        </WhyWrap>
        <div className="fc-faint mt-1" style={{ fontSize: 12 }}>
          {complete ? "fully covered" : `${plural(total - count, "row")} left`} · {hint}
        </div>
      </div>
    </div>
  );
}

export function ReconcileCoverage({ register, events }: { register: Register; events: TransactionEvent[] }) {
  const totalBank = events.filter((e) => e.source === "bank").length;
  const totalLedger = events.filter((e) => e.source === "ledger").length;
  const bankAttributed = totalBank - register.other.bankUnattached;
  const ledgerMatched = totalLedger - register.other.ledgerUnattached;
  const settlementsTraced = register.rows.filter((r) => r.status.kind !== "unmatched").length;

  return (
    <FcCard variant="hero" className="flex h-full flex-col" style={{ padding: 0 }}>
      <FcCardHeader title="Coverage" sub="Three ratios, not blended into one number." />
      <div className="flex flex-1 flex-col justify-around gap-4" style={{ padding: "4px 18px 20px" }}>
        <Ratio
          label="Bank rows attributed"
          hint="a match or exception claims it"
          count={bankAttributed}
          total={totalBank}
          href="/app1/records"
        />
        <Ratio
          label="Ledger lines matched"
          hint="a match or exception claims it"
          count={ledgerMatched}
          total={totalLedger}
          href="/app1/records"
        />
        <Ratio
          label="Gateway settlements traced"
          hint="reached at least a two-way match"
          count={settlementsTraced}
          total={register.counts.settlements}
          href="/app1/settlements"
        />
      </div>
    </FcCard>
  );
}
