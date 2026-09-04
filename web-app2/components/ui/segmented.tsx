"use client";

import { useId } from "react";
import { LayoutGroup, motion } from "framer-motion";
import { cn } from "@/lib/utils";

const SLIDE = { type: "tween" as const, ease: [0.23, 1, 0.32, 1] as [number, number, number, number], duration: 0.2 };

/** A segmented control whose active pill slides to the chosen option. */
export function Segmented({
  options,
  active,
  onChange,
  className,
}: {
  options: { value: string; label: string; count?: number }[];
  active: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  const id = useId();
  return (
    <LayoutGroup id={id}>
      <div role="group" className={cn("inline-flex h-[32px] items-center gap-0.5 rounded-[9px] border border-line bg-surface p-[3px]", className)}>
        {options.map((opt) => {
          const isActive = opt.value === active;
          return (
            <button
              key={opt.value}
              type="button"
              aria-pressed={isActive}
              onClick={() => onChange(opt.value)}
              className={cn(
                "relative flex h-full cursor-pointer items-center gap-1.5 rounded-[6px] px-3 text-[12px] font-medium whitespace-nowrap transition-colors duration-150",
                isActive ? "text-ink" : "text-ink-3 hover:text-ink-2",
              )}
            >
              {isActive && (
                <motion.span
                  layoutId="segmented-active"
                  transition={SLIDE}
                  className="absolute inset-0 rounded-[6px] bg-surface-3 shadow-[0_1px_0_rgba(255,255,255,0.04)_inset]"
                  aria-hidden
                />
              )}
              <span className="relative">{opt.label}</span>
              {typeof opt.count === "number" && (
                <span className={cn("num relative text-[10.5px]", isActive ? "text-ink-2" : "text-ink-4")}>{opt.count}</span>
              )}
            </button>
          );
        })}
      </div>
    </LayoutGroup>
  );
}
