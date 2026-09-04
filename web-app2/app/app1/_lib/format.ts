// Presentation only. Every figure arrives as integer paise computed
// server-side; these functions render, they never derive a financial number.
// The one arithmetic allowed here is integer addition for a band subtotal,
// which is a display grouping of server figures, not a decision.

export {
  formatPaise,
  formatPaiseWhole,
  formatPaiseCompact,
  formatDurationMs,
  formatPercent,
  formatDecimalPercent,
  formatDateShort,
  formatDateTime,
  formatTime,
  formatCount,
  shortId,
  humanizeSnakeCase,
} from "@/lib/format";

/** "₹1,23,456" for headline use; falls back to lakh/crore above 10L. */
export function money(paise: number, opts: { compact?: boolean; whole?: boolean } = {}): string {
  const rupees = Math.abs(paise) / 100;
  const sign = paise < 0 ? "−" : "";
  if (opts.compact && rupees >= 1_000_000) {
    if (rupees >= 10_000_000) return `${sign}₹${(rupees / 10_000_000).toFixed(2)} Cr`;
    return `${sign}₹${(rupees / 100_000).toFixed(2)} L`;
  }
  const n = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: opts.whole ? 0 : 2,
    maximumFractionDigits: opts.whole ? 0 : 2,
  }).format(opts.whole ? Math.round(rupees) : rupees);
  return `${sign}₹${n}`;
}

/** Split a money string into integer and fraction parts so the paise can be
 * set smaller. Returns [ "₹1,23,456", ".78" ]. */
export function moneyParts(paise: number): [string, string] {
  const s = money(paise);
  const i = s.lastIndexOf(".");
  if (i === -1) return [s, ""];
  return [s.slice(0, i), s.slice(i)];
}

/** Integer sum of server figures for a display subtotal. */
export function sumPaise(values: number[]): number {
  let total = 0;
  for (const v of values) total += v;
  return total;
}

/** "0.9400" -> "94%" */
export function pct(decimal: string | number | null | undefined, digits = 0): string {
  if (decimal === null || decimal === undefined) return "—";
  const n = typeof decimal === "string" ? Number(decimal) : decimal;
  if (Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

/** A server percentage already in 0–100 ("98.39%" or "1.000" meaning 100%)
 * is handled by the caller; this is for 0–1 fractions only. */

export function daysBetween(fromIso: string, toIso: string): number {
  const a = new Date(fromIso).getTime();
  const b = new Date(toIso).getTime();
  return Math.round((b - a) / 86_400_000);
}

export function relativeDays(deadlineIso: string | null | undefined, asOfIso: string): string {
  if (!deadlineIso) return "";
  const d = daysBetween(asOfIso, deadlineIso);
  if (d < 0) return `${Math.abs(d)}d overdue`;
  if (d === 0) return "due today";
  if (d === 1) return "due tomorrow";
  return `${d}d left`;
}

export function formatDateLong(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "long", year: "numeric" }).format(
    new Date(iso),
  );
}

export function formatMonth(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" }).format(new Date(iso));
}

export function hashShort(h: string | null | undefined, n = 8): string {
  if (!h) return "—";
  return h.slice(0, n);
}

export function bytes(n: number): string {
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
