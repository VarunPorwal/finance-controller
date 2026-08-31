import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// design/README.md: statusPill(color, bg) — a closed set of tones, never an
// arbitrary hex. "model" is the one tone that marks LLM output and must
// never appear on a deterministic value.
const statusPillVariants = cva(
  "inline-flex items-center rounded-[var(--radius-pill)] px-2 py-[3px] text-[11px] font-semibold whitespace-nowrap",
  {
    variants: {
      tone: {
        success: "bg-success-bg text-success",
        amber: "bg-amber-bg text-amber-text",
        error: "bg-error-bg text-error",
        neutral: "bg-neutral-bg text-neutral-text",
        model: "bg-model-pill-bg text-model-text",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function StatusPill({
  tone,
  className,
  children,
}: VariantProps<typeof statusPillVariants> & {
  className?: string;
  children: React.ReactNode;
}) {
  return <span className={cn(statusPillVariants({ tone }), className)}>{children}</span>;
}
