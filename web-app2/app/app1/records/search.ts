// Search predicates and the "claimed by" index. Pure functions over server
// rows; the only arithmetic is integer paise comparison for an amount query.

import type { Exception, MatchResult, TransactionEvent } from "../_lib/api";
import type { Source } from "../_lib/labels";

export type SourceFilter = "all" | Source;
export type ClaimFilter = "any" | "matched" | "decision" | "unclaimed";
export type ScopeFilter = "any" | "in_scope" | "evidence_only";
export type Scope = "in_scope" | "evidence_only";

export interface Claims {
  matches: Map<string, MatchResult>;
  exceptions: Map<string, Exception>;
}

export function buildClaims(matches: MatchResult[] | undefined, exceptions: Exception[] | undefined): Claims {
  const m = new Map<string, MatchResult>();
  for (const x of matches ?? []) for (const id of x.event_ids) if (!m.has(id)) m.set(id, x);
  const e = new Map<string, Exception>();
  for (const x of exceptions ?? []) {
    for (const id of x.event_ids) {
      const prev = e.get(id);
      // An open decision outranks a closed one for the same row.
      if (!prev || (prev.status !== "open" && x.status === "open")) e.set(id, x);
    }
  }
  return { matches: m, exceptions: e };
}

export interface AmountQuery {
  paise: number;
  exact: boolean;
}

/** "12,345" -> whole-rupee match; "12,345.60" -> exact paise match. */
export function parseAmountQuery(q: string): AmountQuery | null {
  const cleaned = q.replace(/[₹,\s]/g, "");
  const m = /^(\d{1,12})(?:\.(\d{1,2}))?$/.exec(cleaned);
  if (!m) return null;
  const whole = Number(m[1]);
  if (m[2] === undefined) return { paise: whole * 100, exact: false };
  const frac = Number(m[2].padEnd(2, "0"));
  return { paise: whole * 100 + frac, exact: true };
}

const TEXT_FIELDS: (keyof TransactionEvent)[] = [
  "event_id",
  "utr",
  "rrn",
  "settlement_id",
  "order_id",
  "payment_id",
  "voucher_number",
  "counterparty",
  "raw_narration",
];

export function eventMatches(e: TransactionEvent, qLower: string, amount: AmountQuery | null): boolean {
  if (!qLower) return true;
  for (const f of TEXT_FIELDS) {
    const v = e[f];
    if (typeof v === "string" && v.toLowerCase().includes(qLower)) return true;
  }
  if (amount) {
    const abs = Math.abs(e.amount_paise);
    if (amount.exact) return abs === amount.paise;
    return abs - (abs % 100) === amount.paise;
  }
  return false;
}

export function claimState(e: TransactionEvent, claims: Claims): ClaimFilter {
  if (claims.exceptions.has(e.event_id)) return "decision";
  if (claims.matches.has(e.event_id)) return "matched";
  return "unclaimed";
}

/**
 * Whether this row is backed by a bank leg. Gateway and ledger rows are both
 * statements of what should have happened; only a bank leg proves money
 * actually moved (CLAUDE.md: "A match only proves money moved if the bank is
 * one of the sources"). A bank row is definitionally in scope. A razorpay or
 * ledger row is in scope only once matched into a group that also covers
 * bank — otherwise it is evidence only, proven or not.
 */
export function scopeOf(e: TransactionEvent, claims: Claims): Scope {
  if (e.source === "bank") return "in_scope";
  const m = claims.matches.get(e.event_id);
  if (m && m.sources_covered.includes("bank")) return "in_scope";
  return "evidence_only";
}

export interface DateRange {
  from: string | null;
  to: string | null;
}

/** `txn_date` is an ISO "YYYY-MM-DD" string, so lexicographic comparison is
 * chronological comparison. */
export function inDateRange(e: TransactionEvent, range: DateRange): boolean {
  if (range.from && e.txn_date < range.from) return false;
  if (range.to && e.txn_date > range.to) return false;
  return true;
}

/** The most useful single reference for a row. */
export function bestReference(e: TransactionEvent): string | null {
  return e.utr ?? e.rrn ?? e.settlement_id ?? e.voucher_number ?? e.payment_id ?? e.order_id ?? null;
}

/** The narration was cut at ~100 characters upstream and the UTR went with it. */
export function narrationTruncated(e: TransactionEvent): boolean {
  return !e.utr && (e.raw_narration?.length ?? 0) >= 95;
}
