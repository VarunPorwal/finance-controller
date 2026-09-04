"use client";

// One row, twice: as the parser read it, and as it arrived in the file.

import { useEffect, useRef, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, X } from "lucide-react";
import type { TransactionEvent } from "../_lib/api";
import { useRawEvent } from "../_lib/api";
import { formatDateShort, formatDateTime } from "../_lib/format";
import { FcErrorNote, FcMoney, FcSourceMark, Identifier } from "../_components/fc-ui";
import { ClaimedBy, displayCounterparty } from "./table";
import { bestReference, narrationTruncated, scopeOf, type Claims } from "./search";

const HIDDEN: Set<keyof TransactionEvent> = new Set(["raw", "tenant_id", "gt_match_group", "gt_label", "raw_narration"]);
const MONEY_FIELDS: Set<keyof TransactionEvent> = new Set(["amount_paise", "fee_paise", "tax_paise"]);
const DATE_FIELDS: Set<keyof TransactionEvent> = new Set(["txn_date", "value_date"]);
const DATETIME_FIELDS: Set<keyof TransactionEvent> = new Set(["settled_at", "ingested_at"]);
const ID_FIELDS: Set<keyof TransactionEvent> = new Set([
  "event_id",
  "utr",
  "rrn",
  "settlement_id",
  "order_id",
  "payment_id",
  "voucher_number",
]);
const MONO = "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";
const SOURCE_LABEL: Record<"razorpay" | "bank" | "ledger", string> = {
  razorpay: "Razorpay settlements",
  bank: "Bank statement",
  ledger: "Tally day book",
};

function label(k: string): string {
  return k.replace(/_paise$/, "").replace(/_/g, " ");
}

function parsedRows(e: TransactionEvent): [ReactNode, ReactNode][] {
  const rows: [ReactNode, ReactNode][] = [];
  for (const [k, v] of Object.entries(e) as [keyof TransactionEvent, unknown][]) {
    if (HIDDEN.has(k)) continue;
    if (v === null || v === undefined || typeof v === "object") continue;
    let node: ReactNode;
    if (MONEY_FIELDS.has(k) && typeof v === "number") node = <span style={{ fontFamily: MONO }}><FcMoney paise={v} /></span>;
    else if (DATE_FIELDS.has(k) && typeof v === "string") node = <span style={{ fontFamily: MONO }}>{formatDateShort(v)}</span>;
    else if (DATETIME_FIELDS.has(k) && typeof v === "string") node = <span style={{ fontFamily: MONO }}>{formatDateTime(v)}</span>;
    else if (ID_FIELDS.has(k) && typeof v === "string") node = <Identifier value={v} />;
    else if (k === "counterparty" && typeof v === "string") node = displayCounterparty(v);
    else if (typeof v === "boolean") node = v ? "yes" : "no";
    else if (k === "source" && typeof v === "string") node = SOURCE_LABEL[v as keyof typeof SOURCE_LABEL] ?? v;
    else node = <span className="num" style={{ wordBreak: "break-all" }}>{String(v)}</span>;
    rows.push([label(k), node]);
  }
  return rows;
}

function KeyValueRows({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl
      className="grid gap-x-5 gap-y-2"
      style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))", fontSize: 12.5 }}
    >
      {rows.map(([k, v], i) => (
        <div key={i} className="flex items-baseline justify-between gap-3" style={{ minWidth: 0 }}>
          <dt className="fc-faint" style={{ whiteSpace: "nowrap" }}>
            {k}
          </dt>
          <dd
            className="fc-strong"
            style={{ minWidth: 0, textAlign: "right", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          >
            {v}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function RawTable({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <div className="fc-faint" style={{ fontSize: 12 }}>Empty.</div>;
  return (
    <div style={{ border: "1px solid var(--fc-divider)", borderRadius: 10, overflow: "hidden" }}>
      <table className="fc-table" style={{ fontSize: 12, tableLayout: "auto" }}>
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <td className="fc-faint" style={{ whiteSpace: "nowrap", verticalAlign: "top", width: 160 }}>
                {k}
              </td>
              <td className="num fc-muted" style={{ wordBreak: "break-all" }}>
                {v === null || v === undefined ? (
                  <span className="fc-faint">null</span>
                ) : typeof v === "object" ? (
                  <pre style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(v, null, 2)}</pre>
                ) : (
                  String(v)
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RecordDetail({ event, claims, onClose }: { event: TransactionEvent | null; claims: Claims; onClose: () => void }) {
  const raw = useRawEvent(event?.event_id ?? null);
  const ref = event ? bestReference(event) : null;
  const truncated = event ? narrationTruncated(event) : false;
  const scope = event ? scopeOf(event, claims) : null;

  useEffect(() => {
    if (!event) return;
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [event]);

  const rawBody = raw.data?.raw ?? null;
  const parsedAs =
    rawBody && typeof rawBody.parsed_as === "object" && rawBody.parsed_as !== null
      ? (rawBody.parsed_as as Record<string, unknown>)
      : null;
  const rawRest: Record<string, unknown> | null = rawBody
    ? Object.fromEntries(Object.entries(rawBody).filter(([k]) => k !== "parsed_as"))
    : null;

  return (
    <AnimatePresence>
      {event && (
        <PanelChrome onClose={onClose}>
          <div
            className="flex items-start justify-between gap-4"
            style={{ borderBottom: "1px solid var(--fc-border)", padding: "16px 20px" }}
          >
            <div style={{ minWidth: 0 }}>
              <div className="flex items-center gap-3" style={{ fontSize: 14, fontWeight: 500 }}>
                <span
                  className="fc-num fc-strong"
                  style={{ fontFamily: MONO, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                >
                  {ref ?? event.event_id}
                </span>
                <FcMoney paise={event.direction === "credit" ? Math.abs(event.amount_paise) : -Math.abs(event.amount_paise)} tone={event.direction === "credit" ? "ok" : "neutral"} />
              </div>
              <div className="fc-faint mt-1 flex items-center gap-2" style={{ fontSize: 12 }}>
                <FcSourceMark source={event.source} />
                <span aria-hidden>·</span>
                <span style={{ fontFamily: MONO }}>{formatDateShort(event.txn_date)}</span>
                <span aria-hidden>·</span>
                <Identifier value={event.event_id} />
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="fc-btn fc-btn--ghost"
              style={{ padding: 8, flex: "none" }}
            >
              <X size={15} />
            </button>
          </div>

          <div className="flex-1 overflow-auto" style={{ minHeight: 0 }}>
            <div className="flex flex-col gap-5" style={{ padding: "16px 20px" }}>
              <div className="grid gap-x-5 gap-y-4" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
                <div style={{ minWidth: 0 }}>
                  <div className="fc-label mb-2">Claimed by</div>
                  <ClaimedBy e={event} claims={claims} wrap />
                </div>

                <div style={{ minWidth: 0 }}>
                  <div className="fc-label mb-2">Scope</div>
                  <span
                    className="inline-flex items-start gap-1.5"
                    style={{ fontSize: 12.5, color: scope === "in_scope" ? "var(--fc-ok)" : "var(--fc-text-3)" }}
                  >
                    <span
                      className="h-1.5 w-1.5 rounded-full shrink-0"
                      style={{ background: scope === "in_scope" ? "var(--fc-ok)" : "var(--fc-text-3)", marginTop: 5 }}
                    />
                    {scope === "in_scope"
                      ? "In scope — backed by a bank leg. Proven money movement."
                      : "Evidence only — no bank leg yet. A claim of what should have happened, not proof it did."}
                  </span>
                </div>
              </div>

              {truncated && (
                <div
                  className="flex items-start gap-2"
                  style={{
                    borderRadius: 10,
                    border: "1px solid rgba(242,185,70,0.35)",
                    background: "rgba(242,185,70,0.1)",
                    padding: "8px 12px",
                    fontSize: 12.5,
                    color: "var(--fc-warn)",
                  }}
                >
                  <AlertTriangle size={14} style={{ marginTop: 2, flex: "none" }} />
                  <span>
                    Narration truncated at source. The bank cut this line at about 100 characters and the UTR went with it,
                    so this row is excluded from exact matching.
                  </span>
                </div>
              )}

              {event.raw_narration && (
                <div>
                  <div className="fc-label mb-2">Narration</div>
                  <div
                    className="num fc-muted"
                    style={{
                      border: "1px solid var(--fc-divider)",
                      borderRadius: 10,
                      background: "var(--fc-hover)",
                      padding: "10px 12px",
                      fontSize: 12,
                      lineHeight: 1.55,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-all",
                    }}
                  >
                    {event.raw_narration}
                    {truncated && <span style={{ color: "var(--fc-warn)" }}>▍</span>}
                  </div>
                  <div className="fc-faint mt-1" style={{ fontSize: 11.5 }}>
                    <span className="num">{event.raw_narration.length}</span> characters
                  </div>
                </div>
              )}

              <div>
                <div className="fc-label mb-2">As parsed</div>
                <KeyValueRows rows={parsedRows(event)} />
              </div>

              <div className="fc-divider" style={{ height: 1, background: "var(--fc-divider)" }} />

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <div className="fc-label">As it arrived</div>
                  {raw.data && <FcSourceMark source={raw.data.source} />}
                </div>
                {raw.isPending ? (
                  <div className="flex flex-col gap-2">
                    {Array.from({ length: 6 }).map((_, i) => (
                      <div key={i} className="fc-card fc-card--flat animate-pulse" style={{ height: 12, background: "var(--fc-divider)" }} />
                    ))}
                  </div>
                ) : raw.error ? (
                  <FcErrorNote message={raw.error.message} />
                ) : rawRest ? (
                  <RawTable data={rawRest} />
                ) : (
                  <div className="fc-faint" style={{ fontSize: 12 }}>
                    The original line was not stored for this row.
                  </div>
                )}
              </div>

              {parsedAs && (
                <div>
                  <div className="fc-label mb-2">Parsed as</div>
                  <RawTable data={parsedAs} />
                </div>
              )}
            </div>
          </div>
        </PanelChrome>
      )}
    </AnimatePresence>
  );
}

/** Local slide-over chrome, styled with Finco tokens directly rather than the
 * shared a1-themed `SlideOver` (its background/border classes are scoped
 * under `.a1`, which nothing in this app wraps any more). */
function PanelChrome({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <>
      <motion.div
        key="scrim"
        className="fixed inset-0 z-40"
        style={{ background: "rgba(5,5,6,0.55)" }}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
        onClick={onClose}
      />
      <motion.aside
        key="panel"
        ref={ref}
        className="fixed z-50 flex flex-col overflow-hidden"
        style={{
          right: 12,
          top: 12,
          bottom: 12,
          width: "min(680px, calc(100vw - 24px))",
          borderRadius: 16,
          background: "var(--fc-card-grad)",
          border: "1px solid var(--fc-border)",
          boxShadow: "0 24px 60px rgba(0,0,0,0.45)",
        }}
        initial={{ transform: "translateX(24px)", opacity: 0 }}
        animate={{ transform: "translateX(0px)", opacity: 1, transition: { duration: 0.22, ease: [0.32, 0.72, 0, 1] } }}
        exit={{ transform: "translateX(24px)", opacity: 0, transition: { duration: 0.12, ease: [0.23, 1, 0.32, 1] } }}
        role="dialog"
        aria-modal
      >
        {children}
      </motion.aside>
    </>
  );
}
