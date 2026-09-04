import { BookText, CreditCard, Landmark } from "lucide-react";
import { cn } from "@/lib/utils";

export type SourceKey = "razorpay" | "bank" | "ledger" | "tally";

const META: Record<"razorpay" | "bank" | "ledger", { label: string; color: string; Icon: typeof Landmark }> = {
  razorpay: { label: "Razorpay", color: "var(--src-razorpay)", Icon: CreditCard },
  bank: { label: "Bank", color: "var(--src-bank)", Icon: Landmark },
  ledger: { label: "Tally", color: "var(--src-ledger)", Icon: BookText },
};

const ORDER = ["razorpay", "bank", "ledger", "tally"];

/** One order for the three sources everywhere: gateway, bank, books. */
export function orderSources(bySource: Record<string, number>): { label: string; count: number }[] {
  return Object.entries(bySource)
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => {
      const ia = ORDER.indexOf(a.label);
      const ib = ORDER.indexOf(b.label);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    });
}

export function sourceMeta(source: string) {
  const key = source === "tally" ? "ledger" : (source as "razorpay" | "bank" | "ledger");
  return META[key] ?? { label: source, color: "var(--ink-3)", Icon: CreditCard };
}

export function SourceGlyph({ source, size = 24, className }: { source: string; size?: number; className?: string }) {
  const { color, Icon } = sourceMeta(source);
  return (
    <span
      className={cn("inline-flex shrink-0 items-center justify-center rounded-[7px] border", className)}
      style={{
        width: size,
        height: size,
        color,
        borderColor: "color-mix(in srgb, " + color + " 30%, transparent)",
        background: "color-mix(in srgb, " + color + " 10%, transparent)",
      }}
    >
      <Icon width={Math.round(size * 0.52)} height={Math.round(size * 0.52)} />
    </span>
  );
}

export function SourceDot({ source, className }: { source: string; className?: string }) {
  const { color } = sourceMeta(source);
  return <span className={cn("inline-block h-2 w-2 rounded-[2px]", className)} style={{ background: color }} />;
}
