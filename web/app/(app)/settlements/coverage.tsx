"use client";

// Three ratios, never one blended percentage. Each is a share of the
// settlements in the register, with the rupee value alongside. Only the
// ratio that is actually a problem ("needs a human") carries color; the
// other two read as neutral gray/white so the eye goes to what's short.

import { motion } from "framer-motion";
import { clsx } from "clsx";
import { FcCard, FcCardHeader, FcMoney, WhyLabel, WhyWrap } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";
import { moneyParts, plural } from "../_lib/format";
import type { Register } from "./register";

type RingTone = "ok" | "text-3" | "bad";

const RING_COLOR: Record<RingTone, string> = {
  ok: "var(--fc-ok)",
  "text-3": "var(--fc-text-3)",
  bad: "var(--fc-bad)",
};

function Ratio({
  label,
  hint,
  count,
  total,
  paise,
  tone,
  href,
}: {
  label: string;
  hint: string;
  count: number;
  total: number;
  paise: number;
  tone: RingTone;
  href: string;
}) {
  const fraction = total ? count / total : 0;
  const pct = Math.round(fraction * 100);
  const color = RING_COLOR[tone];
  return (
    <div className="flex items-center gap-4">
      <div className="relative shrink-0" style={{ width: 56, height: 56 }}>
        <svg viewBox="0 0 56 56" width={56} height={56}>
          <circle cx={28} cy={28} r={24} fill="none" stroke="var(--fc-divider)" strokeWidth={5} />
          <motion.circle
            cx={28}
            cy={28}
            r={24}
            fill="none"
            stroke={color}
            strokeWidth={5}
            strokeDasharray={150.8}
            strokeLinecap="round"
            transform="rotate(-90 28 28)"
            initial={{ strokeDashoffset: 150.8 }}
            animate={{ strokeDashoffset: 150.8 * (1 - fraction) }}
            transition={{ duration: 0.8, ease: [0.23, 1, 0.32, 1] }}
          />
        </svg>
        <span className="fc-num absolute inset-0 flex items-center justify-center" style={{ fontSize: 12, fontWeight: 500, color }}>
          <CountUp value={pct} format={(n) => `${Math.round(n)}%`} />
        </span>
      </div>
      <div className="min-w-0">
        <div className="fc-label">{label}</div>
        <WhyWrap className="mt-1">
          {tone === "text-3" ? (
            <span className={clsx("fc-num fc-why-figure")} style={{ color, fontSize: 22, fontWeight: 400, letterSpacing: "-0.02em" }}>
              {moneyParts(paise)[0]}
              {moneyParts(paise)[1] && <span style={{ opacity: 0.45, fontSize: "0.6em" }}>{moneyParts(paise)[1]}</span>}
            </span>
          ) : (
            <FcMoney paise={paise} size="lg" tone={tone === "bad" ? "bad" : tone === "ok" ? "ok" : "neutral"} className="fc-why-figure" />
          )}
          <WhyLabel href={href} />
        </WhyWrap>
        <div className="fc-faint mt-0.5" style={{ fontSize: 12 }}>
          {plural(count, "settlement")} of {total}
        </div>
        <div className="fc-faint" style={{ fontSize: 11.5 }}>{hint}</div>
      </div>
    </div>
  );
}

export function Coverage({ register }: { register: Register }) {
  const total = register.counts.settlements;
  const c = register.coverage;
  return (
    <FcCard className="flex h-full flex-col" style={{ padding: 0 }}>
      <FcCardHeader title="Coverage" sub="Three ratios, not blended into one number." />
      <div className="grid grid-cols-3 gap-5" style={{ padding: "0 16px 16px" }}>
        <Ratio
          label="Closed by proof"
          hint="The cascade found bank and books agreeing and closed it."
          count={c.proof.count}
          total={total}
          paise={c.proof.paise}
          tone="ok"
          href="/records"
        />
        <Ratio
          label="Closed by rule"
          hint="A Rulebook deduction explained the whole gap."
          count={c.rule.count}
          total={total}
          paise={c.rule.paise}
          tone="text-3"
          href="/records"
        />
        <Ratio
          label="Needs a human"
          hint="An open decision sits on the settlement."
          count={c.human.count}
          total={total}
          paise={c.human.paise}
          tone="bad"
          href="/decisions"
        />
      </div>
    </FcCard>
  );
}
