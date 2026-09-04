"use client";

import { Check, X, Minus, ArrowUpRight, ChevronRight } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { clsx } from "clsx";
import { FcEmpty, FcMoney, Identifier, StatusDot, type FcTone } from "../_components/fc-ui";
import { formatDateShort, money } from "../_lib/format";
import { CATEGORY, STAGE, categoryShort } from "../_lib/labels";
import type { TransactionEvent } from "../_lib/api";
import { filterRows, type RegisterFilter, type RegisterRow, type RowStatus } from "./register";

/** Title case, capped at 24 chars, for a counterparty name. */
function titleCaseName(s: string, max = 24): string {
  const t = s.replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
}

const FILTERS: { value: RegisterFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "not_received", label: "Not received" },
  { value: "not_booked", label: "Not booked" },
  { value: "open", label: "Open" },
  { value: "proven", label: "Proven" },
];

function Mark({ state, title }: { state: "yes" | "no" | "none"; title: string }) {
  const color = state === "yes" ? "var(--fc-ok)" : state === "no" ? "var(--fc-bad)" : "var(--fc-text-3)";
  return (
    <span title={title} className="fc-num inline-flex w-4 justify-center" style={{ color }}>
      {state === "yes" ? <Check size={13} strokeWidth={2.2} /> : state === "no" ? <X size={13} strokeWidth={2.2} /> : <Minus size={11} />}
    </span>
  );
}

function Decided({ s }: { s: RowStatus }) {
  switch (s.kind) {
    case "proven":
      return (
        <StatusDot tone="ok">
          Proven <span className="fc-faint">· Cascade · {STAGE[s.stage].label}</span>
        </StatusDot>
      );
    case "two_way":
      return (
        <StatusDot tone="neutral">
          Two-way{" "}
          <span className="fc-faint">
            · Cascade · {STAGE[s.stage].label} · no {s.missing === "bank" ? "bank leg" : "ledger leg"}
          </span>
        </StatusDot>
      );
    case "held":
      return (
        <StatusDot tone="neutral">
          Not closed <span className="fc-faint">· Cascade · {STAGE[s.stage].label} · below threshold</span>
        </StatusDot>
      );
    case "rule":
      return (
        <StatusDot tone="ok">
          Rule <span className="fc-faint">· Rulebook{s.ruleHash ? ` · ${s.ruleHash.slice(0, 8)}` : ""}</span>
        </StatusDot>
      );
    case "open": {
      const tone: FcTone = CATEGORY[s.category]?.neverAuto ? "accent" : "bad";
      return (
        <StatusDot tone={tone}>
          Open <span className="fc-muted">· {categoryShort(s.category)}</span>
        </StatusDot>
      );
    }
    case "human":
      return (
        <StatusDot tone="ok">
          Resolved <span className="fc-faint">· Human{s.user ? ` · ${s.user}` : ""}</span>
        </StatusDot>
      );
    default:
      return (
        <StatusDot>
          Unmatched <span className="fc-faint">· No stage claimed it</span>
        </StatusDot>
      );
  }
}

function EventLine({ e }: { e: TransactionEvent }) {
  const ref =
    e.source === "razorpay"
      ? e.order_id ?? e.payment_id ?? e.settlement_id
      : e.source === "bank"
        ? e.utr ?? e.rrn ?? e.raw_narration
        : e.voucher_number ?? e.voucher_guid;
  const sourceColor = e.source === "razorpay" ? "var(--fc-accent)" : e.source === "bank" ? "var(--fc-text)" : "var(--fc-text-3)";
  const sourceLabel = e.source === "razorpay" ? "Razorpay" : e.source === "bank" ? "Bank" : "Tally";
  return (
    <div className="grid grid-cols-[90px_1fr_auto_auto] items-center gap-3 py-1.5" style={{ fontSize: 12 }}>
      <span className="inline-flex items-center gap-1.5" style={{ color: sourceColor, fontSize: 11.5, fontWeight: 500 }}>
        <span className="fc-dot" style={{ background: sourceColor }} />
        {sourceLabel}
      </span>
      <div className="min-w-0">
        <div className="flex items-center gap-1 truncate">
          <Identifier value={ref} />
          {e.counterparty && <span className="fc-faint">· {titleCaseName(e.counterparty)}</span>}
        </div>
        {e.source === "bank" && e.raw_narration && (
          <div className="fc-faint truncate" style={{ fontSize: 11 }}>{e.raw_narration}</div>
        )}
      </div>
      <span className="fc-faint fc-num" style={{ fontSize: 11.5 }}>{formatDateShort(e.txn_date)}</span>
      <span className="fc-num text-right">
        <span style={{ color: e.direction === "debit" ? "var(--fc-text-2)" : "var(--fc-text)" }}>
          {e.direction === "debit" ? "−" : ""}
          {money(e.amount_paise)}
        </span>
        {(e.fee_paise ?? 0) > 0 && (
          <span className="fc-faint ml-2" style={{ fontSize: 11 }}>fee {money((e.fee_paise ?? 0) + (e.tax_paise ?? 0))}</span>
        )}
      </span>
    </div>
  );
}

function Detail({ row }: { row: RegisterRow }) {
  const open = row.exceptions.filter((x) => x.status !== "superseded");
  return (
    <div className="mx-3 my-2 px-4 py-3" style={{ background: "var(--fc-hover)", border: "1px solid var(--fc-divider)", borderRadius: 10 }}>
      <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
        <div>
          <div className="fc-label mb-1">Underlying rows</div>
          <div className="divide-y" style={{ borderColor: "var(--fc-divider)" }}>
            {row.razorpayEvents.map((e) => <EventLine key={e.event_id} e={e} />)}
            {row.bankEvents.map((e) => <EventLine key={e.event_id} e={e} />)}
            {row.ledgerEvents.map((e) => <EventLine key={e.event_id} e={e} />)}
          </div>
          {!row.hasBank && <div className="mt-2" style={{ fontSize: 12, color: "var(--fc-bad)" }}>No bank row is attached to this settlement.</div>}
          {!row.hasLedger && row.hasBank && <div className="mt-2" style={{ fontSize: 12, color: "var(--fc-text)" }}>No Tally voucher is attached to this settlement.</div>}
        </div>
        <div className="flex flex-col gap-3">
          {row.match && (
            <div>
              <div className="fc-label mb-1">Match</div>
              <div style={{ fontSize: 12 }}>
                {STAGE[row.match.stage].label}
                <span className="fc-faint"> · confidence </span>
                <span style={{ fontSize: 11.5 }}>{row.match.confidence}</span>
                {row.match.residual_paise !== 0 && (
                  <>
                    <span className="fc-faint"> · residual </span>
                    <FcMoney paise={row.match.residual_paise} size="sm" />
                  </>
                )}
              </div>
              <div className="fc-faint mt-0.5" style={{ fontSize: 11.5 }}>
                {row.match.auto_closed ? "Closed by the cascade" : "Matched, left open for a human"}
              </div>
            </div>
          )}
          {open.length > 0 && (
            <div>
              <div className="fc-label mb-1">Decisions</div>
              <div className="flex flex-col gap-1.5">
                {open.map((x) => (
                  <Link
                    key={x.exception_id}
                    href={`/decisions?open=${x.exception_id}`}
                    className="fc-card flex items-center justify-between gap-3"
                    style={{ padding: "8px 12px", fontSize: 12 }}
                  >
                    <span className="min-w-0">
                      <span className="block">{CATEGORY[x.category]?.label ?? x.category}</span>
                      <span className="fc-faint" style={{ fontSize: 11 }}>
                        {x.status === "open" || x.status === "escalated" ? "Open decision" : x.status.replace(/_/g, " ")}
                        {" · "}
                        <FcMoney paise={x.amount_paise} size="sm" />
                      </span>
                    </span>
                    <span className="fc-muted inline-flex shrink-0 items-center gap-1" style={{ fontSize: 11.5 }}>
                      Open decision <ArrowUpRight size={12} />
                    </span>
                  </Link>
                ))}
              </div>
            </div>
          )}
          {!row.match && open.length === 0 && (
            <div className="fc-faint" style={{ fontSize: 12 }}>Nothing claimed this settlement. It sits outside every match and every decision.</div>
          )}
        </div>
      </div>
    </div>
  );
}

export function RegisterTable({ rows }: { rows: RegisterRow[] }) {
  const [filter, setFilter] = useState<RegisterFilter>("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const visible = useMemo(() => filterRows(rows, filter), [rows, filter]);

  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f.value, filterRows(rows, f.value).length])) as Record<RegisterFilter, number>,
    [rows],
  );

  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5" style={{ padding: "0 16px 12px" }}>
        {FILTERS.map((f) => {
          const active = f.value === filter;
          return (
            <button
              key={f.value}
              type="button"
              onClick={() => setFilter(f.value)}
              className="fc-chip inline-flex items-center gap-1.5"
              style={{
                cursor: "pointer",
                background: active ? "var(--fc-accent)" : "var(--fc-divider)",
                color: active ? "#fff" : "var(--fc-text-3)",
              }}
              aria-pressed={active}
            >
              {f.label}
              <span className="fc-num" style={{ opacity: active ? 0.9 : 0.6 }}>{counts[f.value]}</span>
            </button>
          );
        })}
        <span className="fc-faint ml-auto" style={{ fontSize: 11.5 }}>Gap is Razorpay less bank, shown for reading, not decided on.</span>
      </div>
      {visible.length === 0 ? (
        <FcEmpty title="No settlements match this filter" sub="Change the filter to see the rest of the register." />
      ) : (
        <div style={{ overflow: "auto", maxHeight: 640 }}>
          <table className="fc-table" style={{ tableLayout: "auto" }}>
            <thead>
              <tr>
                <th style={{ width: 28 }} />
                <th>Settlement</th>
                <th className="fc-table-num">Razorpay says</th>
                <th className="fc-table-num">Bank received</th>
                <th className="fc-table-num">Tally booked</th>
                <th className="text-center" title="Gateway · Bank · Ledger">G · B · L</th>
                <th>Who decided</th>
                <th className="fc-table-num">Gap</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => {
                const isOpen = expanded === r.settlementId;
                return (
                  <Fragment key={r.settlementId}>
                    <motion.tr
                      initial={false}
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setExpanded(isOpen ? null : r.settlementId);
                        }
                      }}
                      onClick={() => setExpanded(isOpen ? null : r.settlementId)}
                      className="fc-row-click cursor-pointer"
                      style={{ background: isOpen ? "var(--fc-row-sel)" : undefined }}
                      aria-expanded={isOpen}
                    >
                      <td className="pr-0">
                        <ChevronRight size={13} className={clsx("fc-faint transition-transform", isOpen && "rotate-90")} />
                      </td>
                      <td>
                        <Identifier value={r.settlementId} />
                        <div className="fc-faint fc-num" style={{ fontSize: 11 }}>{r.date ? formatDateShort(r.date) : "—"}</div>
                      </td>
                      <td className="fc-table-num">
                        <FcMoney paise={r.razorpayPaise} />
                        {r.feePaise > 0 && <div className="fc-faint fc-num" style={{ fontSize: 11 }}>fees {money(r.feePaise, { whole: true })}</div>}
                      </td>
                      <td className="fc-table-num">
                        {r.bankPaise === null ? (
                          <span style={{ borderRadius: 4, border: "1px dashed var(--fc-bad)", padding: "1px 6px", fontSize: 11, color: "var(--fc-bad)" }}>
                            not received
                          </span>
                        ) : (
                          <>
                            <FcMoney paise={r.bankPaise} tone="neutral" />
                            <div className="fc-faint flex items-center justify-end gap-1" style={{ fontSize: 11 }}>
                              {r.utr ? <Identifier value={r.utr} /> : "no UTR"}
                              {r.bankDate ? <span className="fc-num">· {formatDateShort(r.bankDate)}</span> : ""}
                            </div>
                          </>
                        )}
                      </td>
                      <td className="fc-table-num">
                        {r.ledgerPaise === null ? (
                          <span className="fc-faint" style={{ borderRadius: 4, border: "1px dashed var(--fc-border)", padding: "1px 6px", fontSize: 11 }}>
                            not booked
                          </span>
                        ) : (
                          <>
                            <FcMoney paise={r.ledgerPaise} />
                            <div className="fc-faint flex justify-end" style={{ fontSize: 11 }}>
                              {r.voucher ? <Identifier value={r.voucher} /> : "no voucher no."}
                            </div>
                          </>
                        )}
                      </td>
                      <td className="text-center">
                        <span className="inline-flex gap-1">
                          <Mark state="yes" title="Razorpay settlement" />
                          <Mark state={r.hasBank ? "yes" : "no"} title={r.hasBank ? "Bank credit found" : "Not received in bank"} />
                          <Mark state={r.hasLedger ? "yes" : r.hasBank ? "no" : "none"} title={r.hasLedger ? "Tally voucher found" : "Not booked in Tally"} />
                        </span>
                      </td>
                      <td>
                        <Decided s={r.status} />
                      </td>
                      <td className="fc-table-num">
                        {r.gapPaise === null ? <span className="fc-faint">—</span> : <FcMoney paise={r.gapPaise} tone={r.gapPaise !== 0 ? "bad" : "neutral"} />}
                      </td>
                    </motion.tr>
                    <AnimatePresence initial={false}>
                      {isOpen && (
                        <tr key={`${r.settlementId}-d`}>
                          <td colSpan={8} className="p-0" style={{ borderBottom: "1px solid var(--fc-divider)" }}>
                            <motion.div
                              layout
                              initial={{ height: 0, opacity: 0 }}
                              animate={{ height: "auto", opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }}
                              transition={{ type: "spring", stiffness: 400, damping: 36 }}
                              style={{ overflow: "hidden" }}
                            >
                              <Detail row={r} />
                            </motion.div>
                          </td>
                        </tr>
                      )}
                    </AnimatePresence>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
