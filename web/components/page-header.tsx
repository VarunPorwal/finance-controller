import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Facts side by side, separated by hairlines rather than dots. */
export function MetaRow({ items, className }: { items: ReactNode[]; className?: string }) {
  return (
    <span className={cn("meta", className)}>
      {items.filter(Boolean).map((item, i) => (
        <span key={i} className="inline-flex items-center">
          {item}
        </span>
      ))}
    </span>
  );
}

export function PageHeader({
  title,
  sub,
  actions,
  className,
  eyebrow,
}: {
  title: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
  className?: string;
  eyebrow?: ReactNode;
}) {
  return (
    <div className={cn("mb-5 flex flex-wrap items-end justify-between gap-4", className)}>
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5">{eyebrow}</div>}
        <h1 className="text-[22px] leading-none font-semibold tracking-[-0.02em] text-ink">{title}</h1>
        {sub && <p className="mt-2 text-[12.5px] text-ink-3">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
