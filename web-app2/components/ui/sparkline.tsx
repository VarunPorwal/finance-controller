"use client";

import { useId } from "react";

/**
 * A tiny inline trend. Presentation only: it scales a list of server-supplied
 * integers into a viewBox, it never derives a new figure from them.
 */
export function Sparkline({
  values,
  color = "var(--accent)",
  height = 36,
  className,
  fill = true,
}: {
  values: number[];
  color?: string;
  height?: number;
  className?: string;
  fill?: boolean;
}) {
  const id = useId();
  const w = 200;
  const h = height;
  if (values.length === 0) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const step = values.length > 1 ? w / (values.length - 1) : 0;
  const pts = values.map((v, i) => [values.length > 1 ? i * step : w / 2, h - 3 - ((v - min) / span) * (h - 6)] as const);
  const line = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${h} L${pts[0][0].toFixed(1)},${h} Z`;
  const last = pts[pts.length - 1];

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={className} style={{ width: "100%", height }} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.28} />
          <stop offset="100%" stopColor={color} stopOpacity={0} />
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#${id})`} className="tick-in" style={{ animationDelay: "400ms" }} />}
      <path d={line} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" pathLength={1} className="draw" />
      <circle cx={last[0]} cy={last[1]} r={2.5} fill={color} vectorEffect="non-scaling-stroke" className="tick-in" style={{ animationDelay: "560ms" }} />
    </svg>
  );
}
