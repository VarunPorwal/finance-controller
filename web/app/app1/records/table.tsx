"use client";

// The rows. Rendered in slices of 300 so a 1,575-row run never stalls the
// tab; "Show more" reveals the next slice.

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, SearchX } from "lucide-react";
import type { TransactionEvent } from "../_lib/api";
import { STATUS_LABEL, categoryShort, stageLabel } from "../_lib/labels";
import { formatCount, formatDateShort } from "../_lib/format";
import { Identifier, StatusDot, FcEmpty, FcMoney, FcSourceMark } from "../_components/fc-ui";
import { bestReference, scopeOf, type Claims } from "./search";

const SLICE = 300;
const MONO = "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";

/** Title case, capped at 24 chars. Render-time only — never persisted, never
 * sent back to search or claim logic. */
export function displayCounterparty(name: string): string {
  const titled = name
    .toLowerCase()
    .replace(/\b\p{L}/gu, (c) => c.toUpperCase());
  return titled.length > 24 ? `${titled.slice(0, 24).trimEnd()}…` : titled;
}

export function RecordsTable({
  rows,
  claims,
  onOpen,
  emptyHint,
}: {
  rows: TransactionEvent[];
  claims: Claims;
  onOpen: (e: TransactionEvent) => void;
  emptyHint: string;
}) {
  const [limit, setLimit] = useState(SLICE);
  const shown = rows.slice(0, limit);

  if (rows.length === 0) {
    return (
      <div className="flex flex-col items-center">
        <SearchX size={20} className="fc-faint" aria-hidden style={{ marginTop: 40, opacity: 0.6 }} />
        <FcEmpty title="No rows match" sub={emptyHint} />
      </div>
    );
  }

  return (
    <>
      <div className="max-h-[760px] overflow-auto">
        <table className="fc-table">
          <thead>
            <tr>
              <th style={{ width: 92 }}>Source</th>
              <th style={{ width: 84 }}>Date</th>
              <th className="fc-table-num" style={{ width: 140 }}>
                Amount
              </th>
              <th style={{ width: 190 }}>Reference</th>
              <th style={{ width: 190 }}>Counterparty</th>
              <th>Narration</th>
              <th style={{ width: 110 }}>Scope</th>
              <th style={{ width: 200 }}>Claimed by</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((e) => {
              const ref = bestReference(e);
              const credit = e.direction === "credit";
              return (
                <tr key={e.event_id} onClick={() => onOpen(e)} className="fc-row-click">
                  <td>
                    <FcSourceMark source={e.source} />
                  </td>
                  <td className="fc-muted fc-num" style={{ whiteSpace: "nowrap", fontFamily: MONO }}>
                    {formatDateShort(e.txn_date)}
                  </td>
                  <td className="fc-table-num" style={{ fontFamily: MONO }}>
                    <FcMoney paise={credit ? Math.abs(e.amount_paise) : -Math.abs(e.amount_paise)} />
                  </td>
                  <td onClick={(ev) => ev.stopPropagation()}>
                    {ref ? <Identifier value={ref} /> : <span className="fc-faint">—</span>}
                  </td>
                  <td>
                    <span style={truncateStyle(190)} title={e.counterparty ?? undefined}>
                      {e.counterparty ? displayCounterparty(e.counterparty) : <span className="fc-faint">—</span>}
                    </span>
                  </td>
                  <td>
                    <span className="fc-muted" style={truncateStyle(420)} title={e.raw_narration ?? undefined}>
                      {e.raw_narration ?? <span className="fc-faint">—</span>}
                    </span>
                  </td>
                  <td>
                    <ScopeMark e={e} claims={claims} />
                  </td>
                  <td onClick={(ev) => ev.stopPropagation()}>
                    <ClaimedBy e={e} claims={claims} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length > shown.length && (
        <div className="flex items-center justify-between gap-3" style={{ borderTop: "1px solid var(--fc-divider)", padding: "12px 16px" }}>
          <span className="fc-faint" style={{ fontSize: 12 }}>
            Showing <span className="fc-num">{formatCount(shown.length)}</span> of{" "}
            <span className="fc-num">{formatCount(rows.length)}</span>
          </span>
          <button type="button" className="fc-btn fc-btn--ghost" onClick={() => setLimit((n) => n + SLICE)}>
            Show more
          </button>
        </div>
      )}
    </>
  );
}

function truncateStyle(maxWidth: number): React.CSSProperties {
  return { display: "block", maxWidth, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" };
}

/** Shimmering row shapes, same column rhythm as the real table, shown while
 * the first page of events is still in flight. */
export function RecordsTableSkeleton() {
  return (
    <table className="fc-table">
      <thead>
        <tr>
          <th style={{ width: 92 }}>Source</th>
          <th style={{ width: 84 }}>Date</th>
          <th className="fc-table-num" style={{ width: 140 }}>
            Amount
          </th>
          <th style={{ width: 190 }}>Reference</th>
          <th style={{ width: 190 }}>Counterparty</th>
          <th>Narration</th>
          <th style={{ width: 110 }}>Scope</th>
          <th style={{ width: 200 }}>Claimed by</th>
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: 10 }).map((_, i) => (
          <tr key={i}>
            {Array.from({ length: 8 }).map((__, j) => (
              <td key={j}>
                <div className="fc-skel" style={{ height: 12, width: j === 5 ? "70%" : "60%" }} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ScopeMark({ e, claims }: { e: TransactionEvent; claims: Claims }) {
  const scope = scopeOf(e, claims);
  const inScope = scope === "in_scope";
  return (
    <span
      title={
        inScope
          ? "Backed by a bank leg — proven money movement."
          : "No bank leg yet. A claim of what should have happened, not proof it did."
      }
    >
      <StatusDot tone={inScope ? "ok" : "neutral"} className="text-[11.5px]">
        {inScope ? "In scope" : "Evidence only"}
      </StatusDot>
    </span>
  );
}

export function ClaimedBy({ e, claims, wrap }: { e: TransactionEvent; claims: Claims; wrap?: boolean }) {
  const exc = claims.exceptions.get(e.event_id);
  const match = claims.matches.get(e.event_id);
  if (!exc && !match) return <span className="fc-faint">—</span>;
  return (
    <span className={wrap ? "flex flex-wrap items-center gap-3" : "inline-flex items-center gap-3"}>
      {exc && (
        <Link
          href={`/app1/decisions?open=${encodeURIComponent(exc.exception_id)}`}
          className="inline-flex items-center gap-1"
          title={exc.exception_id}
        >
          <StatusDot tone={exc.status === "open" ? "warn" : exc.status === "resolved" ? "ok" : "neutral"}>
            {categoryShort(exc.category)} · {STATUS_LABEL[exc.status]}
          </StatusDot>
          <ArrowRight size={10} className="fc-faint" />
        </Link>
      )}
      {match && (
        <Link href="/app1/settlements" className="inline-flex items-center gap-1" title={match.match_id}>
          <StatusDot tone={match.auto_closed ? "ok" : "neutral"}>
            {stageLabel(match.stage)}
            {match.auto_closed ? " · closed" : " · open"}
          </StatusDot>
          <ArrowRight size={10} className="fc-faint" />
        </Link>
      )}
    </span>
  );
}
