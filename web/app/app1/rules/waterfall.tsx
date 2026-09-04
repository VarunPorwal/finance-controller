"use client";

// A small SVG waterfall: gross on the left, each deduction as a step down,
// net on the right. Drawn on a sample ₹10,000 so the shape of the stack is
// visible at a glance; the figure is an illustration, never a result.

import { motion, useReducedMotion } from "framer-motion";
import { money } from "../_lib/format";
import { deductionShort, illustrate, rateText, SAMPLE_GROSS_PAISE } from "./shared";

export function MiniWaterfall({
  deductions,
  width = 220,
  height = 70,
  className,
}: {
  deductions: { type: string; basis: string; rate: string | number; fixed_paise?: number | null }[];
  width?: number;
  height?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();
  const { lines, net } = illustrate(deductions);
  const cols = lines.length + 2;
  const gap = 6;
  const colW = (width - gap * (cols - 1)) / cols;
  const labelH = 24;
  const top = 3;
  const barH = height - labelH - top;
  const scale = barH / SAMPLE_GROSS_PAISE;
  const yOf = (paise: number) => top + barH - Math.max(0, paise) * scale;

  const x = (i: number) => i * (colW + gap);
  const font = 8.5;

  let level = SAMPLE_GROSS_PAISE;
  const steps = lines.map((l, i) => {
    const from = level;
    level -= l.amount;
    return { ...l, from, to: level, i: i + 1 };
  });

  const bar = (key: string, cx: number, y0: number, y1: number, fill: string, title: string, delay: number) => {
    const y = Math.min(y0, y1);
    const h = Math.max(1, Math.abs(y1 - y0));
    return (
      <motion.rect
        key={key}
        x={cx}
        width={colW}
        rx={2}
        fill={fill}
        initial={reduced ? { y, height: h } : { y: y + h, height: 0 }}
        animate={{ y, height: h }}
        transition={{ duration: 0.5, delay, ease: [0.2, 0.8, 0.2, 1] }}
      >
        <title>{title}</title>
      </motion.rect>
    );
  };

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      role="img"
      aria-label={`Illustration on ${money(SAMPLE_GROSS_PAISE, { whole: true })}: net ${money(net)}`}
    >
      {bar("gross", x(0), yOf(SAMPLE_GROSS_PAISE), yOf(0), "var(--fc-accent)", `Gross ${money(SAMPLE_GROSS_PAISE)}`, 0)}
      {steps.map((s) => (
        <g key={s.type + s.i}>
          <line
            x1={x(s.i - 1) + colW}
            x2={x(s.i)}
            y1={yOf(s.from)}
            y2={yOf(s.from)}
            stroke="var(--fc-divider)"
            strokeDasharray="2 2"
          />
          {bar(
            `d${s.i}`,
            x(s.i),
            yOf(s.from),
            yOf(s.to),
            "var(--fc-text-3)",
            `${deductionShort(s.type)} ${rateText(s.rate)} = ${money(s.amount)}`,
            s.i * 0.06,
          )}
        </g>
      ))}
      <line
        x1={x(cols - 2) + colW}
        x2={x(cols - 1)}
        y1={yOf(net)}
        y2={yOf(net)}
        stroke="var(--fc-divider)"
        strokeDasharray="2 2"
      />
      {bar("net", x(cols - 1), yOf(net), yOf(0), "var(--fc-ok)", `Net ${money(net)}`, cols * 0.06)}

      <text x={x(0) + colW / 2} y={height - 13} textAnchor="middle" fontSize={font} fill="var(--fc-text-2)">
        Gross
      </text>
      {steps.map((s) => (
        <g key={`t${s.i}`}>
          <text x={x(s.i) + colW / 2} y={height - 13} textAnchor="middle" fontSize={font} fill="var(--fc-text-2)">
            {deductionShort(s.type)}
          </text>
          <text
            x={x(s.i) + colW / 2}
            y={height - 3}
            textAnchor="middle"
            fontSize={font}
            fill="var(--fc-text-3)"
            className="fc-num"
          >
            {rateText(s.rate)}
          </text>
        </g>
      ))}
      <text x={x(cols - 1) + colW / 2} y={height - 13} textAnchor="middle" fontSize={font} fill="var(--fc-ok)">
        Net
      </text>
    </svg>
  );
}
