import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Pill, type PillTone } from "@/components/ui/pill";
import { AnimatedNumber } from "@/components/ui/animated-number";

type Size = "28" | "22" | "15";

const SIZE_CLASS: Record<Size, string> = {
  "28": "text-[28px] leading-none",
  "22": "text-[22px] leading-none",
  "15": "text-[15px] leading-none",
};

/**
 * A labelled figure. The value is already computed server-side; this only
 * sets it in mono at one of the three numeral sizes. Pass `numeric` with a
 * `format` to have it count up on arrival.
 */
export function Stat({
  label,
  value,
  numeric,
  format,
  size = "22",
  tone,
  delta,
  deltaTone = "ok",
  sub,
  badge,
  icon,
  children,
  className,
}: {
  label: ReactNode;
  value?: ReactNode;
  numeric?: number;
  format?: (n: number) => string;
  size?: Size;
  tone?: "ok" | "warn" | "bad" | "model" | "accent";
  delta?: ReactNode;
  deltaTone?: "ok" | "warn" | "bad";
  sub?: ReactNode;
  badge?: { label: string; tone: PillTone };
  icon?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const toneClass =
    tone === "ok"
      ? "text-ok"
      : tone === "warn"
        ? "text-warn"
        : tone === "bad"
          ? "text-bad"
          : tone === "model"
            ? "text-model"
            : tone === "accent"
              ? "text-accent"
              : "text-ink";
  const deltaClass = deltaTone === "ok" ? "text-ok" : deltaTone === "warn" ? "text-warn" : "text-bad";

  return (
    <div className={cn("panel flex flex-col px-[18px] pt-4 pb-[18px]", className)}>
      <div className="flex items-center justify-between gap-2">
        <div className="label">{label}</div>
        {icon && <span className="text-ink-3">{icon}</span>}
        {badge && <Pill tone={badge.tone}>{badge.label}</Pill>}
      </div>
      <div className={cn("num mt-3 font-semibold whitespace-nowrap", SIZE_CLASS[size], toneClass)}>
        {numeric != null ? <AnimatedNumber value={numeric} format={format} /> : value}
      </div>
      {(delta || sub) && (
        <div className="mt-2 flex items-baseline gap-2 text-[11.5px]">
          {delta && <span className={cn("num font-semibold", deltaClass)}>{delta}</span>}
          {sub && <span className="text-ink-3">{sub}</span>}
        </div>
      )}
      {children}
    </div>
  );
}
