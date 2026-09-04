"use client";

// Primitives. Every screen composes from these so the surface reads as one
// system. Styles live in app.css under the `.app` scope.

import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { clsx } from "clsx";
import { Info } from "lucide-react";
import { money, moneyParts } from "../_lib/format";

export type Tone = "ok" | "warn" | "bad" | "model" | "brass" | "neutral";

/* ---------- layout ---------- */

export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("mx-auto w-full max-w-[1440px] px-4 pb-16 pt-5 sm:px-6", className)}>{children}</div>;
}

export function PageHeader({
  eyebrow,
  title,
  question,
  actions,
}: {
  eyebrow?: string;
  title: string;
  question?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        {eyebrow && <div className="app-eyebrow mb-1.5">{eyebrow}</div>}
        <h1 className="app-h1">{title}</h1>
        {question && <p className="app-muted mt-1 text-[13px]">{question}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({
  children,
  className,
  hover,
  lit = true,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { hover?: boolean; lit?: boolean }) {
  return (
    <div className={clsx("app-card", hover && "app-card-hover", lit && "app-lit", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  sub,
  right,
  className,
}: {
  title: ReactNode;
  sub?: ReactNode;
  right?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("flex items-start justify-between gap-4 px-5 pt-4 pb-3", className)}>
      <div className="min-w-0">
        <div className="app-h2">{title}</div>
        {sub && <div className="app-faint mt-0.5 text-[12px]">{sub}</div>}
      </div>
      {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
    </div>
  );
}

export function Section({ title, sub, right, children, className }: { title: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={clsx("mb-8", className)}>
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <div className="app-h2">{title}</div>
          {sub && <div className="app-faint mt-0.5 text-[12px]">{sub}</div>}
        </div>
        {right}
      </div>
      {children}
    </section>
  );
}

/* ---------- text ---------- */

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("app-eyebrow", className)}>{children}</div>;
}

export function Mono({ children, className, title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span className={clsx("mono", className)} title={title}>
      {children}
    </span>
  );
}

const toneText: Record<Tone, string> = {
  ok: "text-[var(--app-ok)]",
  warn: "text-[var(--app-warn)]",
  bad: "text-[var(--app-bad)]",
  model: "text-[var(--app-model)]",
  brass: "text-[var(--app-brass)]",
  neutral: "text-[var(--app-ink)]",
};

export function Money({
  paise,
  size = "md",
  tone = "neutral",
  compact,
  whole,
  className,
  signed,
}: {
  paise: number;
  size?: "sm" | "md" | "lg" | "xl";
  tone?: Tone;
  compact?: boolean;
  whole?: boolean;
  className?: string;
  signed?: boolean;
}) {
  if (size === "xl" || size === "lg") {
    const [int, frac] = moneyParts(paise);
    return (
      <span className={clsx(size === "xl" ? "app-money-xl" : "app-money-lg", toneText[tone], className)}>
        {signed && paise > 0 ? "+" : ""}
        {compact ? money(paise, { compact: true }) : int}
        {!compact && frac && <span className="opacity-45" style={{ fontSize: "0.6em" }}>{frac}</span>}
      </span>
    );
  }
  return (
    <span className={clsx("num", size === "sm" ? "text-[12px]" : "text-[13px]", toneText[tone], className)}>
      {signed && paise > 0 ? "+" : ""}
      {money(paise, { compact, whole })}
    </span>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone,
  className,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  className?: string;
  hint?: string;
}) {
  return (
    <div className={clsx("flex flex-col gap-1.5", className)}>
      <div className="app-eyebrow flex items-center gap-1.5">
        {label}
        {hint && (
          <span title={hint} className="app-faint cursor-help">
            <Info size={11} />
          </span>
        )}
      </div>
      <div className={clsx("app-money-lg", tone && toneText[tone])}>{value}</div>
      {sub && <div className="app-faint text-[12px]">{sub}</div>}
    </div>
  );
}

/* ---------- pills ---------- */

export function Pill({ tone = "neutral", children, className, dot }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean }) {
  return (
    <span
      className={clsx(
        "app-pill",
        tone === "ok" && "app-pill-ok",
        tone === "warn" && "app-pill-warn",
        tone === "bad" && "app-pill-bad",
        tone === "model" && "app-pill-model",
        tone === "brass" && "app-pill-brass",
        className,
      )}
    >
      {dot && <span className="app-dot" />}
      {children}
    </span>
  );
}

/* ---------- buttons ---------- */

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "ok" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
};

export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = "default", size = "md", loading, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={clsx(
        "app-btn relative",
        variant === "primary" && "app-btn-primary",
        variant === "ok" && "app-btn-ok",
        variant === "danger" && "app-btn-danger",
        variant === "ghost" && "app-btn-ghost",
        size === "sm" && "app-btn-sm",
        size === "lg" && "app-btn-lg",
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && (
        <span className="absolute inset-0 flex items-center justify-center">
          <Spinner size={13} />
        </span>
      )}
      <span className={clsx("inline-flex items-center gap-1.5", loading && "invisible")}>{children}</span>
    </button>
  );
});

export function IconButton({ active, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return <button className={clsx("app-iconbtn", className)} data-active={active ? "true" : undefined} {...rest} />;
}

export function Spinner({ size = 14, className }: { size?: number; className?: string }) {
  return (
    <svg className={clsx("app-spin", className)} width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="app-kbd">{children}</kbd>;
}

/* ---------- tabs ---------- */

export function Tabs<T extends string>({
  value,
  onChange,
  items,
  id = "tabs",
}: {
  value: T;
  onChange: (v: T) => void;
  items: { value: T; label: ReactNode }[];
  id?: string;
}) {
  return (
    <div className="app-tabs" role="tablist">
      {items.map((it) => (
        <button
          key={it.value}
          role="tab"
          aria-selected={it.value === value}
          className="app-tab"
          data-active={it.value === value ? "true" : undefined}
          onClick={() => onChange(it.value)}
          style={{ position: "relative", zIndex: 0 }}
        >
          {it.value === value && (
            <motion.span layoutId={`${id}-ind`} className="app-tab-ind" transition={{ type: "spring", stiffness: 500, damping: 40 }} />
          )}
          {it.label}
        </button>
      ))}
    </div>
  );
}

/* ---------- states ---------- */

export function Skeleton({ className, lines = 1 }: { className?: string; lines?: number }) {
  return (
    <div className={clsx("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="app-skel h-3.5" style={{ width: `${100 - (i % 3) * 18}%` }} />
      ))}
    </div>
  );
}

export function Empty({ title, sub, action, icon }: { title: string; sub?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon && <div className="app-faint mb-1">{icon}</div>}
      <div className="text-[14px] font-medium">{title}</div>
      {sub && <div className="app-faint max-w-sm text-[12.5px]">{sub}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-[var(--app-bad-line)] bg-[var(--app-bad-soft)] px-3 py-2 text-[12.5px] text-[var(--app-bad)]">
      {message}
    </div>
  );
}

/* ---------- reveal ---------- */

export function Reveal({ children, delay = 0, className }: { children: ReactNode; delay?: number; className?: string; y?: number }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: Math.min(delay, 0.1), ease: [0.23, 1, 0.32, 1] }}
    >
      {children}
    </motion.div>
  );
}

export function Stagger({ children, className, gap = 0.05 }: { children: ReactNode[]; className?: string; gap?: number }) {
  return (
    <AnimatePresence>
      {children.map((c, i) => (
        <motion.div
          key={(c && typeof c === "object" && "key" in c && c.key != null ? String(c.key) : i) as string | number}
          className={className}
          initial={{ opacity: 0, transform: "translateY(6px)" }}
          animate={{ opacity: 1, transform: "translateY(0px)" }}
          transition={{ duration: 0.25, delay: Math.min(i * Math.min(gap, 0.04), 0.24), ease: [0.23, 1, 0.32, 1] }}
        >
          {c}
        </motion.div>
      ))}
    </AnimatePresence>
  );
}

/* ---------- misc ---------- */

export function Divider({ className }: { className?: string }) {
  return <div className={clsx("app-divider", className)} />;
}

export function KeyValue({ rows, className }: { rows: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={clsx("grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[12.5px]", className)}>
      {rows.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="app-faint whitespace-nowrap">{k}</dt>
          <dd className="min-w-0 text-right">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SourceMark({ source, className }: { source: "razorpay" | "bank" | "ledger"; className?: string }) {
  const color =
    source === "razorpay" ? "var(--app-brand)" : source === "bank" ? "var(--app-brass)" : "var(--app-ink-2)";
  const label = source === "razorpay" ? "Razorpay" : source === "bank" ? "Bank" : "Tally";
  return (
    <span className={clsx("inline-flex items-center gap-1.5 text-[11.5px] font-medium", className)} style={{ color }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}
