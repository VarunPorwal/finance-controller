"use client";

// Small bits shared across the Run screen's fc- components. Presentation
// only — every number the caller passes in is already a real server field.

import type { CSSProperties, ReactNode } from "react";
import { SOURCE } from "../_lib/labels";
import type { SourceKey } from "./timeline";

export function skel(className: string) {
  return (
    <div
      className={`fc-card fc-card--flat animate-pulse ${className}`}
      style={{ background: "var(--fc-divider)" }}
    />
  );
}

const SOURCE_DOT: Record<SourceKey, string> = {
  razorpay: "var(--fc-accent)",
  bank: "var(--fc-warn)",
  ledger: "var(--fc-text-3)",
};

export function SourceDot({ source, className }: { source: SourceKey; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className ?? ""}`}>
      <span className="fc-dot" style={{ background: SOURCE_DOT[source] }} />
      <span className="fc-label">{SOURCE[source].label}</span>
    </span>
  );
}

/** Inline styles for the two plain form controls the fc component set has no
 * class for. Values are all fc- custom properties; nothing is a literal color. */
export const fieldStyle: CSSProperties = {
  background: "var(--fc-hover)",
  border: "1px solid var(--fc-border)",
  borderRadius: "var(--fc-r-sm)",
  color: "var(--fc-text)",
  fontFamily: "var(--fc-font)",
  fontSize: 12.5,
  padding: "8px 10px",
};

export function SectionHead({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-2 flex items-end justify-between gap-4">
      <div>
        <div className="fc-strong" style={{ fontSize: 14 }}>{title}</div>
        {sub && (
          <div className="fc-faint" style={{ fontSize: 12, marginTop: 2 }}>
            {sub}
          </div>
        )}
      </div>
      {right}
    </div>
  );
}

export function GuardCheck({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-center gap-2.5" style={{ fontSize: 12.5 }}>
      <span
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full"
        style={{ background: "rgba(62,168,43,0.16)", color: "var(--fc-ok)" }}
      >
        <svg width={9} height={9} viewBox="0 0 12 12" fill="none" aria-hidden>
          <path d="M2 6.5 4.8 9.3 10 3" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <span className="fc-muted">{children}</span>
    </li>
  );
}
