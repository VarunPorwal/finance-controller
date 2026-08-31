"use client";

// A minimal magnitude-over-time chart for however many runs actually exist —
// 1 point is a single bar, not a placeholder. Single series: no legend (the
// card title names it), bars capped at 24px, 4px rounded data-end, baseline
// square, 4px gap between bars, direct label only on the last (endpoint) bar.
export function TrendBars({
  points,
  color,
  formatValue = (v) => v.toLocaleString("en-IN"),
}: {
  points: { label: string; value: number }[];
  color: string;
  formatValue?: (value: number) => string;
}) {
  if (points.length === 0) return null;
  const max = Math.max(...points.map((p) => p.value), 1);

  return (
    <div className="flex h-[88px] items-end gap-1" role="img" aria-label="Trend across recent runs">
      {points.map((p, i) => {
        const isLast = i === points.length - 1;
        const heightPct = Math.max((p.value / max) * 100, p.value > 0 ? 4 : 0);
        return (
          <div key={i} className="flex flex-1 flex-col items-center justify-end gap-1" title={`${p.label}: ${formatValue(p.value)}`}>
            {isLast && (
              <span className="fc-numeric text-[11px] font-semibold" style={{ color }}>
                {formatValue(p.value)}
              </span>
            )}
            <div
              className="w-full max-w-[24px] rounded-t-[4px]"
              style={{ height: `${heightPct}%`, minHeight: p.value > 0 ? 3 : 0, background: color }}
            />
          </div>
        );
      })}
    </div>
  );
}
