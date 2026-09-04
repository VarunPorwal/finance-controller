"use client";

import { useId } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface TrendPoint {
  label: string;
  value: number;
}

/** A run-over-run area chart. One point still renders, as a flat dot. */
export function TrendChart({
  points,
  color = "var(--accent)",
  formatValue = (v) => v.toLocaleString("en-IN"),
  height = 160,
}: {
  points: TrendPoint[];
  color?: string;
  formatValue?: (value: number) => string;
  height?: number;
}) {
  const gradientId = useId();
  if (points.length === 0) return null;

  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.3} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="label"
            axisLine={false}
            tickLine={false}
            tick={{ fill: "var(--ink-3)", fontSize: 10.5, fontFamily: "var(--font-mono)" }}
            interval="preserveStartEnd"
            minTickGap={28}
          />
          <YAxis hide domain={[0, (max: number) => Math.max(max * 1.15, 1)]} />
          <Tooltip
            cursor={{ stroke: "var(--line-strong)", strokeWidth: 1, strokeDasharray: "3 3" }}
            content={({ active, payload, label }) => {
              if (!active || !payload || payload.length === 0) return null;
              const value = payload[0]?.value as number;
              return (
                <div className="rounded-[8px] border border-line-strong bg-surface-2 px-2.5 py-1.5 text-[11px] shadow-[var(--shadow-pop)]">
                  <div className="num text-ink-3">{label}</div>
                  <div className="num mt-0.5 font-semibold" style={{ color }}>
                    {formatValue(value)}
                  </div>
                </div>
              );
            }}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.75}
            fill={`url(#${gradientId})`}
            dot={points.length <= 12 ? { r: 2.5, fill: color, strokeWidth: 0 } : false}
            activeDot={{ r: 4, fill: color, stroke: "var(--surface)", strokeWidth: 2 }}
            animationDuration={280}
            animationEasing="ease-out"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
