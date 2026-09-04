"use client";

// Local helpers for the Rule Book. Nothing here decides anything: the only
// arithmetic is the ₹10,000 illustration a card draws so a reader can see the
// shape of a deduction stack. Real figures come from /rules/preview and from
// the exceptions the run already wrote. Restyled to the Finco design system
// (`finco-tokens.css`); see `_components/fc-ui.tsx` for the shared primitives.

import { useEffect, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import type { Exception, Rule, S } from "../_lib/api";
import { StatusDot } from "../_components/fc-ui";

export type DeductionIn = S["Deduction-Input"];
export type DeductionOut = S["Deduction-Output"];
export type DeductionType = DeductionIn["type"];
export type DeductionBasis = DeductionIn["basis"];
export type Scope = S["Scope"];

export const DEDUCTION_TYPES: DeductionType[] = [
  "commission",
  "mdr",
  "gst_on_fee",
  "tds_194o",
  "reserve",
  "platform_fee",
  "custom",
];
export const DEDUCTION_BASES: DeductionBasis[] = ["gross", "net", ...DEDUCTION_TYPES];

export const DEDUCTION_LABEL: Record<DeductionType, { label: string; short: string }> = {
  commission: { label: "Commission", short: "Comm." },
  mdr: { label: "MDR", short: "MDR" },
  gst_on_fee: { label: "GST on fee", short: "GST" },
  tds_194o: { label: "TDS 194-O", short: "TDS" },
  reserve: { label: "Rolling reserve", short: "Reserve" },
  platform_fee: { label: "Platform fee", short: "Platform" },
  custom: { label: "Custom", short: "Custom" },
};

export function deductionLabel(t: string): string {
  return (DEDUCTION_LABEL as Record<string, { label: string }>)[t]?.label ?? t.replace(/_/g, " ");
}
export function deductionShort(t: string): string {
  return (DEDUCTION_LABEL as Record<string, { short: string }>)[t]?.short ?? t;
}
export function basisLabel(b: string): string {
  if (b === "gross") return "of gross";
  if (b === "net") return "of running net";
  return `of ${deductionLabel(b)}`;
}

/** "18.00" -> "18%", "0.05" -> "0.05%". The rate is a server string; this only trims zeros. */
export function rateText(rate: string | number): string {
  const n = typeof rate === "number" ? rate : Number(rate);
  if (Number.isNaN(n)) return `${rate}%`;
  return `${n}%`;
}

/** "0.9500" -> "0.95" */
export function confidenceText(c: string): string {
  const n = Number(c);
  return Number.isNaN(n) ? c : n.toFixed(2);
}

/* ---------- illustration ---------- */

export const SAMPLE_GROSS_PAISE = 1_000_000;

export interface IllustratedLine {
  type: string;
  basis: string;
  rate: string;
  amount: number;
}

/**
 * Display-only. Walks the stack over a sample gross so a card can draw it.
 * Integer paise throughout; rounding is the picture's, not the ledger's.
 */
export function illustrate(
  deductions: { type: string; basis: string; rate: string | number; fixed_paise?: number | null }[],
  gross = SAMPLE_GROSS_PAISE,
): { lines: IllustratedLine[]; total: number; net: number } {
  const byType = new Map<string, number>();
  let net = gross;
  let total = 0;
  const lines: IllustratedLine[] = [];
  for (const d of deductions) {
    const basis = d.basis === "gross" ? gross : d.basis === "net" ? net : (byType.get(d.basis) ?? 0);
    const rate = Number(d.rate);
    const fromRate = Number.isNaN(rate) ? 0 : Math.round((basis * rate) / 100);
    const amount = fromRate + (d.fixed_paise ?? 0);
    byType.set(d.type, amount);
    net -= amount;
    total += amount;
    lines.push({ type: d.type, basis: d.basis, rate: String(d.rate), amount });
  }
  return { lines, total, net };
}

/* ---------- usage from the run ---------- */

export interface RuleExample {
  exceptionId: string;
  arithmetic: string | null;
  explainedPaise: number;
}

export interface RuleUsage {
  fired: number;
  explained: number;
  largestResidual: number;
  exceptionIds: string[];
  /** One real instance of this rule firing, for the worked example in the
   * detail panel. `arithmetic` is server text (`RuleApplicationRef.arithmetic`);
   * never assembled client-side. */
  example: RuleExample | null;
}

/** How often each rule_id was cited in this run's exceptions, and what it explained. */
export function ruleUsage(exceptions: Exception[] | undefined): Map<string, RuleUsage> {
  const out = new Map<string, RuleUsage>();
  for (const e of exceptions ?? []) {
    for (const r of e.rules_applied ?? []) {
      const u = out.get(r.rule_id) ?? {
        fired: 0,
        explained: 0,
        largestResidual: 0,
        exceptionIds: [],
        example: null,
      };
      u.fired += 1;
      u.explained += r.explained_paise;
      const residual = Math.abs(e.residual_paise);
      if (residual > u.largestResidual) u.largestResidual = residual;
      u.exceptionIds.push(e.exception_id);
      if (!u.example || (!u.example.arithmetic && r.arithmetic)) {
        u.example = { exceptionId: e.exception_id, arithmetic: r.arithmetic ?? null, explainedPaise: r.explained_paise };
      }
      out.set(r.rule_id, u);
    }
  }
  return out;
}

/* ---------- grouping ---------- */

/** One card per rule_id: the active version if there is one, else the newest. */
export function latestPerRule(rules: Rule[] | undefined): Rule[] {
  const byId = new Map<string, Rule>();
  for (const r of rules ?? []) {
    const cur = byId.get(r.rule_id);
    if (!cur) {
      byId.set(r.rule_id, r);
      continue;
    }
    const curActive = cur.status === "active";
    const rActive = r.status === "active";
    if ((rActive && !curActive) || (rActive === curActive && r.version > cur.version)) byId.set(r.rule_id, r);
  }
  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export const GENERAL = "General";

export function groupLabel(rule: Rule): string {
  return rule.scope.counterparty_matches?.[0] ?? rule.scope.narration_contains?.[0] ?? GENERAL;
}

export function groupRules(rules: Rule[]): [string, Rule[]][] {
  const groups = new Map<string, Rule[]>();
  for (const r of rules) {
    const k = groupLabel(r);
    groups.set(k, [...(groups.get(k) ?? []), r]);
  }
  return [...groups.entries()].sort(([a], [b]) => {
    if (a === GENERAL) return 1;
    if (b === GENERAL) return -1;
    return a.localeCompare(b);
  });
}

/** Rule name / id / counterparty match against a free-text search term. */
export function matchesSearch(rule: Rule, term: string): boolean {
  const t = term.trim().toLowerCase();
  if (!t) return true;
  if (rule.name.toLowerCase().includes(t)) return true;
  if (rule.rule_id.toLowerCase().includes(t)) return true;
  if (rule.scope.counterparty_matches?.some((c) => c.toLowerCase().includes(t))) return true;
  return false;
}

/* ---------- badges ---------- */

export function StatusPill({ status }: { status: Rule["status"] }) {
  if (status === "active") return <StatusDot tone="ok">Active</StatusDot>;
  if (status === "draft") return <StatusDot tone="neutral">Draft</StatusDot>;
  return (
    <StatusDot tone="neutral" className="opacity-60">
      Retired
    </StatusDot>
  );
}

export function OriginPill({ origin }: { origin: Rule["origin"] }) {
  if (origin === "learned") return <StatusDot tone="accent">Learned</StatusDot>;
  if (origin === "imported") return <StatusDot tone="neutral">Imported</StatusDot>;
  return <StatusDot tone="neutral">Manual</StatusDot>;
}

export function scopeLines(scope: Scope): [string, string][] {
  const rows: [string, string][] = [];
  if (scope.rule_set) rows.push(["Rule set", scope.rule_set]);
  if (scope.counterparty_matches?.length) rows.push(["Counterparty", scope.counterparty_matches.join(", ")]);
  if (scope.narration_contains?.length) rows.push(["Narration contains", scope.narration_contains.join(", ")]);
  if (scope.source) rows.push(["Source", scope.source]);
  if (scope.rail) rows.push(["Rail", scope.rail.toUpperCase()]);
  if (scope.method) rows.push(["Method", scope.method]);
  return rows;
}

/* ---------- slide-over panel, themed for Finco ---------- */

export function FcPanel({
  open,
  onClose,
  title,
  sub,
  width = 640,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  sub?: ReactNode;
  width?: number;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="scrim"
            className="fixed inset-0 z-40"
            style={{ background: "rgba(0,0,0,0.55)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={onClose}
          />
          <motion.aside
            key="panel"
            className="fc-card fixed right-3 top-3 bottom-3 z-50 flex flex-col overflow-hidden"
            style={{ width: `min(${width}px, calc(100vw - 24px))`, borderRadius: 16, padding: 0 }}
            initial={{ transform: "translateX(24px)", opacity: 0 }}
            animate={{ transform: "translateX(0px)", opacity: 1, transition: { duration: 0.22, ease: [0.32, 0.72, 0, 1] } }}
            exit={{ transform: "translateX(24px)", opacity: 0, transition: { duration: 0.12, ease: [0.23, 1, 0.32, 1] } }}
            role="dialog"
            aria-modal
          >
            <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
              <div className="min-w-0">
                <div className="fc-card-title truncate" style={{ display: "block" }}>
                  {title}
                </div>
                {sub && <div className="fc-label mt-1">{sub}</div>}
              </div>
              <button
                className="fc-btn fc-btn--ghost shrink-0"
                style={{ padding: "6px 8px" }}
                onClick={onClose}
                aria-label="Close"
              >
                <X size={15} />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto" style={{ overscrollBehavior: "contain" }}>
              {children}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
