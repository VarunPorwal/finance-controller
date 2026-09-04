"use client";

// The list's building blocks, Finco-skinned: a band section (header + table),
// one exception row, a cluster row that expands to its members, a deadline
// chip and a handled row. No confidence, no tier pill, no cause-cluster
// column — those were dropped per the redesign brief; a cluster's rows still
// carry the "will not guess" / "injection flagged" signals because those are
// safety facts, not confidence noise.

import { useState, type KeyboardEvent, type MouseEvent, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Layers } from "lucide-react";
import { clsx } from "clsx";
import type { Cluster, Exception, TransactionEvent } from "../_lib/api";
import { ACTION_GROUP, categoryLabel, categoryShort, type ActionGroup } from "../_lib/labels";
import { daysBetween, formatDateShort, money, plural, relativeDays, sumPaise } from "../_lib/format";
import { Identifier, StatusDot } from "../_components/fc-ui";
import { causeLine, eventReference, firstEvent, firstVerb, neverAuto, titleCaseShort } from "./helpers";

type Open = (id: string) => void;

function ageLabel(e: Exception, asOf: string): string {
  if (e.deadline && asOf) return relativeDays(e.deadline, asOf);
  if (!asOf) return "";
  return `${Math.max(0, daysBetween(e.created_at, asOf))}d old`;
}

function ageUrgent(e: Exception, asOf: string): boolean {
  if (!e.deadline || !asOf) return false;
  return daysBetween(asOf, e.deadline) <= 0;
}

function keyOpen(ev: KeyboardEvent<HTMLElement>, fn: () => void) {
  if (ev.key === "Enter" || ev.key === " ") {
    ev.preventDefault();
    fn();
  }
}

/* ---------- band section: header + table ---------- */

export function BandHeader({
  group,
  subtotal,
  count,
  title,
  blurb,
}: {
  group?: ActionGroup;
  subtotal: number;
  count: number;
  title?: string;
  blurb?: string;
}) {
  const g = group ? ACTION_GROUP[group] : null;
  return (
    <div className="fc-lhead">
      <div className="flex items-center gap-3">
        <div>
          <div style={{ fontSize: 13, fontWeight: 500, color: "var(--fc-text)" }}>{title ?? g?.label}</div>
          <div className="fc-label mt-0.5">{blurb ?? g?.blurb}</div>
        </div>
      </div>
      <div className="flex items-baseline gap-3">
        <span className="fc-num" style={{ fontSize: 15 }}>
          {money(subtotal)}
        </span>
        <span className="fc-faint fc-num text-[11px]">{plural(count, "item")}</span>
      </div>
    </div>
  );
}

/* ---------- deadline chip strip ---------- */

export function DeadlineChip({ e, asOf, onOpen }: { e: Exception; asOf: string; onOpen: Open }) {
  if (!e.deadline) return null;
  const urgent = ageUrgent(e, asOf);
  return (
    <button
      className="fc-card relative shrink-0 px-3.5 py-2.5 text-left transition-transform hover:-translate-y-px"
      onClick={() => onOpen(e.exception_id)}
    >
      <div className="flex items-baseline gap-2">
        <span className="fc-num fc-faint text-[12px]">{formatDateShort(e.deadline)}</span>
        <span className="inline-flex items-center gap-1.5">
          <span className={clsx("fc-num text-[11px]", "text-[var(--fc-text-2)]", urgent && "font-medium")}>
            {relativeDays(e.deadline, asOf)}
          </span>
        </span>
      </div>
      <div className="mt-0.5 flex items-baseline gap-2">
        <span className="fc-num fc-strong text-[13px]">{money(e.amount_paise)}</span>
        <span className="fc-faint text-[11.5px]">{categoryShort(e.category)}</span>
      </div>
    </button>
  );
}

/* ---------- shared cell content ---------- */

function WhatHappened({ e }: { e: Exception }) {
  const cause = causeLine(e);
  return (
    <div className="min-w-0">
      <div style={{ fontSize: 13, fontWeight: 500 }}>{categoryLabel(e.category)}</div>
      <div
        className="fc-faint mt-0.5 text-[12px]"
        title={cause}
        style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
      >
        {cause}
      </div>
    </div>
  );
}

/** "Will not guess" is a policy annotation, not a status — a flat divider
 * chip. "Injection flagged" is a detected condition, so it reads as a status
 * dot instead. */
function SafetyBadges({ e }: { e: Exception }) {
  if (!neverAuto(e.category) && !e.suspicious_narration) return null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2">
      {neverAuto(e.category) && (
        <span className="fc-chip" style={{ background: "var(--fc-divider)", color: "var(--fc-text-3)" }}>
          Will not guess
        </span>
      )}
      {e.suspicious_narration && <StatusDot tone="bad" dot={false}>Injection flagged</StatusDot>}
    </div>
  );
}

/* ---------- table shell ---------- */

export function DecisionTable({ children }: { children: ReactNode }) {
  return (
    <table className="fc-table">
      <thead>
        <tr>
          <th style={{ width: "15%" }}>Counterparty</th>
          <th>What happened</th>
          <th style={{ width: "12%" }}>Reference</th>
          <th style={{ width: "13%", textAlign: "right" }}>Amount</th>
          <th style={{ width: "11%" }}>Age</th>
          <th style={{ width: "13%" }} />
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

/* ---------- one exception row ---------- */

export function ExceptionRow({
  e,
  asOf,
  onOpen,
  eventsById,
}: {
  e: Exception;
  asOf: string;
  onOpen: Open;
  eventsById: Map<string, TransactionEvent>;
}) {
  const ev = firstEvent(e, eventsById);
  const open = () => onOpen(e.exception_id);
  return (
    <tr className="fc-row-click cursor-pointer" role="button" tabIndex={0} onClick={open} onKeyDown={(k) => keyOpen(k, open)}>
      <td className="fc-ref truncate" title={ev?.counterparty ?? undefined}>
        {ev?.counterparty ? titleCaseShort(ev.counterparty) : <span className="fc-faint">&mdash;</span>}
      </td>
      <td>
        <WhatHappened e={e} />
        <SafetyBadges e={e} />
      </td>
      <td className="truncate">{ev ? <Identifier value={eventReference(ev)} /> : <span className="fc-faint">&mdash;</span>}</td>
      <td className="fc-table-num fc-num">{money(e.amount_paise)}</td>
      <td className={clsx("fc-num", ageUrgent(e, asOf) && "font-medium")} style={ageUrgent(e, asOf) ? { color: "var(--fc-bad)" } : undefined}>
        {ageLabel(e, asOf)}
      </td>
      <td style={{ textAlign: "right" }}>
        <button
          className="fc-btn"
          style={{ padding: "6px 12px", fontSize: 12 }}
          onClick={(ev2: MouseEvent) => {
            ev2.stopPropagation();
            open();
          }}
        >
          {firstVerb(e.recommended_action)}
        </button>
      </td>
    </tr>
  );
}

/* ---------- a cluster row, expandable to its members ---------- */

export function ClusterRow({
  cluster,
  members,
  asOf,
  onOpen,
  onApplyAll,
  eventsById,
  count,
  total,
}: {
  cluster: Cluster;
  members: Exception[];
  asOf: string;
  onOpen: Open;
  onApplyAll: (cluster: Cluster, members: Exception[]) => void;
  eventsById: Map<string, TransactionEvent>;
  /** Server-side member count / total; defaults to the members shown. */
  count?: number;
  total?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const n = count ?? members.length;
  const sum = total ?? sumPaise(members.map((m) => m.amount_paise));
  const fix = cluster.suggested_fix?.trim();

  return (
    <>
      <tr>
        <td colSpan={2}>
          <button
            className="flex items-center gap-2 text-left"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            {expanded ? <ChevronDown size={13} className="fc-faint shrink-0" /> : <ChevronRight size={13} className="fc-faint shrink-0" />}
            <span className="min-w-0">
              <span className="flex items-center gap-1.5" style={{ fontSize: 13, fontWeight: 500 }}>
                <Layers size={11} className="fc-faint" />
                {plural(n, "unbooked entry", "unbooked entries")}
              </span>
              <span className="fc-faint block truncate mt-0.5 text-[12px]" title={fix || cluster.label}>
                {fix || cluster.label}
              </span>
            </span>
          </button>
        </td>
        <td className="fc-faint truncate">{categoryLabel(cluster.root_cause)}</td>
        <td className="fc-table-num fc-num">{money(sum)}</td>
        <td className="fc-faint fc-num">
          {cluster.created_at && asOf ? `${Math.max(0, daysBetween(cluster.created_at, asOf))}d` : "—"}
        </td>
        <td style={{ textAlign: "right" }}>
          <button
            className="fc-btn fc-btn--ghost"
            style={{ padding: "6px 12px", fontSize: 12 }}
            disabled={members.length === 0}
            onClick={() => onApplyAll(cluster, members)}
          >
            Apply to all {n}
          </button>
        </td>
      </tr>
      {expanded &&
        (members.length === 0 ? (
          <tr>
            <td colSpan={6} className="fc-faint">
              No member of this pattern is in the current list.
            </td>
          </tr>
        ) : (
          members.map((m) => (
            <MemberRow key={m.exception_id} e={m} asOf={asOf} onOpen={onOpen} eventsById={eventsById} />
          ))
        ))}
    </>
  );
}

function MemberRow({
  e,
  asOf,
  onOpen,
  eventsById,
}: {
  e: Exception;
  asOf: string;
  onOpen: Open;
  eventsById: Map<string, TransactionEvent>;
}) {
  const ev = firstEvent(e, eventsById);
  const open = () => onOpen(e.exception_id);
  return (
    <tr className="fc-row-click cursor-pointer" role="button" tabIndex={0} onClick={open} onKeyDown={(k) => keyOpen(k, open)} style={{ background: "var(--fc-hover)" }}>
      <td className="fc-ref truncate" style={{ paddingLeft: 30 }}>
        {ev?.counterparty ? titleCaseShort(ev.counterparty) : <span className="fc-faint">&mdash;</span>}
      </td>
      <td>
        <WhatHappened e={e} />
      </td>
      <td className="truncate">{ev ? <Identifier value={eventReference(ev)} /> : <span className="fc-faint">&mdash;</span>}</td>
      <td className="fc-table-num fc-num">{money(e.amount_paise)}</td>
      <td className="fc-faint fc-num">{ageLabel(e, asOf)}</td>
      <td style={{ textAlign: "right" }}>
        <span className="fc-chip">{firstVerb(e.recommended_action)}</span>
      </td>
    </tr>
  );
}

/* ---------- handled row ---------- */

export function HandledRow({ e, onOpen }: { e: Exception; onOpen: Open }) {
  const why = e.resolution_reason?.trim() || e.recommended_action;
  return (
    <div
      className="fc-lrow items-center cursor-pointer transition-colors hover:bg-[var(--fc-card-hover)]"
      role="button"
      tabIndex={0}
      onClick={() => onOpen(e.exception_id)}
      onKeyDown={(k) => keyOpen(k, () => onOpen(e.exception_id))}
    >
      <div className="fc-lrow-name min-w-0">
        <span className="fc-num">{money(e.amount_paise)}</span>
        <span className="fc-faint truncate" title={why}>
          {categoryLabel(e.category)} &middot; {why}
        </span>
      </div>
      <div className="fc-lrow-amt fc-faint">{categoryShort(e.category)}</div>
    </div>
  );
}
