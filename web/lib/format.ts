// Presentation only. CLAUDE.md: "the frontend never computes a financial
// number" - every figure below is already computed server-side as integer
// paise; these functions render that integer, they never derive a new one
// (no rounding, no percentage math, no summing).

/** Integer paise -> "₹5,04,200.00", Indian digit grouping, always 2 decimals. */
export function formatPaise(paise: number): string {
  const rupees = paise / 100;
  const sign = rupees < 0 ? "-" : "";
  const formatted = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(rupees));
  return `${sign}₹${formatted}`;
}

/** Integer paise -> "₹5,04,200", Indian digit grouping, no decimal places -
 * the design handoff's convention for every amount outside the evidence pack. */
export function formatPaiseWhole(paise: number): string {
  const rupees = Math.round(paise / 100);
  const sign = rupees < 0 ? "-" : "";
  const formatted = new Intl.NumberFormat("en-IN", {
    maximumFractionDigits: 0,
  }).format(Math.abs(rupees));
  return `${sign}₹${formatted}`;
}

/** Same as {@link formatPaise} without the currency glyph, for compact contexts. */
export function formatPaiseCompact(paise: number): string {
  const rupees = Math.abs(paise) / 100;
  const sign = paise < 0 ? "-" : "";
  if (rupees >= 10_000_000) return `${sign}${(rupees / 10_000_000).toFixed(2)}Cr`;
  if (rupees >= 100_000) return `${sign}${(rupees / 100_000).toFixed(2)}L`;
  return formatPaise(paise);
}

/** A server-supplied ISO 8601 datetime string, rendered for a header strip. */
export function formatRunTimestamp(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** A duration already computed server-side in milliseconds, e.g. `runtime_ms`. */
export function formatDurationMs(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

export function formatPercent(fraction: number): string {
  return new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 1 }).format(
    fraction,
  );
}

/** A server-supplied Decimal, serialised as a JSON string (e.g. `confidence`,
 * `priority_score`) - parsed for display only, never for a decision. */
export function formatDecimalPercent(value: string): string {
  return formatPercent(Number(value));
}

/** "missing_in_bank" -> "Missing in bank". Category/tier vocabulary is
 * server-defined (PRD §6.8); this only reformats the label for prose. */
export function humanizeSnakeCase(value: string): string {
  const spaced = value.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}


/** ISO date/datetime -> "27 Aug". */
export function formatDateShort(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short" }).format(new Date(iso));
}

/** ISO datetime -> "27 Aug, 14:03". */
export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

/** ISO datetime -> "14:03". */
export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

/** Integer count with Indian grouping. Never a money value. */
export function formatCount(n: number): string {
  return new Intl.NumberFormat("en-IN").format(n);
}

/** The tail of a ULID, for a compact run/exception reference. */
export function shortId(id: string, n = 6): string {
  return id.slice(-n).toUpperCase();
}
