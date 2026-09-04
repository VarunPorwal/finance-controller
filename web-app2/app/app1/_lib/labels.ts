// Vocabulary the screens speak. Categories, tiers, stages and action groups
// are server-defined (PRD §6.8); this file only says them in a finance
// person's words. Nothing here decides anything.

import type { components } from "@/lib/client";

export type Exception = components["schemas"]["Exception_"];
export type Category = Exception["category"];
export type Tier = Exception["tier"];
export type ActionGroup = Exception["action_group"];
export type Stage = components["schemas"]["MatchResult"]["stage"];
export type Source = components["schemas"]["TransactionEvent"]["source"];

export const CATEGORY: Record<Category, { label: string; short: string; hint: string; neverAuto: boolean }> = {
  missing_in_bank: {
    label: "Not received in bank",
    short: "Not in bank",
    hint: "Razorpay says it settled. The bank statement has no matching credit.",
    neverAuto: false,
  },
  missing_in_gateway: {
    label: "Bank credit with no settlement",
    short: "No settlement",
    hint: "The bank received money that no gateway settlement explains.",
    neverAuto: false,
  },
  missing_in_ledger: {
    label: "Not booked in Tally",
    short: "Not booked",
    hint: "Settled and received, but the ledger has no voucher for it.",
    neverAuto: false,
  },
  duplicate_ledger_entry: {
    label: "Duplicate voucher",
    short: "Duplicate",
    hint: "Two ledger entries for one movement of money. One must be reversed.",
    neverAuto: true,
  },
  chargeback_unrecorded: {
    label: "Chargeback not recorded",
    short: "Chargeback",
    hint: "A dispute was deducted from a settlement but never entered in the books.",
    neverAuto: true,
  },
  partial_refund: {
    label: "Partial refund",
    short: "Partial refund",
    hint: "A refund of part of an order, netted inside a settlement.",
    neverAuto: false,
  },
  nach_batch_unexploded: {
    label: "NACH batch not split",
    short: "NACH batch",
    hint: "One bank line covers many mandates. It cannot be matched until exploded.",
    neverAuto: true,
  },
  timing_lag: {
    label: "Timing",
    short: "Timing",
    hint: "Settled and expected in the bank within the next few days.",
    neverAuto: false,
  },
  ambiguous_multi_candidate: {
    label: "More than one candidate",
    short: "Ambiguous",
    hint: "Several rows could be the match. The system will not pick one.",
    neverAuto: true,
  },
  reference_truncated: {
    label: "Reference cut off",
    short: "Truncated ref",
    hint: "The bank narration was truncated and the UTR is incomplete.",
    neverAuto: false,
  },
  amount_variance: {
    label: "Amount differs",
    short: "Variance",
    hint: "The figures agree on identity but not on amount, after every rule was applied.",
    neverAuto: false,
  },
  unbooked_bank_entry: {
    label: "Bank entry not in books",
    short: "Unbooked",
    hint: "A bank movement the ledger never recorded.",
    neverAuto: false,
  },
  unidentified_inflow: {
    label: "Unidentified inflow",
    short: "Unidentified",
    hint: "Money arrived in the bank and nothing in the gateway or ledger claims it.",
    neverAuto: false,
  },
  revenue_booked_not_settled: {
    label: "Revenue booked, not settled",
    short: "Booked, unsettled",
    hint: "Sales are in the ledger but no settlement has paid them yet.",
    neverAuto: false,
  },
  unknown: {
    label: "Unclassified",
    short: "Unknown",
    hint: "Nothing in the classification tree matched. Always goes to a human.",
    neverAuto: true,
  },
};

export function categoryLabel(c: string): string {
  return (CATEGORY as Record<string, { label: string }>)[c]?.label ?? c.replace(/_/g, " ");
}
export function categoryShort(c: string): string {
  return (CATEGORY as Record<string, { short: string }>)[c]?.short ?? c.replace(/_/g, " ");
}

export const ACTION_GROUP: Record<
  ActionGroup,
  { label: string; blurb: string; tone: "bad" | "warn" | "ok" | "model" | "neutral"; order: number }
> = {
  act_today: {
    label: "Act today",
    blurb: "Money that expires on a date, or a bank credit still missing.",
    tone: "bad",
    order: 0,
  },
  books_fix: {
    label: "Fix the books",
    blurb: "The money moved correctly. Tally needs an entry.",
    tone: "warn",
    order: 1,
  },
  unidentified_inflow: {
    label: "Identify",
    blurb: "Money arrived that nothing claims. Someone knows what it is.",
    tone: "neutral",
    order: 2,
  },
  cannot_resolve: {
    label: "Needs a human",
    blurb: "The system refused to guess. Only you can choose.",
    tone: "model",
    order: 3,
  },
  waiting: {
    label: "Waiting",
    blurb: "Expected to clear on its own. Rechecked automatically.",
    tone: "neutral",
    order: 4,
  },
};

export const TIER: Record<Tier, { label: string; tone: "ok" | "warn" | "bad" }> = {
  auto: { label: "Closed automatically", tone: "ok" },
  monitor: { label: "Monitoring", tone: "warn" },
  escalate: { label: "Needs a decision", tone: "bad" },
};

export const STAGE: Record<Stage, { label: string; short: string; hint: string; mayAutoClose: boolean }> = {
  exact_ref: {
    label: "Exact reference",
    short: "Stage 1",
    hint: "UTR, RRN or settlement id agree exactly.",
    mayAutoClose: true,
  },
  fee_adjusted: {
    label: "Fee adjusted",
    short: "Stage 2",
    hint: "Gross less MDR, GST and TDS equals the bank credit within tolerance.",
    mayAutoClose: true,
  },
  date_shift: {
    label: "Date shift",
    short: "Stage 3",
    hint: "Same amount and reference completion, T+1 to T+3 later.",
    mayAutoClose: true,
  },
  many_to_one: {
    label: "Batch",
    short: "Stage 4",
    hint: "Several settlements sum to one bank credit.",
    mayAutoClose: true,
  },
  fuzzy: {
    label: "Fuzzy",
    short: "Stage 5",
    hint: "Weighted similarity. Capped at 0.75, never closes on its own.",
    mayAutoClose: false,
  },
  rule: {
    label: "Rulebook",
    short: "Rule",
    hint: "A deduction rule explained the gap.",
    mayAutoClose: true,
  },
};

export const STAGE_ORDER: Stage[] = ["exact_ref", "fee_adjusted", "date_shift", "many_to_one", "fuzzy", "rule"];

export const SOURCE: Record<Source, { label: string; short: string; tone: "brand" | "brass" | "ink2" }> = {
  razorpay: { label: "Razorpay settlements", short: "Razorpay", tone: "brand" },
  bank: { label: "Bank statement", short: "Bank", tone: "brass" },
  ledger: { label: "Tally day book", short: "Tally", tone: "ink2" },
};

export const STATUS_LABEL: Record<Exception["status"], string> = {
  open: "Open",
  monitoring: "Monitoring",
  resolved: "Resolved",
  written_off: "Written off",
  snoozed: "Snoozed",
  escalated: "Escalated",
  superseded: "Superseded",
};

/** Who decided. Never "model". */
export function decidedBy(e: Pick<Exception, "resolved_by" | "resolved_by_user" | "rules_applied">): string {
  if (e.resolved_by === "human") return e.resolved_by_user ? `Human · ${e.resolved_by_user}` : "Human";
  if (e.resolved_by === "rule") return "Rulebook";
  if (e.resolved_by === "recheck") return "Recheck";
  if (e.resolved_by === "system") return "Cascade";
  return "Open";
}

export function stageLabel(s: string): string {
  return (STAGE as Record<string, { label: string }>)[s]?.label ?? s;
}

export const AUDIT_ACTION_LABEL: Record<string, string> = {
  "run.complete": "Run completed",
  "run.create": "Run started",
  "run.replay": "Run replayed",
  "exception.resolve": "Resolved",
  "exception.write_off": "Written off",
  "exception.escalate": "Escalated",
  "exception.snooze": "Snoozed",
  "exception.reclassify": "Reclassified",
  "exception.link": "Linked",
  "rule.create": "Rule drafted",
  "rule.activate": "Rule activated",
  "rule.retire": "Rule retired",
  "rule.backtest": "Rule back-tested",
  "rule.version": "Rule versioned",
  "settings.update": "Settings changed",
  "settings.send_run_summary": "Summary emailed",
  "agent.execute": "Instruction executed",
  "cluster.apply": "Applied to cluster",
  "ingest.razorpay": "Razorpay file ingested",
  "ingest.bank": "Bank statement ingested",
  "ingest.ledger": "Tally export ingested",
};

export function auditActionLabel(action: string): string {
  return AUDIT_ACTION_LABEL[action] ?? action.replace(/[._]/g, " ");
}

export function isHumanActor(actor: string): boolean {
  return actor.startsWith("user:");
}
