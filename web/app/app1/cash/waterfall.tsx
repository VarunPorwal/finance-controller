"use client";

// The gateway bridge as a waterfall: gross collected, each deduction stepping
// down, expected net, the unexplained step, actual bank. Hand-built SVG so the
// bars can carry their own labels and grow from the baseline on mount. The
// figures are the server's; the chart only positions them.

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { motion, useReducedMotion } from "framer-motion";
import { money, plural } from "../_lib/format";
import type { CashBridge } from "../_lib/api";

type Segment = CashBridge["segments"][number];

interface Bar {
  key: string;
  label: string;
  amount: number;
  kind: "total" | "step";
  color: string;
  /** True only for the unexplained/gap step — the one bar allowed to alarm. */
  isAlert: boolean;
  /** Level the bar starts from and ends at (running total, in paise). */
  from: number;
  to: number;
  attributed: number;
  exceptionIds: string[];
  eventCount: number;
}

// Two tones plus one alert: gross/expected/actual (the totals) read neutral,
// every deduction reads as one undifferentiated gray block, and only the
// unexplained step gets the danger color. The eye should land on the one bar
// that's a problem, not on which fee is bigger than which.
const TOTAL_COLOR = "var(--fc-accent)";
const STEP_COLOR = "var(--fc-divider)";
const ALERT_COLOR = "var(--fc-bad)";

// The bridge from gross to actual, built entirely from `bridge.segments`:
// the six named deductions followed by a server-computed "Unexplained" step
// (§ its own exception_ids and attributed_paise, not derived here). The
// "Expected net" and "Actual bank" totals are inserted around it for
// readability; their values are the server's own fields, not recomputed.
export function buildBars(bridge: CashBridge): Bar[] {
  const bars: Bar[] = [];
  const gross = bridge.gross_collected_paise;
  bars.push({
    key: "gross",
    label: "Gross collected",
    amount: gross,
    kind: "total",
    color: TOTAL_COLOR,
    isAlert: false,
    from: 0,
    to: gross,
    attributed: 0,
    exceptionIds: [],
    eventCount: bridge.gross_event_ids.length,
  });
  let level = gross;
  for (const seg of bridge.segments as Segment[]) {
    const isUnexplained = seg.label === "Unexplained";
    if (isUnexplained) {
      bars.push({
        key: "expected",
        label: "Expected net",
        amount: bridge.expected_net_paise,
        kind: "total",
        color: TOTAL_COLOR,
        isAlert: false,
        from: 0,
        to: bridge.expected_net_paise,
        attributed: 0,
        exceptionIds: [],
        eventCount: 0,
      });
    }
    const next = level - seg.amount_paise;
    bars.push({
      key: `s-${seg.label}`,
      label: seg.label,
      amount: seg.amount_paise,
      kind: "step",
      color: isUnexplained ? ALERT_COLOR : STEP_COLOR,
      isAlert: isUnexplained,
      from: level,
      to: next,
      attributed: seg.attributed_paise,
      exceptionIds: seg.exception_ids,
      eventCount: seg.event_ids.length,
    });
    level = next;
  }
  bars.push({
    key: "actual",
    label: "Actual bank",
    amount: bridge.actual_bank_paise,
    kind: "total",
    color: TOTAL_COLOR,
    isAlert: false,
    from: 0,
    to: bridge.actual_bank_paise,
    attributed: 0,
    exceptionIds: [],
    eventCount: bridge.actual_bank_event_ids.length,
  });
  return bars;
}

const H = 340;
const PAD_TOP = 40;
const PAD_BOTTOM = 56;
const PAD_X = 16;

export function Waterfall({ bridge }: { bridge: CashBridge }) {
  const router = useRouter();
  const reduced = useReducedMotion();
  const wrap = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(960);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(Math.max(480, Math.floor(w)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const bars = useMemo(() => buildBars(bridge), [bridge]);

  const plotH = H - PAD_TOP - PAD_BOTTOM;
  const max = Math.max(1, ...bars.map((b) => Math.max(b.from, b.to)));
  const yOf = (v: number) => PAD_TOP + plotH - (Math.max(0, v) / max) * plotH;
  const baseline = yOf(0);

  const n = bars.length;
  const slot = (width - PAD_X * 2) / n;
  const barW = Math.min(88, slot * 0.62);

  return (
    <div ref={wrap} className="relative w-full">
      <svg width={width} height={H} viewBox={`0 0 ${width} ${H}`} className="block" role="img" aria-label="Cash bridge waterfall">
        <line x1={PAD_X} x2={width - PAD_X} y1={baseline} y2={baseline} stroke="var(--fc-divider)" />
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line
            key={f}
            x1={PAD_X}
            x2={width - PAD_X}
            y1={yOf(max * f)}
            y2={yOf(max * f)}
            stroke="var(--fc-border)"
            strokeDasharray="2 4"
          />
        ))}
        {bars.map((b, i) => {
          const cx = PAD_X + slot * i + slot / 2;
          const x = cx - barW / 2;
          const top = yOf(Math.max(b.from, b.to));
          const bottom = yOf(Math.min(b.from, b.to));
          const h = Math.max(1.5, bottom - top);
          const dim = hover !== null && hover !== i;
          const clickable = b.exceptionIds.length > 0;
          const next = bars[i + 1];
          const connectorY = yOf(b.to);
          return (
            <g
              key={b.key}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onClick={clickable ? () => router.push(`/app1/decisions?open=${b.exceptionIds[0]}`) : undefined}
              style={{ cursor: clickable ? "pointer" : "default" }}
            >
              <rect x={PAD_X + slot * i} y={PAD_TOP} width={slot} height={plotH} fill="transparent" />
              <motion.rect
                x={x}
                width={barW}
                rx={4}
                fill={hover === i ? "var(--fc-text)" : b.color}
                initial={reduced ? { attrY: top, height: h } : { attrY: bottom, height: 0 }}
                animate={{ attrY: top, height: h, opacity: dim ? 0.6 : 1 }}
                transition={{
                  attrY: { duration: 0.5, ease: [0.16, 1, 0.3, 1], delay: reduced ? 0 : i * 0.03 },
                  height: { duration: 0.5, ease: [0.16, 1, 0.3, 1], delay: reduced ? 0 : i * 0.03 },
                  opacity: { duration: 0.15 },
                }}
                style={{ filter: hover === i ? `drop-shadow(0 0 10px ${b.color})` : undefined }}
              />
              {next && (
                <motion.line
                  x1={x + barW}
                  x2={PAD_X + slot * (i + 1) + slot / 2 - barW / 2}
                  y1={connectorY}
                  y2={connectorY}
                  stroke="var(--fc-border)"
                  strokeDasharray="3 3"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: dim ? 0.3 : 1 }}
                  transition={{ delay: reduced ? 0 : i * 0.03 + 0.35 }}
                />
              )}
              <motion.text
                x={cx}
                y={top - 8}
                textAnchor="middle"
                fontSize={11.5}
                fontFamily="var(--font-mono)"
                fill={b.isAlert ? ALERT_COLOR : b.kind === "step" ? "var(--fc-text-2)" : "var(--fc-text)"}
                initial={{ opacity: 0 }}
                animate={{ opacity: dim ? 0.4 : 1 }}
                transition={{ delay: reduced ? 0 : i * 0.03 + 0.3 }}
              >
                {b.kind === "step" && b.amount > 0 ? "−" : ""}
                {money(Math.abs(b.amount), { compact: true, whole: true })}
              </motion.text>
              <text
                x={cx}
                y={baseline + 18}
                textAnchor="middle"
                fontSize={11.5}
                fill={dim ? "var(--fc-text-3)" : "var(--fc-text-2)"}
                fontWeight={500}
              >
                {b.label}
              </text>
              {b.attributed > 0 && b.exceptionIds.length > 0 && (
                <text x={cx} y={baseline + 33} textAnchor="middle" fontSize={10.5} fill="var(--fc-text-3)" fontFamily="var(--fc-font)">
                  {money(b.attributed, { compact: true, whole: true })} to {plural(b.exceptionIds.length, "decision")}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {hover !== null && (
        <div
          className="pointer-events-none absolute z-10 px-3 py-2 text-[11.5px]"
          style={{
            left: Math.min(width - 230, Math.max(0, PAD_X + slot * hover + slot / 2 - 110)),
            top: 4,
            width: 220,
            borderRadius: 10,
            background: "var(--fc-hover)",
            border: "1px solid var(--fc-divider)",
            color: "var(--fc-text-2)",
          }}
        >
          <div className="flex items-center justify-between gap-3">
            <span className="fc-strong" style={{ fontWeight: 500 }}>
              {bars[hover].label}
            </span>
            <span className="fc-num font-mono fc-strong">{money(bars[hover].amount)}</span>
          </div>
          {bars[hover].kind === "step" && (
            <div className="fc-faint fc-num font-mono mt-1">
              {money(bars[hover].from, { whole: true })} → {money(bars[hover].to, { whole: true })}
            </div>
          )}
          {bars[hover].eventCount > 0 && <div className="fc-faint mt-0.5">{plural(bars[hover].eventCount, "row")}</div>}
          {bars[hover].attributed > 0 && (
            <div className="fc-num font-mono mt-0.5" style={{ color: "var(--fc-warn)" }}>
              {money(bars[hover].attributed)} attributed to {plural(bars[hover].exceptionIds.length, "open decision")}
            </div>
          )}
          {bars[hover].exceptionIds.length > 0 && <div className="fc-faint mt-1">Click to open the first decision</div>}
        </div>
      )}
    </div>
  );
}

export function WaterfallTable({ bridge }: { bridge: CashBridge }) {
  const bars = useMemo(() => buildBars(bridge), [bridge]);
  return (
    <table className="fc-table">
      <thead>
        <tr>
          <th>Segment</th>
          <th style={{ textAlign: "right" }}>Amount</th>
          <th style={{ textAlign: "right" }}>Attributed</th>
          <th style={{ textAlign: "right" }}>Decisions</th>
          <th style={{ textAlign: "right" }}>Rows</th>
        </tr>
      </thead>
      <tbody>
        {bars.map((b) => (
          <tr key={b.key}>
            <td className={b.kind === "total" ? "fc-strong" : undefined}>
              <span className="inline-flex items-center gap-2">
                <span className="h-2 w-2 rounded-sm" style={{ background: b.color, display: "inline-block" }} />
                {b.label}
              </span>
            </td>
            <td className="fc-table-num font-mono">
              {b.kind === "step" && b.amount > 0 ? <span className="fc-faint">−</span> : null}
              <span className={b.isAlert && b.amount > 0 ? "fc-bad" : undefined}>{money(Math.abs(b.amount))}</span>
            </td>
            <td className="fc-table-num font-mono">
              {b.attributed > 0 ? <span style={{ color: "var(--fc-warn)" }}>{money(b.attributed)}</span> : <span className="fc-faint">—</span>}
            </td>
            <td className="fc-table-num">
              {b.exceptionIds.length > 0 ? b.exceptionIds.length : <span className="fc-faint">—</span>}
            </td>
            <td className="fc-table-num">{b.eventCount > 0 ? b.eventCount : <span className="fc-faint">—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
