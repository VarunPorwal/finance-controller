"use client";

import { cn } from "@/lib/utils";

export function FilterPills({
  options,
  active,
  onChange,
}: {
  options: { value: string; label: string }[];
  active: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="mb-4 flex gap-2">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "cursor-pointer rounded-[7px] px-3.5 py-1.5 text-[12.5px] whitespace-nowrap",
            opt.value === active
              ? "bg-primary-tint font-semibold text-primary-active-text"
              : "border border-border font-medium text-text-body",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
