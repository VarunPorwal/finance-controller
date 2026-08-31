"use client";

import { useId } from "react";
import { motion } from "framer-motion";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface TrendPoint {
  label: string;
  value: number;
}

/**
 * A modern, interactive area chart for however many run-history points
 * exist — 1 point still renders (as a flat dot), it doesn't wait for a
 * minimum. Single series: color is the identity, no legend box needed.
 */
export function InteractiveTrendChart({
  points,
  color,
  formatValue = (v) => v.toLocaleString("en-IN"),
  height = 160,
}: {
  points: TrendPoint[];
  color: string;
  formatValue?: (value: number) => string;
  height?: number;
}) {
  const gradientId = useId();

  if (points.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      style={{ width: "100%", height }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.28} />
              <stop offset="100%" stopColor={color} stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <XAxis
            dataKey="label"
            axisLine={false}
            tickLine={false}
            tick={{ fill: "var(--text-muted)", fontSize: 11 }}
            interval="preserveStartEnd"
            minTickGap={24}
          />
          <YAxis hide domain={[0, (max: number) => Math.max(max * 1.15, 1)]} />
          <Tooltip
            cursor={{ stroke: "var(--border)", strokeWidth: 1 }}
            content={({ active, payload, label }) => {
              if (!active || !payload || payload.length === 0) return null;
              const value = payload[0]?.value as number;
              return (
                <div className="fc-card rounded-[9px] border border-border px-3 py-2 text-xs shadow-lg">
                  <div className="text-text-muted">{label}</div>
                  <div className="fc-numeric mt-0.5 font-semibold" style={{ color }}>
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
            strokeWidth={2}
            fill={`url(#${gradientId})`}
            dot={points.length <= 12 ? { r: 3, fill: color, strokeWidth: 0 } : false}
            activeDot={{ r: 5, fill: color, stroke: "var(--card)", strokeWidth: 2 }}
            animationDuration={500}
            animationEasing="ease-out"
          />
        </AreaChart>
      </ResponsiveContainer>
    </motion.div>
  );
}
