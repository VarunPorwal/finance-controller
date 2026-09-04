"use client";

// Where every decision went: one bar of matches plus exceptions on the left,
// flowing into the stage that formed each match, and an amber band for what
// still needs a person.

import { motion, useReducedMotion } from "framer-motion";
import type { MatchResult } from "../_lib/api";
import { STAGE, STAGE_ORDER } from "../_lib/labels";
import { plural } from "../_lib/format";

const W = 720;
const BAR = 26;
const LEFT_X = 0;
const RIGHT_X = 400;
const GAP = 14;
// Tall enough to hold three stacked label lines (name, count, auto-closed)
// without the next band's block starting before this one's text ends.
const MIN_H = 46;
const BODY = 230;

interface Band {
  key: string;
  label: string;
  hint: string;
  count: number;
  auto: number;
  color: string;
}

export function StageFunnel({ matches, exceptions }: { matches: MatchResult[]; exceptions: number }) {
  const reduced = useReducedMotion();
  const perStage = new Map<string, { count: number; auto: number }>();
  for (const m of matches) {
    const s = perStage.get(m.stage) ?? { count: 0, auto: 0 };
    s.count += 1;
    if (m.auto_closed) s.auto += 1;
    perStage.set(m.stage, s);
  }

  const bands: Band[] = STAGE_ORDER.filter((s) => (perStage.get(s)?.count ?? 0) > 0).map((s) => ({
    key: s,
    label: STAGE[s].label,
    hint: STAGE[s].short,
    count: perStage.get(s)!.count,
    auto: perStage.get(s)!.auto,
    color: STAGE[s].mayAutoClose ? "var(--fc-accent)" : "var(--fc-text-3)",
  }));
  if (exceptions > 0)
    bands.push({ key: "human", label: "Needs a human", hint: "Exceptions", count: exceptions, auto: 0, color: "var(--fc-warn)" });

  const total = matches.length + exceptions;
  const silent = STAGE_ORDER.filter((s) => !perStage.has(s));

  if (total === 0) return <p className="fc-faint" style={{ fontSize: 12.5 }}>No matches or exceptions in this run yet.</p>;

  const avail = BODY - GAP * (bands.length - 1);
  const heights = bands.map((b) => Math.max(MIN_H, (b.count / total) * avail));
  const sumH = heights.reduce((a, b) => a + b, 0);
  const H = sumH + GAP * (bands.length - 1) + 30;

  let ly = 15;
  let ry = 15;
  const placed = bands.map((b, i) => {
    const h = heights[i];
    const out = { ...b, h, ly0: ly, ly1: ly + h, ry0: ry, ry1: ry + h };
    ly += h;
    ry += h + GAP;
    return out;
  });
  const x0 = LEFT_X + BAR;
  const x1 = RIGHT_X;
  const cx = (x0 + x1) / 2;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between" style={{ fontSize: 12 }}>
        <span>
          <span className="fc-num" style={{ fontWeight: 500 }}>{total.toLocaleString("en-IN")}</span>
          <span className="fc-muted"> decisions: {plural(matches.length, "match", "matches")} and {plural(exceptions, "exception")}</span>
        </span>
        <span className="fc-faint">Band height is share of decisions</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full" role="img" aria-label="Decisions by stage">
        <rect x={LEFT_X} y={15} width={BAR} height={sumH} rx={4} fill="var(--fc-divider)" />
        {placed.map((b, i) => (
          <g key={b.key}>
            <motion.path
              d={`M${x0},${b.ly0} C${cx},${b.ly0} ${cx},${b.ry0} ${x1},${b.ry0} L${x1},${b.ry1} C${cx},${b.ry1} ${cx},${b.ly1} ${x0},${b.ly1} Z`}
              fill={b.color}
              fillOpacity={0.16}
              initial={reduced ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.5, delay: i * 0.06 }}
            />
            <rect x={LEFT_X} y={b.ly0} width={BAR} height={b.h} fill={b.color} fillOpacity={0.55} />
            <motion.rect
              x={x1}
              y={b.ry0}
              width={BAR}
              height={b.h}
              rx={3}
              fill={b.color}
              initial={reduced ? false : { opacity: 0, x: x1 - 8 }}
              animate={{ opacity: 1, x: x1 }}
              transition={{ duration: 0.45, delay: i * 0.06, ease: [0.2, 0.8, 0.2, 1] }}
            />
            {/* Name on its own line, the count on the line below it, and
                what happened to that count (auto-closed / ranked for a
                person) on a third line — never two figures run together. */}
            <text x={x1 + BAR + 12} y={b.ry0 + 13} fontSize={12} fill="var(--fc-text)" fontWeight={500}>
              {b.label}
              <tspan fill="var(--fc-text-3)" fontSize={10.5}>
                {"  "}
                {b.hint}
              </tspan>
            </text>
            <text x={x1 + BAR + 12} y={b.ry0 + 29} fontSize={13} fill="var(--fc-text)" className="fc-num" fontWeight={500}>
              {b.count.toLocaleString("en-IN")}
            </text>
            <text x={x1 + BAR + 12} y={b.ry0 + 43} fontSize={11} className="fc-num">
              {b.key === "human" ? (
                <tspan fill="var(--fc-warn)">ranked for a person</tspan>
              ) : (
                <tspan fill={b.auto > 0 ? "var(--fc-ok)" : "var(--fc-text-3)"}>{b.auto} auto-closed</tspan>
              )}
            </text>
          </g>
        ))}
        <text x={LEFT_X} y={10} fontSize={10.5} fill="var(--fc-text-3)">
          all decisions
        </text>
        <text x={x1} y={10} fontSize={10.5} fill="var(--fc-text-3)">
          who decided
        </text>
      </svg>
      {silent.length > 0 && (
        <p className="fc-faint" style={{ fontSize: 11.5 }}>
          Formed nothing in this run: {silent.map((s) => STAGE[s].label).join(", ")}. A stage that forms no match is
          reported here.
        </p>
      )}
    </div>
  );
}
