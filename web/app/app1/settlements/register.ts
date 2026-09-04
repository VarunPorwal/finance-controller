// The settlement register: one row per Razorpay settlement, with whatever the
// bank and the ledger said about it and who decided. Pure data shaping of
// server rows. The only arithmetic is integer subtotals of server figures for
// display; nothing here reconciles anything.

import type { Exception, MatchResult, TransactionEvent } from "../_lib/api";
import type { Stage } from "../_lib/labels";
import { sumPaise } from "../_lib/format";

export type RowStatus =
  | { kind: "proven"; stage: Stage; confidence: string }
  | { kind: "two_way"; stage: Stage; confidence: string; missing: "bank" | "ledger" }
  | { kind: "held"; stage: Stage; confidence: string }
  | { kind: "rule"; confidence: string; ruleHash: string | null }
  | { kind: "open"; category: Exception["category"]; exceptionId: string; status: Exception["status"] }
  | { kind: "human"; user: string | null; exceptionId: string; how: string | null }
  | { kind: "unmatched" };

export interface RegisterRow {
  settlementId: string;
  /** settled_at when Razorpay states it, else the row date. */
  date: string;
  razorpayPaise: number;
  feePaise: number;
  bankPaise: number | null;
  ledgerPaise: number | null;
  utr: string | null;
  bankDate: string | null;
  voucher: string | null;
  razorpayEvents: TransactionEvent[];
  bankEvents: TransactionEvent[];
  ledgerEvents: TransactionEvent[];
  match: MatchResult | null;
  exceptions: Exception[];
  status: RowStatus;
  /** Razorpay less bank, when both are present. Shown, never decided on. */
  gapPaise: number | null;
  hasGateway: boolean;
  hasBank: boolean;
  hasLedger: boolean;
}

export interface Register {
  rows: RegisterRow[];
  totals: { razorpay: number; bank: number; ledger: number; fees: number };
  counts: {
    settlements: number;
    proven: number;
    rule: number;
    open: number;
    human: number;
    notReceived: number;
    notBooked: number;
  };
  coverage: {
    proof: { count: number; paise: number };
    rule: { count: number; paise: number };
    human: { count: number; paise: number };
  };
  other: { razorpayWithoutSettlement: number; bankUnattached: number; ledgerUnattached: number };
}

const OPEN_STATUSES: ReadonlySet<Exception["status"]> = new Set(["open", "escalated", "monitoring", "snoozed"]);

export function isOpen(e: Pick<Exception, "status">): boolean {
  return OPEN_STATUSES.has(e.status);
}

function signed(e: TransactionEvent): number {
  return e.direction === "credit" ? e.amount_paise : -e.amount_paise;
}

function rowDate(events: TransactionEvent[]): string {
  let best = "";
  for (const e of events) {
    const d = e.settled_at ?? e.txn_date;
    if (d > best) best = d;
  }
  return best;
}

function status(match: MatchResult | null, exceptions: Exception[]): RowStatus {
  const open = exceptions.find(isOpen);
  if (open) return { kind: "open", category: open.category, exceptionId: open.exception_id, status: open.status };
  const human = exceptions.find((e) => e.resolved_by === "human");
  if (human) {
    return {
      kind: "human",
      user: human.resolved_by_user ?? null,
      exceptionId: human.exception_id,
      how: human.resolved_via ?? human.resolution_category ?? null,
    };
  }
  if (!match) return { kind: "unmatched" };
  if (match.stage === "rule") return { kind: "rule", confidence: match.confidence, ruleHash: match.rule_version_hash ?? null };
  const hasBank = match.sources_covered.includes("bank");
  const hasLedger = match.sources_covered.includes("ledger");
  if (hasBank && hasLedger) {
    if (match.auto_closed) return { kind: "proven", stage: match.stage, confidence: match.confidence };
    return { kind: "held", stage: match.stage, confidence: match.confidence };
  }
  return { kind: "two_way", stage: match.stage, confidence: match.confidence, missing: hasBank ? "ledger" : "bank" };
}

export function buildRegister(events: TransactionEvent[], matches: MatchResult[], exceptions: Exception[]): Register {
  const byId = new Map<string, TransactionEvent>();
  for (const e of events) byId.set(e.event_id, e);

  const matchesByEvent = new Map<string, MatchResult[]>();
  for (const m of matches) {
    for (const id of m.event_ids) {
      const list = matchesByEvent.get(id);
      if (list) list.push(m);
      else matchesByEvent.set(id, [m]);
    }
  }
  const exceptionsByEvent = new Map<string, Exception[]>();
  for (const x of exceptions) {
    for (const id of x.event_ids) {
      const list = exceptionsByEvent.get(id);
      if (list) list.push(x);
      else exceptionsByEvent.set(id, [x]);
    }
  }

  const groups = new Map<string, TransactionEvent[]>();
  let razorpayWithoutSettlement = 0;
  for (const e of events) {
    if (e.source !== "razorpay") continue;
    if (!e.settlement_id) {
      razorpayWithoutSettlement++;
      continue;
    }
    const g = groups.get(e.settlement_id);
    if (g) g.push(e);
    else groups.set(e.settlement_id, [e]);
  }

  const attached = new Set<string>();
  const rows: RegisterRow[] = [];

  for (const [settlementId, rp] of groups) {
    const seen = new Set<MatchResult>();
    const seenX = new Set<Exception>();
    for (const e of rp) {
      for (const m of matchesByEvent.get(e.event_id) ?? []) seen.add(m);
      for (const x of exceptionsByEvent.get(e.event_id) ?? []) seenX.add(x);
    }
    // Prefer the match that covers the most sources, then the highest confidence.
    const match =
      [...seen].sort(
        (a, b) => b.sources_covered.length - a.sources_covered.length || Number(b.confidence) - Number(a.confidence),
      )[0] ?? null;

    const bankEvents: TransactionEvent[] = [];
    const ledgerEvents: TransactionEvent[] = [];
    const legIds = new Set<string>();
    for (const m of seen) for (const id of m.event_ids) legIds.add(id);
    for (const x of seenX) for (const id of x.event_ids) legIds.add(id);
    for (const id of legIds) {
      const e = byId.get(id);
      if (!e) continue;
      if (e.source === "bank") bankEvents.push(e);
      else if (e.source === "ledger") ledgerEvents.push(e);
    }
    for (const e of bankEvents) attached.add(e.event_id);
    for (const e of ledgerEvents) attached.add(e.event_id);

    const razorpayPaise = sumPaise(rp.map(signed));
    const feePaise = sumPaise(rp.map((e) => (e.fee_paise ?? 0) + (e.tax_paise ?? 0)));
    const bankPaise = bankEvents.length ? sumPaise(bankEvents.map(signed)) : null;
    const ledgerPaise = ledgerEvents.length ? sumPaise(ledgerEvents.map((e) => e.amount_paise)) : null;
    const bankWithUtr = bankEvents.find((e) => e.utr) ?? bankEvents[0];
    const ledgerWithVoucher = ledgerEvents.find((e) => e.voucher_number) ?? ledgerEvents[0];

    const st = status(match, [...seenX]);
    rows.push({
      settlementId,
      date: rowDate(rp),
      razorpayPaise,
      feePaise,
      bankPaise,
      ledgerPaise,
      utr: bankWithUtr?.utr ?? rp.find((e) => e.utr)?.utr ?? null,
      bankDate: bankWithUtr?.txn_date ?? null,
      voucher: ledgerWithVoucher?.voucher_number ?? null,
      razorpayEvents: rp,
      bankEvents,
      ledgerEvents,
      match,
      exceptions: [...seenX],
      status: st,
      gapPaise: bankPaise === null ? null : razorpayPaise - bankPaise,
      hasGateway: true,
      hasBank: bankEvents.length > 0,
      hasLedger: ledgerEvents.length > 0,
    });
  }

  rows.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.settlementId.localeCompare(b.settlementId)));

  let bankUnattached = 0;
  let ledgerUnattached = 0;
  for (const e of events) {
    if (attached.has(e.event_id)) continue;
    if (e.source === "bank") bankUnattached++;
    else if (e.source === "ledger") ledgerUnattached++;
  }

  const counts = { settlements: rows.length, proven: 0, rule: 0, open: 0, human: 0, notReceived: 0, notBooked: 0 };
  const coverage = {
    proof: { count: 0, paise: 0 },
    rule: { count: 0, paise: 0 },
    human: { count: 0, paise: 0 },
  };
  for (const r of rows) {
    if (!r.hasBank) counts.notReceived++;
    if (!r.hasLedger) counts.notBooked++;
    switch (r.status.kind) {
      case "proven":
        counts.proven++;
        break;
      case "rule":
        counts.rule++;
        break;
      case "open":
        counts.open++;
        break;
      case "human":
        counts.human++;
        break;
    }
    if (r.status.kind === "open") {
      coverage.human.count++;
      coverage.human.paise += r.razorpayPaise;
    } else if (r.match?.stage === "rule") {
      coverage.rule.count++;
      coverage.rule.paise += r.razorpayPaise;
    } else if (r.match?.auto_closed) {
      coverage.proof.count++;
      coverage.proof.paise += r.razorpayPaise;
    }
  }

  return {
    rows,
    totals: {
      razorpay: sumPaise(rows.map((r) => r.razorpayPaise)),
      bank: sumPaise(rows.map((r) => r.bankPaise ?? 0)),
      ledger: sumPaise(rows.map((r) => r.ledgerPaise ?? 0)),
      fees: sumPaise(rows.map((r) => r.feePaise)),
    },
    counts,
    coverage,
    other: { razorpayWithoutSettlement, bankUnattached, ledgerUnattached },
  };
}

export type RegisterFilter = "all" | "not_received" | "not_booked" | "open" | "proven";

export function filterRows(rows: RegisterRow[], f: RegisterFilter): RegisterRow[] {
  switch (f) {
    case "not_received":
      return rows.filter((r) => !r.hasBank);
    case "not_booked":
      return rows.filter((r) => !r.hasLedger);
    case "open":
      return rows.filter((r) => r.status.kind === "open");
    case "proven":
      return rows.filter((r) => r.status.kind === "proven");
    default:
      return rows;
  }
}

function csvCell(v: string | number | null): string {
  if (v === null) return "";
  const s = String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function rupees(paise: number | null): string {
  if (paise === null) return "";
  const sign = paise < 0 ? "-" : "";
  const abs = Math.abs(paise);
  const whole = Math.floor(abs / 100);
  const frac = abs % 100;
  return `${sign}${whole}.${frac < 10 ? "0" : ""}${frac}`;
}

export function statusText(s: RowStatus): string {
  switch (s.kind) {
    case "proven":
      return `Proven · ${s.stage}`;
    case "two_way":
      return `Two-way · ${s.stage} · no ${s.missing}`;
    case "held":
      return `Matched, not closed · ${s.stage}`;
    case "rule":
      return `Rulebook${s.ruleHash ? ` · ${s.ruleHash.slice(0, 8)}` : ""}`;
    case "open":
      return `Open · ${s.category}`;
    case "human":
      return `Human${s.user ? ` · ${s.user}` : ""}`;
    default:
      return "Unmatched";
  }
}

/** Close-pack CSV: one line per settlement, amounts in rupees with paise. */
export function registerCsv(rows: RegisterRow[]): string {
  const header = [
    "settlement_id",
    "date",
    "razorpay_net_inr",
    "fees_and_tax_inr",
    "bank_received_inr",
    "bank_utr",
    "bank_date",
    "tally_booked_inr",
    "tally_voucher",
    "gap_inr",
    "status",
    "stage",
    "confidence",
    "exception_ids",
  ];
  const lines = [header.join(",")];
  for (const r of rows) {
    lines.push(
      [
        r.settlementId,
        r.date,
        rupees(r.razorpayPaise),
        rupees(r.feePaise),
        rupees(r.bankPaise),
        r.utr,
        r.bankDate,
        rupees(r.ledgerPaise),
        r.voucher,
        rupees(r.gapPaise),
        statusText(r.status),
        r.match?.stage ?? null,
        r.match?.confidence ?? null,
        r.exceptions.map((x) => x.exception_id).join(" "),
      ]
        .map(csvCell)
        .join(","),
    );
  }
  return lines.join("\n");
}
