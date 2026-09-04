// Pure helpers for the Decisions screen. Nothing here decides anything: it
// groups, sorts and labels server figures for display.

import type { Exception, TransactionEvent } from "../_lib/api";
import { ACTION_GROUP, CATEGORY, type ActionGroup, type Category } from "../_lib/labels";
import { money } from "../_lib/format";

export type View = "todo" | "cause" | "all";
export type StatusFilter = "open" | "resolved" | "all";
export type ClusterMode = { clusterId: string; count: number } | null;

const CLOSED = new Set<Exception["status"]>(["resolved", "written_off", "superseded"]);

const NOT_A_VERB = new Set([
  "the",
  "a",
  "an",
  "this",
  "that",
  "it",
  "no",
  "none",
  "if",
  "when",
  "there",
  "these",
  "those",
  "money",
  "bank",
]);

export function isOpen(e: Exception): boolean {
  return !CLOSED.has(e.status);
}

/** Open and not already closed by the cascade: the only rows that need a person. */
export function needsYou(e: Exception): boolean {
  return isOpen(e) && e.tier !== "auto";
}

export function handledWithoutYou(e: Exception): boolean {
  return e.tier === "auto" || !isOpen(e);
}

export function neverAuto(category: string): boolean {
  return (CATEGORY as Record<string, { neverAuto: boolean }>)[category]?.neverAuto ?? false;
}

export function isCategory(v: string | null): v is Category {
  return !!v && v in CATEGORY;
}

export const GROUP_ORDER: ActionGroup[] = (Object.keys(ACTION_GROUP) as ActionGroup[]).sort(
  (a, b) => ACTION_GROUP[a].order - ACTION_GROUP[b].order,
);

export const CATEGORIES = Object.keys(CATEGORY) as Category[];

/** priority_score is a server Decimal serialised as a string; parsed for ordering only. */
export function priority(e: Exception): number {
  const n = Number(e.priority_score);
  return Number.isNaN(n) ? 0 : n;
}

export function byPriority(a: Exception, b: Exception): number {
  return priority(b) - priority(a);
}

/** "Record the chargeback…" -> "Record". Falls back to "Decide". */
export function firstVerb(action: string): string {
  const word = (action.trim().split(/\s+/)[0] ?? "").replace(/[^A-Za-z-]/g, "");
  if (word.length < 3 || word.length > 12 || NOT_A_VERB.has(word.toLowerCase())) return "Decide";
  return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
}

/** One line under the category, built from what the server already said. */
export function causeLine(e: Exception): string {
  if (e.category === "ambiguous_multi_candidate") return "Several rows could be this. Not chosen.";
  const rules = e.rules_applied ?? [];
  if (rules.length > 0) {
    const last = rules[rules.length - 1];
    return `${money(e.residual_paise)} unexplained after ${last.rule_id} v${last.version}`;
  }
  return e.recommended_action;
}

/**
 * Accept any faithful spelling of the amount the server asked for: 52000,
 * 52,000, 52000.00, ₹52,000.00. String arithmetic only, no float.
 */
export function typedMatches(typed: string, paise: number): boolean {
  const cleaned = typed.replace(/[₹,\s]/g, "");
  if (!/^\d+(\.\d{0,2})?$/.test(cleaned)) return false;
  const [whole, frac = ""] = cleaned.split(".");
  const digits = `${whole}${frac.padEnd(2, "0")}`.replace(/^0+(?=\d)/, "");
  return digits === String(paise);
}

export function toneVar(tone: "bad" | "warn" | "ok" | "model" | "neutral"): string {
  switch (tone) {
    case "bad":
      return "var(--fc-bad)";
    case "warn":
      return "var(--fc-warn)";
    case "ok":
      return "var(--fc-ok)";
    case "model":
      return "var(--fc-accent)";
    default:
      return "var(--fc-text-3)";
  }
}

/** Render-time only: "acme retail pvt ltd" -> "Acme Retail Pvt Ltd". Does not
 * touch the stored/fetched value — callers still pass the raw string to
 * title="" for the untruncated original. */
export function titleCase(s: string): string {
  return s
    .toLowerCase()
    .split(" ")
    .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

/** titleCase, capped at 24 characters with an ellipsis. Pass the raw value to
 * the element's title attribute for the full text on hover. */
export function titleCaseShort(s: string, max = 24): string {
  const t = titleCase(s);
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

/** First non-null identifying reference a raw row carries, in priority order. */
export function eventReference(ev: TransactionEvent): string {
  return ev.utr ?? ev.settlement_id ?? ev.voucher_number ?? ev.order_id ?? ev.rrn ?? ev.source_row_id;
}

/** The first row (in event_ids order) this exception is built from that the
 * caller actually has loaded. Used to show a counterparty/reference on the
 * list row without fabricating a field the exception itself doesn't carry. */
export function firstEvent(e: Exception, eventsById: Map<string, TransactionEvent>): TransactionEvent | undefined {
  for (const id of e.event_ids) {
    const ev = eventsById.get(id);
    if (ev) return ev;
  }
  return undefined;
}
