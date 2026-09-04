import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * The one card shape. Header row (title, optional sub-line, optional
 * actions) over a body. `flush` drops the body padding for tables.
 */
export function Panel({
  title,
  sub,
  actions,
  children,
  className,
  bodyClassName,
  flush,
  tone = "default",
}: {
  title?: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
  flush?: boolean;
  tone?: "default" | "raised" | "model";
}) {
  const shell = tone === "model" ? "panel-model" : tone === "raised" ? "panel-raised" : "panel";
  return (
    <section className={cn(shell, "overflow-hidden", className)}>
      {(title || actions) && (
        <header
          className={cn(
            "flex items-start justify-between gap-3 px-[18px] pt-4",
            flush ? "border-b border-line pb-3.5" : "pb-1",
          )}
        >
          <div className="min-w-0">
            {title && (
              <h2 className={cn("text-[13px] font-semibold", tone === "model" ? "text-model" : "text-ink")}>
                {title}
              </h2>
            )}
            {sub && <p className="mt-0.5 text-[11.5px] text-ink-3">{sub}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn(flush ? "" : "px-[18px] pt-3 pb-[18px]", bodyClassName)}>{children}</div>
    </section>
  );
}
