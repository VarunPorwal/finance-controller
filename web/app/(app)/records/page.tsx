"use client";

// Records. "Show me the underlying evidence." Search first, then the table,
// then the row itself with the raw line beside the parsed one.

import { Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { motion, useReducedMotion } from "framer-motion";
import { ChevronDown, Search, X } from "lucide-react";
import { useCurrentRun, useEvents, useEventsCount, useExceptions, useMatches, type TransactionEvent } from "../_lib/api";
import type { Source } from "../_lib/labels";
import { formatCount } from "../_lib/format";
import { FcCard, FcErrorNote, FcHead, FcPage, FcSkeleton, FcSourceMark } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";
import { RecordsTable, RecordsTableSkeleton } from "./table";
import { RecordDetail } from "./detail";
import {
  buildClaims,
  claimState,
  eventMatches,
  inDateRange,
  parseAmountQuery,
  scopeOf,
  type ClaimFilter,
  type DateRange,
  type ScopeFilter,
  type SourceFilter,
} from "./search";

const SOURCES: Source[] = ["razorpay", "bank", "ledger"];

const SOURCE_OPTIONS: { value: SourceFilter; label: string }[] = [
  { value: "all", label: "All sources" },
  { value: "razorpay", label: "Razorpay" },
  { value: "bank", label: "Bank" },
  { value: "ledger", label: "Tally" },
];
const SCOPE_OPTIONS: { value: ScopeFilter; label: string }[] = [
  { value: "any", label: "Any scope" },
  { value: "in_scope", label: "In scope" },
  { value: "evidence_only", label: "Evidence only" },
];
const CLAIM_OPTIONS: { value: ClaimFilter; label: string }[] = [
  { value: "any", label: "Claimed by: any" },
  { value: "matched", label: "Matched" },
  { value: "decision", label: "In a decision" },
  { value: "unclaimed", label: "Unclaimed" },
];

const MONO = "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";

/** Fade-in on mount only, staggered by index — cards don't re-animate on data
 * refresh since the wrapper never unmounts. */
function FadeCard({ index, children }: { index: number; children: ReactNode }) {
  const reduced = useReducedMotion();
  if (reduced) return <>{children}</>;
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, delay: index * 0.04 }}
    >
      {children}
    </motion.div>
  );
}

export default function RecordsPage() {
  return (
    <Suspense fallback={<RecordsSkeleton />}>
      <RecordsInner />
    </Suspense>
  );
}

function RecordsSkeleton() {
  return (
    <FcPage>
      <FcHead title="Records" sub="Show me the underlying evidence." />
      <FcSkeleton className="h-[52px] mb-3" />
      <div className="flex flex-col gap-3">
        <FcSkeleton className="h-[52px]" />
        <FcSkeleton className="h-[420px]" />
      </div>
    </FcPage>
  );
}

function RecordsInner() {
  const params = useSearchParams();
  const urlQ = params.get("q") ?? "";
  const { runId } = useCurrentRun();

  const events = useEvents(runId);
  const matches = useMatches(runId);
  const exceptions = useExceptions(runId);
  const counts = useEventsCount(runId);

  const [q, setQ] = useState(urlQ);
  const [source, setSource] = useState<SourceFilter>("all");
  const [scope, setScope] = useState<ScopeFilter>("any");
  const [claim, setClaim] = useState<ClaimFilter>("any");
  const [dateRange, setDateRange] = useState<DateRange>({ from: null, to: null });
  const [open, setOpen] = useState<TransactionEvent | null>(null);

  useEffect(() => setQ(urlQ), [urlQ]);

  const claims = useMemo(() => buildClaims(matches.data, exceptions.data), [matches.data, exceptions.data]);

  const dateBounds = useMemo(() => {
    let min: string | null = null;
    let max: string | null = null;
    for (const e of events.data ?? []) {
      if (!min || e.txn_date < min) min = e.txn_date;
      if (!max || e.txn_date > max) max = e.txn_date;
    }
    return { min, max };
  }, [events.data]);

  const rows = useMemo(() => {
    const all = events.data ?? [];
    const qLower = q.trim().toLowerCase();
    const amount = parseAmountQuery(q.trim());
    return all.filter((e) => {
      if (source !== "all" && e.source !== source) return false;
      if (scope !== "any" && scopeOf(e, claims) !== scope) return false;
      if (claim !== "any" && claimState(e, claims) !== claim) return false;
      if (!inDateRange(e, dateRange)) return false;
      return eventMatches(e, qLower, amount);
    });
  }, [events.data, q, source, scope, claim, dateRange, claims]);

  const error = events.error ?? matches.error ?? exceptions.error;
  const loading = events.isPending || matches.isPending || exceptions.isPending;
  const claimsReady = !matches.isPending && !exceptions.isPending;

  return (
    <FcPage>
      <FcHead title="Records" sub="Show me the underlying evidence." />

      <FadeCard index={0}>
        <FcCard className="mb-3" style={{ padding: 0 }}>
          <div className="flex items-stretch" style={{ height: 52 }}>
            {SOURCES.map((s, i) => (
              <div
                key={s}
                className="flex flex-1 flex-col justify-center"
                style={{
                  padding: "0 18px",
                  borderLeft: i === 0 ? undefined : "1px solid var(--fc-divider)",
                }}
              >
                <div className="mb-1">
                  <FcSourceMark source={s} />
                </div>
                <div className="fc-num" style={{ fontSize: 18, fontWeight: 500, fontFamily: MONO, color: "var(--fc-text)" }}>
                  {counts.data ? (
                    <CountUp value={counts.data.by_source[s] ?? 0} />
                  ) : (
                    <FcSkeleton className="h-[18px] w-14" />
                  )}
                </div>
              </div>
            ))}
          </div>
        </FcCard>
      </FadeCard>

      {error ? (
        <FcErrorNote message={error.message} />
      ) : (
        <FadeCard index={1}>
          <FcCard style={{ padding: 0, marginBottom: 12 }}>
            <div className="flex flex-col gap-3" style={{ borderBottom: "1px solid var(--fc-divider)", padding: "16px" }}>
              <div className="relative">
                <Search size={15} className="fc-faint" style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }} />
                <input
                  autoFocus
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  placeholder="UTR, RRN, settlement, order, voucher, counterparty, narration, or an amount like 12,345"
                  aria-label="Search records"
                  style={{
                    width: "100%",
                    height: 40,
                    padding: "0 36px",
                    borderRadius: "var(--fc-r-sm)",
                    border: "1px solid var(--fc-border)",
                    background: "var(--fc-hover)",
                    color: "var(--fc-text)",
                    fontSize: 14,
                    fontFamily: "inherit",
                  }}
                />
                {q && (
                  <button
                    type="button"
                    onClick={() => setQ("")}
                    aria-label="Clear search"
                    className="fc-btn fc-btn--ghost"
                    style={{ position: "absolute", right: 6, top: "50%", transform: "translateY(-50%)", height: 28, width: 28, padding: 0 }}
                  >
                    <X size={13} />
                  </button>
                )}
              </div>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <FilterSelect value={source} onChange={setSource} options={SOURCE_OPTIONS} />
                  <FilterSelect value={scope} onChange={setScope} options={SCOPE_OPTIONS} />
                  <FilterSelect value={claim} onChange={setClaim} options={CLAIM_OPTIONS} />
                  <DateRangeFilter range={dateRange} onChange={setDateRange} bounds={dateBounds} />
                </div>
                <span className="fc-faint" style={{ fontSize: 12 }}>
                  <span className="fc-num">{formatCount(rows.length)}</span> rows
                </span>
              </div>
            </div>

            {loading && !events.data ? (
              <RecordsTableSkeleton />
            ) : (
              <RecordsTable
                rows={rows}
                claims={claims}
                onOpen={setOpen}
                emptyHint={
                  q.trim()
                    ? `Nothing in this run carries “${q.trim()}”. Try a shorter piece of the reference, or the amount without paise.`
                    : "Rows will appear here once a run has read a Razorpay file, a bank statement or a Tally export."
                }
              />
            )}
            {!claimsReady && events.data && (
              <div className="fc-faint" style={{ borderTop: "1px solid var(--fc-divider)", padding: "8px 16px", fontSize: 11.5 }}>
                Loading who claims each row.
              </div>
            )}
          </FcCard>
        </FadeCard>
      )}

      <RecordDetail event={open} claims={claims} onClose={() => setOpen(null)} />
    </FcPage>
  );
}

const selectStyle: React.CSSProperties = {
  appearance: "none",
  background: "var(--fc-divider)",
  color: "var(--fc-text-2)",
  border: "1px solid var(--fc-border)",
  borderRadius: "var(--fc-r-sm)",
  padding: "6px 26px 6px 10px",
  fontSize: 12.5,
  fontFamily: "inherit",
  cursor: "pointer",
};

function FilterSelect<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <span className="relative inline-flex items-center">
      <select value={value} onChange={(e) => onChange(e.target.value as T)} style={selectStyle} aria-label="Filter">
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown size={12} className="fc-faint" style={{ position: "absolute", right: 8, pointerEvents: "none" }} />
    </span>
  );
}

function DateRangeFilter({
  range,
  onChange,
  bounds,
}: {
  range: DateRange;
  onChange: (r: DateRange) => void;
  bounds: { min: string | null; max: string | null };
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (ev: MouseEvent) => {
      if (ref.current && !ref.current.contains(ev.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const active = range.from !== null || range.to !== null;
  const buttonLabel = active
    ? `${range.from ?? bounds.min ?? "…"} – ${range.to ?? bounds.max ?? "…"}`
    : "All dates";

  return (
    <div className="relative inline-flex" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{ ...selectStyle, padding: "6px 26px 6px 10px", display: "inline-flex", alignItems: "center", gap: 6 }}
      >
        <span className="fc-num">{buttonLabel}</span>
        <ChevronDown size={12} className="fc-faint" />
      </button>
      {open && (
        <div
          className="absolute z-10"
          style={{
            top: "calc(100% + 6px)",
            left: 0,
            background: "var(--fc-card)",
            border: "1px solid var(--fc-border)",
            borderRadius: "var(--fc-r-sm)",
            padding: 12,
            display: "flex",
            flexDirection: "column",
            gap: 8,
            boxShadow: "0 12px 30px rgba(0,0,0,0.35)",
            minWidth: 220,
          }}
        >
          <DateField label="From" value={range.from} min={bounds.min} max={range.to ?? bounds.max} onChange={(v) => onChange({ ...range, from: v })} />
          <DateField label="To" value={range.to} min={range.from ?? bounds.min} max={bounds.max} onChange={(v) => onChange({ ...range, to: v })} />
          {active && (
            <button
              type="button"
              className="fc-link"
              style={{ textAlign: "left", background: "none", border: 0, padding: 0, cursor: "pointer" }}
              onClick={() => onChange({ from: null, to: null })}
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function DateField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: ReactNode;
  value: string | null;
  min: string | null;
  max: string | null;
  onChange: (v: string | null) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-3" style={{ fontSize: 12 }}>
      <span className="fc-faint">{label}</span>
      <input
        type="date"
        value={value ?? ""}
        min={min ?? undefined}
        max={max ?? undefined}
        onChange={(e) => onChange(e.target.value || null)}
        style={{
          background: "var(--fc-divider)",
          color: "var(--fc-text)",
          border: "1px solid var(--fc-border)",
          borderRadius: "var(--fc-r-sm)",
          padding: "4px 8px",
          fontSize: 12,
          fontFamily: "inherit",
        }}
      />
    </label>
  );
}
