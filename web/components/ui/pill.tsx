import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type PillTone = "ok" | "warn" | "bad" | "neutral" | "model" | "accent";

const TONE: Record<PillTone, string> = {
  ok: "bg-ok-soft text-ok border-[rgba(61,220,151,0.25)]",
  warn: "bg-warn-soft text-warn border-[rgba(245,165,36,0.25)]",
  bad: "bg-bad-soft text-bad border-[rgba(255,107,107,0.25)]",
  neutral: "bg-surface-3 text-ink-2 border-line-strong",
  model: "bg-model-soft text-model border-model-line",
  accent: "bg-accent-soft text-accent border-[rgba(138,180,255,0.25)]",
};

const DOT: Record<PillTone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  neutral: "bg-ink-3",
  model: "bg-model",
  accent: "bg-accent",
};

/** A closed set of tones. `model` is the one that marks LLM output. */
export function Pill({
  tone = "neutral",
  dot,
  mono,
  className,
  children,
}: {
  tone?: PillTone;
  dot?: boolean;
  mono?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-[20px] items-center gap-1.5 rounded-[6px] border px-1.5 text-[10.5px] font-semibold tracking-[0.04em] whitespace-nowrap uppercase",
        mono && "num normal-case tracking-normal",
        TONE[tone],
        className,
      )}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", DOT[tone])} />}
      {children}
    </span>
  );
}
