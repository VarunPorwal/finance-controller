import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { StatusPill } from "@/components/ui/status-pill";

// design/README.md: one card shape reused for the KPI row, activity stats,
// and evaluation quality gates — label + optional icon chip on top, a mono
// value (one of the app's exactly three numeral sizes) + optional delta or
// PASS/FAIL badge, and an optional caption underneath.
export function StatCard({
  label,
  value,
  valueSize = "28",
  icon,
  iconBg,
  iconColor,
  delta,
  deltaTone = "success",
  badge,
  sub,
  className,
}: {
  label: string;
  value: ReactNode;
  valueSize?: "28" | "22" | "16";
  icon?: ReactNode;
  iconBg?: string;
  iconColor?: string;
  delta?: string;
  deltaTone?: "success" | "amber" | "error";
  badge?: { label: string; tone: "success" | "amber" | "error" | "neutral" };
  sub?: string;
  className?: string;
}) {
  const deltaColor =
    deltaTone === "success" ? "text-success" : deltaTone === "amber" ? "text-amber-text" : "text-error";
  const valueSizeClass =
    valueSize === "28" ? "text-[28px]" : valueSize === "22" ? "text-[22px]" : "text-base";

  return (
    <div className={cn("fc-card", className)}>
      <div className="flex items-center justify-between px-[18px] pt-4">
        <div className="text-[13px] font-medium whitespace-nowrap text-text-body">{label}</div>
        {icon && (
          <div
            className="flex h-[26px] w-[26px] items-center justify-center rounded-[8px]"
            style={{ background: iconBg, color: iconColor }}
          >
            {icon}
          </div>
        )}
        {badge && <StatusPill tone={badge.tone}>{badge.label}</StatusPill>}
      </div>
      <div className="px-[18px] pt-3.5 pb-5">
        <div className={cn("fc-numeric font-semibold tracking-[-0.01em]", valueSizeClass)}>
          {value}
        </div>
        {(delta || sub) && (
          <div className="mt-2 flex items-center gap-1.5 text-xs">
            {delta && <span className={cn("font-semibold", deltaColor)}>{delta}</span>}
            {sub && <span className="text-text-muted">{sub}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
