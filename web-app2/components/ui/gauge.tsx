"use client";

import { cn } from "@/lib/utils";

/**
 * A polar dial. Exactly one is allowed per screen, for a rate. Every other
 * headline figure is a tabular numeral, never a dial.
 */
export function Gauge({
  value,
  label,
  readout,
  tone = "ok",
  size = 150,
  className,
}: {
  /** 0..1, already computed server-side. */
  value: number;
  label: string;
  readout: string;
  tone?: "ok" | "warn" | "bad" | "accent";
  size?: number;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value));
  const ticks = 40;
  const start = -210;
  const sweep = 240;
  const cx = 50;
  const cy = 52;
  const rOuter = 44;
  const rInner = 37;
  const color = `var(--${tone})`;
  const lit = Math.round(clamped * ticks);

  return (
    <div className={cn("relative", className)} style={{ width: size, height: size * 0.8 }}>
      <svg viewBox="0 0 100 82" width={size} height={size * 0.82} aria-hidden>
        {Array.from({ length: ticks + 1 }).map((_, i) => {
          const a = ((start + (sweep * i) / ticks) * Math.PI) / 180;
          const x1 = cx + rInner * Math.cos(a);
          const y1 = cy + rInner * Math.sin(a);
          const x2 = cx + rOuter * Math.cos(a);
          const y2 = cy + rOuter * Math.sin(a);
          const on = i <= lit;
          return (
            <line
              key={i}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={on ? color : "var(--line-strong)"}
              strokeWidth={i % 5 === 0 ? 1.6 : 1}
              strokeLinecap="round"
              className={on ? "tick-in" : undefined}
              style={on ? { animationDelay: `${i * 12}ms` } : undefined}
            />
          );
        })}
      </svg>
      <div className="absolute inset-x-0 top-[46%] flex flex-col items-center">
        <div className="num tick-in text-[22px] leading-none font-semibold" style={{ color, animationDelay: "320ms" }}>
          {readout}
        </div>
        <div className="label mt-1.5">{label}</div>
      </div>
    </div>
  );
}
