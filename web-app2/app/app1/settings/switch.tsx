"use client";

// A toggle switch. Local to Settings; the shared primitives have no switch.

import { motion } from "framer-motion";
import { clsx } from "clsx";

export function Switch({
  checked,
  onChange,
  disabled,
  label,
  id,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label: string;
  id?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full border transition-colors",
        disabled && "cursor-not-allowed opacity-50",
      )}
      style={{
        background: checked ? "var(--a1-brand)" : "var(--a1-surface-4)",
        borderColor: checked ? "var(--a1-brand-2)" : "var(--a1-line-2)",
        boxShadow: "inset 0 1px 2px rgba(0,0,0,0.5)",
        transition: "background 160ms cubic-bezier(0.23,1,0.32,1), border-color 160ms cubic-bezier(0.23,1,0.32,1)",
      }}
    >
      <motion.span
        className="absolute left-0 top-[2px] h-[16px] w-[16px] rounded-full"
        style={{
          background: checked ? "var(--a1-bg)" : "var(--a1-ink-2)",
          boxShadow: "0 1px 2px rgba(0,0,0,0.5)",
        }}
        initial={false}
        animate={{ transform: checked ? "translateX(18px)" : "translateX(2px)" }}
        transition={{ duration: 0.16, ease: [0.23, 1, 0.32, 1] }}
      />
    </button>
  );
}
