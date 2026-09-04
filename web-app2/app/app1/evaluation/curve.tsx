"use client";

// Coverage against precision as the auto-close threshold moves. Hand-built
// SVG so the shipped threshold can be drawn as a real line, not a legend.

import { useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { pct, plural } from "../_lib/format";
import { nearest, thresholdText, type CurvePoint } from "./shape";

const W = 720;
const H = 240;
const L = 44;
const R = 20;
const T = 22;
const B = 30;
const MONO: React.CSSProperties = { fontFamily: "var(--font-geist-mono)" };

export function CoverageCurve({ points, shipped }: { points: CurvePoint[]; shipped: number }) {
  const reduced = useReducedMotion();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  if (points.length === 0) return null;

  const xs = points.map((p) => p.threshold);
  const xMin = Math.min(0.7, ...xs);
  const xMax = Math.max(0.99, ...xs);
  const x = (t: number) => L + ((t - xMin) / (xMax - xMin)) * (W - L - R);
  const y = (v: number) => T + (1 - Math.max(0, Math.min(1, v))) * (H - T - B);

  const path = (key: "coverage" | "precision") =>
    points.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.threshold).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = svgRef.current;
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    const vx = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0;
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(x(points[i].threshold) - vx) < Math.abs(x(points[best].threshold) - vx)) best = i;
    }
    setHover(best);
  };

  const at = nearest(points, shipped);
  const low = nearest(points, 0.85);
  const hp = hover !== null ? points[hover] : null;
  const yTicks = [0, 0.25, 0.5, 0.75, 1];

  return (
    <div className="flex flex-col gap-3">
      <div className="relative">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          className="block h-auto w-full"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          role="img"
          aria-label="Coverage and precision by threshold"
        >
          {yTicks.map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="var(--fc-divider)" />
              <text x={L - 8} y={y(v) + 3.5} textAnchor="end" fontSize={10} fill="var(--fc-text-3)" className="fc-num" style={MONO}>
                {Math.round(v * 100)}%
              </text>
            </g>
          ))}
          {points.map((p) => (
            <text
              key={p.threshold}
              x={x(p.threshold)}
              y={H - B + 16}
              textAnchor="middle"
              fontSize={10}
              fill={p.threshold === at?.threshold ? "var(--fc-warn)" : "var(--fc-text-3)"}
              className="fc-num"
              style={MONO}
            >
              {p.label}
            </text>
          ))}

          <line
            x1={x(shipped)}
            x2={x(shipped)}
            y1={T - 6}
            y2={H - B}
            stroke="var(--fc-warn)"
            strokeDasharray="3 3"
            strokeWidth={1.2}
          />
          <text x={x(shipped) + 6} y={T + 4} fontSize={10.5} fill="var(--fc-warn)" fontWeight={500} className="fc-num" style={MONO}>
            shipped at {thresholdText(shipped)}
          </text>

          <motion.path
            d={path("coverage")}
            fill="none"
            stroke="var(--fc-accent)"
            strokeWidth={1.8}
            strokeLinejoin="round"
            initial={reduced ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.1, ease: "easeOut" }}
          />
          <motion.path
            d={path("precision")}
            fill="none"
            stroke="var(--fc-ok)"
            strokeWidth={1.8}
            strokeLinejoin="round"
            initial={reduced ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 1.1, ease: "easeOut", delay: 0.15 }}
          />
          {points.map((p, i) => (
            <g key={p.threshold} opacity={hover === null || hover === i ? 1 : 0.35}>
              <circle cx={x(p.threshold)} cy={y(p.coverage)} r={hover === i ? 4 : 2.5} fill="var(--fc-accent)" />
              <circle cx={x(p.threshold)} cy={y(p.precision)} r={hover === i ? 4 : 2.5} fill="var(--fc-ok)" />
            </g>
          ))}
          {hp && (
            <line x1={x(hp.threshold)} x2={x(hp.threshold)} y1={T} y2={H - B} stroke="var(--fc-border)" />
          )}
        </svg>
        {hp && (
          <div
            className="fc-card fc-card--flat pointer-events-none absolute top-2 z-10"
            style={{
              left: `${(x(hp.threshold) / W) * 100}%`,
              transform: x(hp.threshold) > W * 0.7 ? "translateX(calc(-100% - 10px))" : "translateX(10px)",
              padding: "8px 12px",
              fontSize: 11.5,
            }}
          >
            <div className="fc-num mb-1" style={{ ...MONO, fontWeight: 500 }}>threshold {hp.label}</div>
            <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
              <span style={{ color: "var(--fc-accent)" }}>coverage</span>
              <span className="fc-num text-right" style={MONO}>{pct(hp.coverage, 1)}</span>
              <span style={{ color: "var(--fc-ok)" }}>precision</span>
              <span className="fc-num text-right" style={MONO}>{pct(hp.precision, 1)}</span>
              <span className="fc-muted">abstentions</span>
              <span className="fc-num text-right" style={MONO}>{hp.abstentions}</span>
              <span style={{ color: "var(--fc-bad)" }}>false positives</span>
              <span className="fc-num text-right" style={MONO}>{hp.false_positives}</span>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-4" style={{ fontSize: 11.5 }}>
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded" style={{ background: "var(--fc-accent)" }} />
          Coverage, share auto-resolved
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded" style={{ background: "var(--fc-ok)" }} />
          Precision on those
        </span>
      </div>

      {at && low && (
        <p className="fc-muted" style={{ fontSize: 13 }}>
          At <span className="fc-num fc-strong" style={MONO}>{at.label}</span>: {pct(at.coverage, 1)} auto-resolved at{" "}
          {pct(at.precision, 1)} precision. Lowering to <span className="fc-num" style={MONO}>{low.label}</span> would{" "}
          {low.coverage > at.coverage ? `raise coverage to ${pct(low.coverage, 1)}` : `leave coverage at ${pct(low.coverage, 1)}`}{" "}
          and cost{" "}
          <span
            className="fc-num"
            style={{ ...MONO, ...(Math.max(0, low.false_positives - at.false_positives) > 0 ? { color: "var(--fc-bad)" } : undefined) }}
          >
            {plural(Math.max(0, low.false_positives - at.false_positives), "false positive")}
          </span>
          .
        </p>
      )}
    </div>
  );
}
