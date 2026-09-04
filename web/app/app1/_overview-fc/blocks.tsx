"use client";

// Overview, matching the Finco card composition: metric row, a day-by-day
// unmatched chart, an agent narrative banner, a cash-position rail and a
// needs-a-decision list. Every figure below reads an existing server field —
// nothing here derives a financial number beyond simple sums/grouping of
// server integers (CLAUDE.md hard rules 1 and 5).

import { useMemo, useState } from "react";
import Link from "next/link";
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Sparkles, Wallet } from "lucide-react";
import {
  useMatches,
  useNarrative,
  useRunDiff,
  useRuns,
  type Exception,
  type MatchResult,
  type RunOut,
} from "../_lib/api";
import { categoryLabel, type Category } from "../_lib/labels";
import { formatCount, formatDateTime, money, sumPaise } from "../_lib/format";
import { CountUp } from "../_components/motion";
import { Identifier, StatusDot, WhyLabel, WhyWrap } from "../_components/fc-ui";

function asAt(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" }).format(d);
}

function skel(className: string) {
  return <div className={`fc-skel ${className}`} />;
}

// Highlights numeric/currency tokens inside free-text narrative (e.g. "₹1,24,500",
// "42", "18%") in the theme's strong text color so figures stand out from the
// dimmer surrounding prose, in both light and dark theme.
const NUMBER_TOKEN = /(₹?\s?[\d,]*\d(?:\.\d+)?%?)/g;

function highlightNumbers(text: string) {
  return text.split(NUMBER_TOKEN).map((part, i) =>
    /\d/.test(part) ? (
      <span key={i} className="fc-num" style={{ color: "var(--fc-text)" }}>
        {part}
      </span>
    ) : (
      part
    ),
  );
}

/* ---------- header ---------- */

export function OverviewHeader({ run }: { run: RunOut | null }) {
  return (
    <div className="mb-3 flex items-baseline justify-between">
      <h1 className="fc-title" style={{ fontSize: 32, fontWeight: 400 }}>
        Overview
        {run && (
          <span className="fc-faint inline-flex items-baseline gap-1.5" style={{ fontSize: 15, marginLeft: 10 }}>
            · Run <Identifier value={run.run_id} /> · {formatDateTime(run.started_at)}
          </span>
        )}
      </h1>
    </div>
  );
}

/* ---------- sub-bar: reconciled sentence + New run ---------- */

export function SubBar({
  reconciledPct,
  asOfIso,
}: {
  reconciledPct: number | undefined;
  asOfIso: string | null | undefined;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-4">
      {reconciledPct === undefined ? (
        skel("h-5 w-[46%]")
      ) : (
        <p className="fc-body flex items-center gap-2" style={{ fontSize: 14.5 }}>
          <span className="fc-dot fc-dot--accent" />
          Books are{" "}
          <WhyWrap>
            <span className="fc-num fc-strong fc-why-figure">{(reconciledPct * 100).toFixed(0)}%</span>
            <WhyLabel href="/app1/cash" />
          </WhyWrap>{" "}
          reconciled by value for the cycle ending {asAt(asOfIso)}.
        </p>
      )}
      <Link href="/app1/run" className="fc-btn shrink-0">
        New run
      </Link>
    </div>
  );
}

/* ---------- tiles ---------- */

function Tile({
  icon,
  label,
  value,
  numeric,
  sub,
  bar,
  href,
  loading,
  index,
  whyHref,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  numeric?: { value: number; format: (n: number) => string };
  sub?: React.ReactNode;
  bar?: number;
  href?: string;
  loading?: boolean;
  index: number;
  whyHref?: string;
}) {
  const valueStyle: React.CSSProperties = {
    fontSize: 22,
    fontWeight: 500,
    letterSpacing: "-0.01em",
    color: "var(--fc-text)",
    fontFamily: "var(--fc-mono, var(--fc-font))",
  };
  const valueNode = numeric ? <CountUp value={numeric.value} format={numeric.format} duration={0.9} /> : value;
  const body = (
    <div className={`fc-card h-full${href ? " fc-card-hover" : ""}`}>
      <div className="flex items-center justify-between">
        <div className="fc-label">{label}</div>
        <span className="fc-faint">{icon}</span>
      </div>
      {loading ? (
        skel("mt-2 h-6 w-24")
      ) : whyHref ? (
        <WhyWrap className="mt-1.5">
          <span className="fc-num fc-why-figure" style={valueStyle}>
            {valueNode}
          </span>
          <WhyLabel href={whyHref} />
        </WhyWrap>
      ) : (
        <div className="fc-num mt-1.5" style={valueStyle}>
          {valueNode}
        </div>
      )}
      {bar !== undefined && !loading && (
        <div className="fc-bar mt-2">
          <span style={{ width: `${Math.max(0, Math.min(100, bar * 100))}%` }} />
        </div>
      )}
      {sub && !loading && <div className="mt-1" style={{ fontSize: 12.5 }}>{sub}</div>}
    </div>
  );
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2, delay: index * 0.04 }}>
      {href ? (
        <Link href={href} className="block">
          {body}
        </Link>
      ) : (
        body
      )}
    </motion.div>
  );
}

export function Tiles({
  totalCash,
  asOfIso,
  reconciledPct,
  reconciledDeltaPct,
  openCount,
  openSubtotal,
  autoResolvedCount,
}: {
  totalCash: number | undefined;
  asOfIso: string | null | undefined;
  reconciledPct: number | undefined;
  reconciledDeltaPct: number | null | undefined;
  openCount: number | undefined;
  openSubtotal: number | undefined;
  autoResolvedCount: number | undefined;
}) {
  return (
    <div className="fc-row4 mb-3">
      <Tile
        index={0}
        icon={<Wallet size={14} />}
        label="Total cash"
        value={totalCash !== undefined ? money(totalCash, { compact: true }) : undefined}
        numeric={totalCash !== undefined ? { value: totalCash, format: (n) => money(Math.round(n), { compact: true }) } : undefined}
        sub={<span className="fc-faint">as at {asAt(asOfIso)}</span>}
        loading={totalCash === undefined}
      />
      <Tile
        index={1}
        icon={<CheckCircle2 size={14} />}
        label="Reconciled"
        value={reconciledPct !== undefined ? `${(reconciledPct * 100).toFixed(1)}%` : undefined}
        numeric={reconciledPct !== undefined ? { value: reconciledPct * 100, format: (n) => `${n.toFixed(1)}%` } : undefined}
        whyHref="/app1/cash"
        bar={reconciledPct}
        sub={
          reconciledDeltaPct !== undefined && reconciledDeltaPct !== null ? (
            <span style={{ color: reconciledDeltaPct >= 0 ? "var(--fc-ok)" : "var(--fc-bad)" }}>
              {reconciledDeltaPct >= 0 ? "+" : ""}
              {(reconciledDeltaPct * 100).toFixed(1)}% vs last run
            </span>
          ) : undefined
        }
        loading={reconciledPct === undefined}
      />
      <Tile
        index={2}
        icon={<AlertTriangle size={14} />}
        label="Exceptions"
        value={openCount !== undefined ? formatCount(openCount) : undefined}
        numeric={openCount !== undefined ? { value: openCount, format: (n) => formatCount(Math.round(n)) } : undefined}
        sub={openSubtotal !== undefined ? <span className="fc-faint">{money(openSubtotal)} unmatched</span> : undefined}
        href="/app1/decisions"
        loading={openCount === undefined}
      />
      <Tile
        index={3}
        icon={<Sparkles size={14} />}
        label="Reviewed by Finco"
        value={autoResolvedCount !== undefined ? formatCount(autoResolvedCount) : undefined}
        numeric={autoResolvedCount !== undefined ? { value: autoResolvedCount, format: (n) => formatCount(Math.round(n)) } : undefined}
        sub={<span className="fc-faint">Matched without a human</span>}
        href="/app1/controller-activity"
        loading={autoResolvedCount === undefined}
      />
    </div>
  );
}

/* ---------- unmatched value by day ---------- */

export function UnmatchedByDay({
  exceptions,
  asOfIso,
  index = 0,
}: {
  exceptions: Exception[] | undefined;
  asOfIso: string;
  index?: number;
}) {
  const days = useMemo(() => {
    if (!exceptions) return null;
    const asOf = new Date(asOfIso);
    const buckets: { key: string; label: string; paise: number }[] = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date(asOf);
      d.setDate(d.getDate() - i);
      const key = d.toISOString().slice(0, 10);
      const label = i === 0 ? "Today" : new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short" }).format(d);
      buckets.push({ key, label, paise: 0 });
    }
    const byKey = new Map(buckets.map((b) => [b.key, b]));
    for (const e of exceptions) {
      const key = e.created_at.slice(0, 10);
      const bucket = byKey.get(key);
      if (bucket) bucket.paise += e.amount_paise;
    }
    return buckets;
  }, [exceptions, asOfIso]);

  const total = days ? sumPaise(days.map((d) => d.paise)) : 0;
  const isEmpty = days !== null && total === 0;
  const max = days ? Math.max(1, ...days.map((d) => d.paise)) : 1;

  return (
    <motion.div
      className="fc-card flex h-full flex-col"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: index * 0.04 }}
    >
      <div className="shrink-0">
        <div className="fc-card-title mb-1" style={{ fontSize: 16 }}>Unmatched value by day</div>
        <div className="fc-label mb-2" style={{ fontSize: 12 }}>Open exceptions raised each day, last 7 days</div>
      </div>
      {!days ? (
        skel("h-32 w-full")
      ) : isEmpty ? (
        <div className="flex flex-1 items-center justify-center" style={{ minHeight: 132 }}>
          <span className="fc-faint" style={{ fontSize: 12.5 }}>No exceptions raised in the last seven days.</span>
        </div>
      ) : (
        <div className="flex flex-1 flex-col gap-2">
          <div className="flex min-h-0 flex-1 gap-2">
            <div
              className="fc-faint fc-num flex shrink-0 flex-col justify-between"
              style={{ width: 40, fontSize: 10.5, paddingBottom: 2, textAlign: "right" }}
            >
              <span>{money(max, { compact: true })}</span>
              <span>₹0</span>
            </div>
            <div className="min-w-0 flex-1">
              <div className="fc-chart" style={{ height: "100%", marginTop: 0 }}>
                {days.map((d, i) => (
                  <div
                    key={d.key}
                    className={i === days.length - 1 ? "is-peak" : undefined}
                    style={{ height: `${Math.max(4, (d.paise / max) * 100)}%` }}
                    title={`${d.label}: ${money(d.paise)}`}
                  />
                ))}
              </div>
            </div>
          </div>
          <div className="fc-xaxis" style={{ marginTop: 0, paddingLeft: 48 }}>
            {days.map((d) => (
              <span key={d.key}>{d.label}</span>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  );
}

/* ---------- agent narrative banner ---------- */

export function AgentBanner({ run, index = 0 }: { run: RunOut; index?: number }) {
  const q = useNarrative(run.run_id);
  const [dismissed, setDismissed] = useState(false);

  // The old "N new · N cleared · N closed" line used to float under this card
  // on its own; it belongs to the same story the narrative tells, so it now
  // lives in this card's footer instead (CLAUDE.md-adjacent design brief §14).
  const runs = useRuns("original", 5);
  const matches = useMatches(run.run_id);
  const prev = (runs.data ?? [])
    .filter((r) => r.run_id !== run.run_id && r.started_at < run.started_at && r.finished_at !== null)
    .sort((a, b) => (a.started_at < b.started_at ? 1 : a.started_at > b.started_at ? -1 : 0))[0];
  const diff = useRunDiff(prev?.run_id, run.run_id);
  const autoClosed = matches.data ? matches.data.filter((m) => m.auto_closed).length : undefined;

  if (dismissed || !q.data) return null;

  const minutesAgo = run.finished_at
    ? Math.max(0, Math.round((Date.now() - new Date(run.finished_at).getTime()) / 60000))
    : null;

  const footer = !prev ? (
    <span className="fc-faint">First run for this tenant. There is nothing earlier to compare against.</span>
  ) : !diff.data || autoClosed === undefined ? (
    skel("h-3.5 w-56")
  ) : (
    <span className="fc-faint">
      <span className="fc-num" style={{ color: "var(--fc-text)" }}>{formatCount(diff.data.diff.added.length)}</span> new ·{" "}
      <span className="fc-num" style={{ color: "var(--fc-text)" }}>{formatCount(diff.data.diff.removed.length)}</span> cleared since last run ·{" "}
      <span className="fc-num" style={{ color: "var(--fc-text)" }}>{formatCount(autoClosed)}</span> closed on evidence alone
    </span>
  );

  return (
    <motion.div
      className="fc-card fc-card--hero flex flex-col"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: index * 0.04 }}
      style={{ minHeight: 150 }}
    >
      <div className="flex h-full items-start gap-3">
        <span
          className="flex shrink-0 items-center justify-center"
          style={{ width: 28, height: 28, borderRadius: 8, background: "var(--fc-accent-dim)", color: "var(--fc-accent)" }}
        >
          <Sparkles size={15} />
        </span>
        <div className="flex h-full min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between gap-2">
            <div className="fc-card-title" style={{ fontSize: 16 }}>The run, in words</div>
            {minutesAgo !== null && <span className="fc-chip">{minutesAgo <= 1 ? "just now" : `${minutesAgo} min ago`}</span>}
          </div>
          <p className="fc-body mt-1.5" style={{ whiteSpace: "pre-line", fontSize: 13 }}>
            {highlightNumbers(q.data.narrative)}
          </p>
          <div className="mt-3 flex gap-2">
            <Link href="/app1/decisions" className="fc-btn fc-btn--light">
              Review exceptions
            </Link>
            <button className="fc-btn fc-btn--ghost" onClick={() => setDismissed(true)}>
              Dismiss
            </button>
          </div>
          <div className="mt-auto flex pt-3" style={{ borderTop: "1px solid var(--fc-divider)", fontSize: 12.5 }}>
            {footer}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

/* ---------- cash position ---------- */

export function CashPosition({
  balance,
  inflow,
  outflow,
  index = 0,
}: {
  balance: number | undefined;
  inflow: number | undefined;
  outflow: number | undefined;
  index?: number;
}) {
  const loading = balance === undefined || inflow === undefined || outflow === undefined;
  const projected = loading ? undefined : balance + inflow - outflow;
  return (
    <motion.div
      className="fc-card"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: index * 0.04 }}
    >
      <div className="fc-card-title mb-2" style={{ fontSize: 16 }}>Cash position</div>
      {loading ? (
        skel("h-24 w-full")
      ) : (
        <div className="flex flex-col gap-2.5">
          <div className="flex items-baseline justify-between">
            <span className="fc-label">Current balance</span>
            <span className="fc-num fc-strong" style={{ fontSize: 16.5, fontWeight: 600 }}>{money(balance, { compact: true })}</span>
          </div>
          <div className="flex items-baseline justify-between" style={{ fontSize: 13 }}>
            <span className="flex items-center gap-1.5 fc-muted">
              <span className="fc-dot fc-dot--ok" /> Expected inflow
            </span>
            <span className="fc-num" style={{ color: "var(--fc-ok)" }}>+{money(inflow, { compact: true })}</span>
          </div>
          <div className="flex items-baseline justify-between" style={{ fontSize: 13 }}>
            <span className="flex items-center gap-1.5 fc-muted">
              <span className="fc-dot fc-dot--bad" /> Expected outflow
            </span>
            <span className="fc-num" style={{ color: outflow > 0 ? "var(--fc-bad)" : "var(--fc-text-3)" }}>
              {outflow > 0 ? `−${money(outflow, { compact: true })}` : "—"}
            </span>
          </div>
          <div className="fc-divider my-0.5" />
          <div className="flex items-baseline justify-between">
            <span className="fc-label">Projected close</span>
            <span className="fc-num" style={{ fontSize: 15.5, fontWeight: 600, color: "var(--fc-accent)" }}>
              {money(projected!, { compact: true })}
            </span>
          </div>
        </div>
      )}
    </motion.div>
  );
}

/* ---------- needs a decision ---------- */

function NeedsRow({ e, counterparty }: { e: Exception; counterparty: string | undefined }) {
  const dotTone = e.action_group === "act_today" || e.action_group === "cannot_resolve" ? "fc-dot--bad" : "fc-dot--warn";
  const cause = e.consequence ?? categoryLabel(e.category);
  return (
    <Link href={`/app1/decisions?open=${encodeURIComponent(e.exception_id)}`} className="block">
      <div className="flex items-start justify-between gap-3 py-2">
        <div className="flex min-w-0 items-start gap-2">
          <span className={`fc-dot ${dotTone}`} style={{ marginTop: 5 }} />
          <div className="min-w-0">
            <div className="truncate" style={{ fontSize: 13.5, color: "var(--fc-text)" }}>{categoryLabel(e.category)}</div>
            <div className="fc-faint truncate" style={{ fontSize: 11.5, maxWidth: 190 }} title={cause}>
              {counterparty ?? cause}
            </div>
          </div>
        </div>
        <span className="fc-num fc-strong shrink-0" style={{ fontSize: 13.5 }}>{money(e.amount_paise, { compact: true })}</span>
      </div>
    </Link>
  );
}

export function NeedsDecision({
  items,
  counterpartyOf,
  index = 0,
}: {
  items: Exception[] | undefined;
  counterpartyOf: (e: Exception) => string | undefined;
  index?: number;
}) {
  return (
    <motion.div
      className="fc-card flex flex-col"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: index * 0.04 }}
    >
      <div className="flex shrink-0 items-center justify-between">
        <div className="fc-card-title" style={{ fontSize: 16 }}>Needs a decision</div>
        <Link href="/app1/decisions" className="fc-link">View all</Link>
      </div>
      {!items ? (
        <div className="mt-2 flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <div key={i}>{skel("h-8 w-full")}</div>
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="fc-faint mt-2" style={{ fontSize: 12 }}>Nothing is open.</div>
      ) : (
        <div className="mt-1 divide-y" style={{ borderColor: "var(--fc-divider)" }}>
          {items.map((e) => (
            <NeedsRow key={e.exception_id} e={e} counterparty={counterpartyOf(e)} />
          ))}
        </div>
      )}
    </motion.div>
  );
}

/* ---------- three-source trace ----------
 * Real row counts come from /api/v1/events/count (useEventsCount), grouped by
 * source server-side. A pairwise "matched" count is the number of MatchResult
 * rows whose sources_covered includes both sources of that pair (server
 * field, not derived). The "gap" count for Razorpay↔Bank is open exceptions
 * categorised missing_in_bank or missing_in_gateway; for Bank↔Tally it is
 * missing_in_ledger — the categories CLAUDE.md documents as mapping to a
 * missing leg between exactly those sources. Razorpay↔Tally has no such
 * single-category mapping, so that pair renders no gap figure at all rather
 * than a guessed one. */

type SourceKey = "razorpay" | "bank" | "ledger";

const SOURCE_LABEL: Record<SourceKey, string> = { razorpay: "Razorpay", bank: "Bank", ledger: "Tally" };

function SourceBlock({ label, count, index }: { label: string; count: number | undefined; index: number }) {
  return (
    <motion.div
      className="min-w-0 flex-1"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: index * 0.08 }}
    >
      <Link href="/app1/records" className="fc-card-hover block" style={{ borderRadius: "var(--fc-r-sm)", padding: "10px 14px" }}>
        <StatusDot tone={count !== undefined && count > 0 ? "ok" : "neutral"}>{label}</StatusDot>
        <div
          className="fc-num mt-1.5"
          style={{ fontSize: 22, fontWeight: 500, fontFamily: "var(--fc-mono, var(--fc-font))", color: "var(--fc-text)" }}
        >
          {count === undefined ? skel("inline-block h-6 w-12") : <CountUp value={count} format={(n) => formatCount(Math.round(n))} duration={0.9} />}
        </div>
        <div className="fc-faint" style={{ fontSize: 11 }}>rows ingested</div>
      </Link>
    </motion.div>
  );
}

function SourceConnector({
  matched,
  gap,
  href,
  index,
}: {
  matched: number | undefined;
  gap: number | undefined;
  href: string;
  index: number;
}) {
  const ready = matched !== undefined && gap !== undefined;
  const hasGap = ready && gap! > 0;
  const lineColor = !ready ? "var(--fc-divider)" : hasGap ? "var(--fc-bad)" : "var(--fc-accent-dim)";
  return (
    <motion.div
      className="flex shrink-0 flex-col items-center justify-center"
      style={{ width: 108, padding: "0 4px" }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: 0.16 + index * 0.08 }}
    >
      <Link href={href} className="flex w-full flex-col items-center gap-1.5" style={{ textDecoration: "none" }}>
        <span className="fc-num fc-faint" style={{ fontSize: 10.5 }}>
          {ready ? `${formatCount(matched!)} matched` : "…"}
        </span>
        <motion.span
          style={{ display: "block", width: "100%", height: 2, borderRadius: 1, background: lineColor, transformOrigin: "left" }}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: ready ? 1 : 0 }}
          transition={{ duration: 0.4, delay: 0.3 + index * 0.08 }}
        />
        <span className="fc-num" style={{ fontSize: 10.5, color: hasGap ? "var(--fc-bad)" : "var(--fc-text-3)" }}>
          {ready ? (hasGap ? `${formatCount(gap!)} gap` : "in sync") : ""}
        </span>
      </Link>
    </motion.div>
  );
}

export function SourceTrace({
  bySource,
  matches,
  openExceptions,
}: {
  bySource: Record<string, number> | undefined;
  matches: MatchResult[] | undefined;
  openExceptions: Exception[] | undefined;
}) {
  function pair(a: SourceKey, b: SourceKey, gapCategories: Category[]) {
    const matched = matches ? matches.filter((m) => m.sources_covered.includes(a) && m.sources_covered.includes(b)).length : undefined;
    const gap = openExceptions ? openExceptions.filter((e) => gapCategories.includes(e.category)).length : undefined;
    return { matched, gap };
  }

  const razorpayBank = pair("razorpay", "bank", ["missing_in_bank", "missing_in_gateway"]);
  const bankLedger = pair("bank", "ledger", ["missing_in_ledger"]);

  return (
    <div className="fc-card mb-3">
      <div className="fc-card-title mb-3" style={{ fontSize: 16 }}>Three sources, one truth</div>
      <div className="flex items-center">
        <SourceBlock label={SOURCE_LABEL.razorpay} count={bySource?.razorpay} index={0} />
        <SourceConnector matched={razorpayBank.matched} gap={razorpayBank.gap} href="/app1/decisions" index={0} />
        <SourceBlock label={SOURCE_LABEL.bank} count={bySource?.bank} index={1} />
        <SourceConnector matched={bankLedger.matched} gap={bankLedger.gap} href="/app1/decisions?category=missing_in_ledger" index={1} />
        <SourceBlock label={SOURCE_LABEL.ledger} count={bySource?.ledger} index={2} />
      </div>
    </div>
  );
}

/* ---------- shared selectors (presentation-only filters, no derivation) ---------- */

export function openExceptionsOf(rows: Exception[] | undefined): Exception[] {
  return (rows ?? []).filter((e) => e.status === "open");
}

export function openSubtotalOf(open: Exception[]): number {
  return sumPaise(open.filter((e) => e.tier !== "auto").map((e) => e.amount_paise));
}
