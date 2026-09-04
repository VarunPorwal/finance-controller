import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** Empty states invite action. Copy says what to do next, never "no data". */
export function EmptyState({
  title,
  note,
  action,
  icon,
  className,
}: {
  title: string;
  note?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-[var(--radius-panel)] border border-dashed border-line-strong bg-surface/60 px-6 py-10 text-center",
        className,
      )}
    >
      {icon && <div className="mb-3 text-ink-3">{icon}</div>}
      <p className="text-[13px] font-semibold text-ink">{title}</p>
      {note && <p className="mt-1 max-w-[46ch] text-[12px] text-ink-3">{note}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
