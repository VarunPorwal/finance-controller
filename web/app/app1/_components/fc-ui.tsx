"use client";

// Small Finco-styled primitives, used by the pages converted directly in this
// pass (Settlements, Reconcile, Evaluation, Controller Activity). Mirrors the
// shape of ui.tsx but themed with fc- classes from finco-tokens.css.

import { useState, type HTMLAttributes, type MouseEvent, type ReactNode } from "react";
import Link from "next/link";
import { clsx } from "clsx";
import { money, moneyParts } from "../_lib/format";

export type FcTone = "ok" | "warn" | "bad" | "accent" | "neutral";

const toneVar: Record<FcTone, string> = {
  ok: "var(--fc-ok)",
  warn: "var(--fc-warn)",
  bad: "var(--fc-bad)",
  accent: "var(--fc-accent)",
  neutral: "var(--fc-text)",
};

export function FcPage({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("mx-auto w-full max-w-[1440px]", className)} style={{ padding: "20px 26px 40px" }}>{children}</div>;
}

export function FcHead({ title, sub, actions }: { title: ReactNode; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="fc-head">
      <div>
        <h1 style={{ fontSize: 27, fontWeight: 400, letterSpacing: "-0.025em", margin: 0, color: "var(--fc-text)" }}>{title}</h1>
        {sub && <p className="fc-sub">{sub}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function FcCard({
  children,
  className,
  variant,
  ...rest
}: HTMLAttributes<HTMLDivElement> & { variant?: "hero" | "flat" }) {
  return (
    <div
      className={clsx("fc-card", variant === "hero" && "fc-card--hero", variant === "flat" && "fc-card--flat", className)}
      {...rest}
    >
      {children}
    </div>
  );
}

export function FcCardHeader({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4" style={{ padding: "14px 16px 11px" }}>
      <div className="min-w-0">
        <div className="fc-card-title" style={{ display: "block" }}>{title}</div>
        {sub && <div className="fc-label mt-1">{sub}</div>}
      </div>
      {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
    </div>
  );
}

export function FcMoney({
  paise,
  tone = "neutral",
  size = "md",
  whole,
  compact,
  signed,
  className,
}: {
  paise: number;
  tone?: FcTone;
  size?: "sm" | "md" | "lg" | "xl";
  whole?: boolean;
  compact?: boolean;
  signed?: boolean;
  className?: string;
}) {
  const style = { color: toneVar[tone] };
  const prefix = signed && paise > 0 ? "+" : "";
  if (size === "xl" || size === "lg") {
    const [int, frac] = moneyParts(paise);
    return (
      <span
        className={clsx("fc-num", className)}
        style={{ ...style, fontSize: size === "xl" ? 32 : 22, fontWeight: 400, letterSpacing: "-0.02em" }}
      >
        {prefix}
        {compact ? money(paise, { compact: true }) : int}
        {!compact && frac && <span style={{ opacity: 0.45, fontSize: "0.6em" }}>{frac}</span>}
      </span>
    );
  }
  return (
    <span className={clsx("fc-num", className)} style={{ ...style, fontSize: size === "sm" ? 12 : 13 }}>
      {prefix}
      {money(paise, { compact, whole })}
    </span>
  );
}

export function FcChip({ tone, children, className }: { tone?: FcTone; children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx("fc-chip", className)}
      style={tone ? { color: toneVar[tone], background: tone === "neutral" ? undefined : `color-mix(in srgb, ${toneVar[tone]} 14%, transparent)` } : undefined}
    >
      {children}
    </span>
  );
}

export function FcDot({ tone = "neutral" }: { tone?: FcTone }) {
  return <span className="fc-dot" style={{ background: toneVar[tone] }} />;
}

export function FcSkeleton({ className }: { className?: string }) {
  return <div className={clsx("fc-card fc-card--flat animate-pulse", className)} style={{ background: "var(--fc-divider)" }} />;
}

export function FcEmpty({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 text-center" style={{ padding: "48px 24px" }}>
      <div className="fc-strong" style={{ fontSize: 14 }}>{title}</div>
      {sub && <div className="fc-faint" style={{ fontSize: 12.5, maxWidth: 380 }}>{sub}</div>}
    </div>
  );
}

export function FcErrorNote({ message }: { message: string }) {
  return (
    <div
      style={{
        borderRadius: 10,
        border: "1px solid rgba(226,75,74,0.35)",
        background: "rgba(226,75,74,0.1)",
        padding: "8px 12px",
        fontSize: 12.5,
        color: "var(--fc-bad)",
      }}
    >
      {message}
    </div>
  );
}

export function FcSection({ title, sub, children }: { title: ReactNode; sub?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div>
        <div className="fc-card-title" style={{ fontSize: 15, display: "block" }}>{title}</div>
        {sub && <div className="fc-label mt-1">{sub}</div>}
      </div>
      {children}
    </section>
  );
}

export function FcDivider({ className }: { className?: string }) {
  return <div className={clsx("fc-divider", className)} />;
}

const sourceMeta: Record<"razorpay" | "bank" | "ledger", { label: string; color: string }> = {
  razorpay: { label: "Razorpay", color: "var(--fc-accent)" },
  bank: { label: "Bank", color: "var(--fc-warn)" },
  ledger: { label: "Tally", color: "var(--fc-text-3)" },
};

export function FcSourceMark({ source, className }: { source: "razorpay" | "bank" | "ledger"; className?: string }) {
  const { label, color } = sourceMeta[source];
  return (
    <span className={clsx("inline-flex items-center gap-1.5", className)} style={{ color, fontSize: 11.5, fontWeight: 500 }}>
      <span className="h-1.5 w-1.5 rounded-full shrink-0" style={{ background: color }} />
      {label}
    </span>
  );
}

/* ---------- identifier: the one place any long id is rendered ---------- */

/** first4…last4, mono, copy on click. Values ≤12 chars render in full. */
export function Identifier({ value, className }: { value: string | null | undefined; className?: string }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="fc-faint">—</span>;
  const short = value.length <= 12 ? value : `${value.slice(0, 4)}…${value.slice(-4)}`;

  async function copy(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(value!);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — nothing to do, the value is still visible */
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      title={value}
      className={clsx("fc-num", className)}
      style={{
        fontFamily: "var(--fc-mono, var(--fc-font))",
        fontSize: 12,
        fontWeight: 400,
        color: "var(--fc-text-2)",
        background: "transparent",
        border: 0,
        padding: 0,
        cursor: "pointer",
        position: "relative",
      }}
    >
      {copied ? "Copied" : short}
    </button>
  );
}

/* ---------- status: a dot plus gray text, everywhere a status appears ---------- */

export function StatusDot({
  tone = "neutral",
  children,
  className,
  dot = true,
}: {
  tone?: FcTone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}) {
  return (
    <span className={clsx("inline-flex items-center gap-2", className)} style={{ fontSize: 12, color: "var(--fc-text-2)" }}>
      {dot && <span className="fc-dot" style={{ background: toneVar[tone] }} />}
      {children}
    </span>
  );
}

/* ---------- why?: hover affordance on a computed figure ---------- */

export function WhyLabel({ href, onClick, className }: { href?: string; onClick?: () => void; className?: string }) {
  const label = (
    <span
      className={clsx("fc-why-label", className)}
      style={{
        fontSize: 11,
        color: "var(--fc-accent)",
        opacity: 0,
        transition: "opacity 150ms ease",
        marginLeft: 6,
        whiteSpace: "nowrap",
      }}
    >
      Why?
    </span>
  );
  if (href) {
    return (
      <Link href={href} className="fc-why-trigger" onClick={(e) => e.stopPropagation()}>
        {label}
      </Link>
    );
  }
  return (
    <button
      type="button"
      className="fc-why-trigger"
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      style={{ background: "transparent", border: 0, padding: 0, cursor: "pointer" }}
    >
      {label}
    </button>
  );
}

/** Wraps a computed figure so hovering it reveals the Why? label and tints
 * the figure itself accent on hover. Give the figure `fc-why-figure`. */
export function WhyWrap({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={clsx("fc-why-wrap inline-flex items-baseline", className)}>{children}</span>
  );
}

/* ---------- refusal card: section 11, used wherever the engine declines ---------- */

export function RefusalCard({
  reason,
  candidates,
  onConfirm,
  onNeither,
}: {
  reason: string;
  candidates: { label: string; sub: string; amountPaise: number }[];
  onConfirm: (index: number) => void;
  onNeither: () => void;
}) {
  return (
    <FcCard variant="hero">
      <div style={{ fontSize: 16, fontWeight: 500, color: "var(--fc-text)" }}>Only you can choose</div>
      <p className="fc-body mt-1" style={{ fontSize: 13 }}>{reason}</p>
      <div className="mt-4 grid gap-0 md:grid-cols-2" style={{ borderTop: "1px solid var(--fc-divider)" }}>
        {candidates.map((c, i) => (
          <div
            key={i}
            className="flex flex-col gap-2"
            style={{
              padding: "16px 18px",
              borderLeft: i === 1 ? "1px solid var(--fc-divider)" : undefined,
              borderBottom: "1px solid var(--fc-divider)",
            }}
          >
            <div className="fc-label">{c.label}</div>
            <div className="fc-faint" style={{ fontSize: 12 }}>{c.sub}</div>
            <FcMoney paise={c.amountPaise} size="lg" />
            <button className="fc-btn mt-2" onClick={() => onConfirm(i)}>
              Confirm this one
            </button>
          </div>
        ))}
      </div>
      <div className="mt-3 flex justify-end">
        <button className="fc-btn fc-btn--ghost" onClick={onNeither}>
          Neither
        </button>
      </div>
    </FcCard>
  );
}
