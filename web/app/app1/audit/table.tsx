"use client";

// The event log. One row per event; expand a row to see the payload as the
// server stored it and the two hashes that bind it into the chain. Truncates
// the tail of an id, never the head, so the identifying prefix stays visible.

import { Fragment, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, ChevronRight } from "lucide-react";
import type { AuditEvent } from "../_lib/api";
import { auditActionLabel, isHumanActor } from "../_lib/labels";
import { formatDateTime, hashShort, shortId } from "../_lib/format";
import { FcChip, FcEmpty, Identifier, StatusDot } from "../_components/fc-ui";
import { actorName, glance, subjectHref } from "./actors";

const MONO = "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";

export function AuditTable({
  events,
  flashSeq,
  emptyHint,
}: {
  /** Newest first. */
  events: AuditEvent[];
  flashSeq: number | null;
  emptyHint: string;
}) {
  const [open, setOpen] = useState<Set<number>>(() => new Set());

  function toggle(seq: number) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  }

  if (events.length === 0) {
    return <FcEmpty title="Nothing on record here" sub={emptyHint} />;
  }

  return (
    <div style={{ maxHeight: 720, overflow: "auto" }}>
      <table className="fc-table" style={{ tableLayout: "auto" }}>
        <thead>
          <tr>
            <th style={{ width: 28 }} />
            <th style={{ width: 72 }}>Seq</th>
            <th style={{ width: 130 }}>Time</th>
            <th style={{ width: 160 }}>Actor</th>
            <th style={{ width: 170 }}>Action</th>
            <th style={{ width: 200 }}>Subject</th>
            <th>Before / after</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => {
            const isOpen = open.has(e.seq);
            const human = isHumanActor(e.actor);
            const href = subjectHref(e.subject_type, e.subject_id);
            const g = glance(e.payload ?? {});
            const flashing = flashSeq === e.seq;
            return (
              <Fragment key={e.seq}>
                <tr
                  id={`audit-row-${e.seq}`}
                  onClick={() => toggle(e.seq)}
                  className="fc-row-click"
                  style={{
                    background: flashing ? "rgba(62,168,43,0.12)" : undefined,
                    boxShadow: flashing ? "inset 2px 0 0 var(--fc-ok)" : undefined,
                    transition: "background 600ms ease, box-shadow 600ms ease",
                  }}
                >
                  <td className="fc-faint">
                    <motion.span
                      className="inline-flex"
                      animate={{ rotate: isOpen ? 90 : 0 }}
                      transition={{ type: "spring", stiffness: 400, damping: 32 }}
                    >
                      <ChevronRight size={13} />
                    </motion.span>
                  </td>
                  <td className="fc-num fc-muted" style={{ fontFamily: MONO }}>#{e.seq}</td>
                  <td className="fc-muted fc-num" style={{ whiteSpace: "nowrap", fontFamily: MONO }}>{formatDateTime(e.created_at)}</td>
                  <td title={e.actor}>
                    <StatusDot tone={human ? "accent" : "ok"}>
                      <span className="overflow-hidden text-ellipsis whitespace-nowrap" style={{ maxWidth: 110, display: "inline-block" }}>
                        {actorName(e.actor)}
                      </span>
                    </StatusDot>
                  </td>
                  <td>
                    <span className="inline-flex items-center gap-1.5">
                      {auditActionLabel(e.action)}
                      {g.dryRun && <FcChip>dry run</FcChip>}
                    </span>
                  </td>
                  <td onClick={(ev) => ev.stopPropagation()}>
                    <span className="inline-flex items-center gap-1.5">
                      <span className="fc-faint">{e.subject_type}</span>
                      {href ? (
                        <Link
                          href={href}
                          className="fc-num inline-flex items-center gap-1"
                          style={{ color: "var(--fc-text)", textDecoration: "underline", textDecorationColor: "var(--fc-border)", textUnderlineOffset: 4 }}
                          title={e.subject_id}
                        >
                          {shortId(e.subject_id)}
                          <ArrowRight size={11} className="fc-faint" />
                        </Link>
                      ) : (
                        <span className="fc-num fc-muted" title={e.subject_id}>
                          {shortId(e.subject_id)}
                        </span>
                      )}
                    </span>
                  </td>
                  <td style={{ maxWidth: 420 }}>
                    <Glance g={g} />
                  </td>
                </tr>
                <AnimatePresence initial={false}>
                  {isOpen && (
                    <tr key={`${e.seq}-x`}>
                      <td colSpan={7} style={{ paddingTop: 0, paddingBottom: 0, background: "var(--fc-hover)" }}>
                        <motion.div
                          initial={{ opacity: 0, height: 0 }}
                          animate={{ opacity: 1, height: "auto" }}
                          exit={{ opacity: 0, height: 0 }}
                          transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}
                          style={{ overflow: "hidden" }}
                        >
                          <Expanded e={e} />
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
  );
}

function Glance({ g }: { g: ReturnType<typeof glance> }) {
  if (!g.quote && !g.transition && g.pairs.length === 0) return <span className="fc-faint">—</span>;
  return (
    <div className="flex flex-col gap-0.5" style={{ fontSize: 12.5 }}>
      {g.transition && (
        <span className="inline-flex items-center gap-1.5">
          <span className="fc-muted">{g.transition[0]}</span>
          <ArrowRight size={11} className="fc-faint" />
          <span className="fc-strong">{g.transition[1]}</span>
        </span>
      )}
      {g.quote && (
        <span
          className="overflow-hidden text-ellipsis whitespace-nowrap"
          style={{ maxWidth: 400 }}
          title={g.quote}
        >
          &ldquo;{g.quote}&rdquo;
        </span>
      )}
      {g.pairs.length > 0 && (
        <span className="fc-faint flex flex-wrap gap-x-3" style={{ fontSize: 11.5 }}>
          {g.pairs.map(([k, v]) => (
            <span key={k}>
              {k} <span className="fc-muted">{v}</span>
            </span>
          ))}
        </span>
      )}
    </div>
  );
}

function Expanded({ e }: { e: AuditEvent }) {
  const json = JSON.stringify(e.payload ?? {}, null, 2);
  return (
    <div className="flex flex-col gap-3" style={{ padding: "12px 12px 12px 40px" }}>
      <div className="fc-num flex flex-wrap items-center gap-2" style={{ fontSize: 11.5 }}>
        <span className="fc-faint">prev</span>
        <span className="fc-muted" title={e.prev_hash}>
          {hashShort(e.prev_hash, 12)}
        </span>
        <ArrowRight size={11} className="fc-faint" />
        <span className="fc-faint">this</span>
        <span style={{ color: "var(--fc-ok)" }} title={e.this_hash}>
          {hashShort(e.this_hash, 12)}
        </span>
        {e.ruleset_hash && (
          <>
            <span className="fc-faint ml-3">ruleset</span>
            <span className="fc-muted" title={e.ruleset_hash}>
              {hashShort(e.ruleset_hash, 12)}
            </span>
          </>
        )}
        {e.run_id && (
          <>
            <span className="fc-faint ml-3">run</span>
            <span className="fc-muted" title={e.run_id}>
              {shortId(e.run_id)}
            </span>
          </>
        )}
        <span className="fc-faint ml-3">subject</span>
        <Identifier value={e.subject_id} />
      </div>
      <pre
        className="fc-num"
        style={{
          background: "var(--fc-bg)",
          border: "1px solid var(--fc-divider)",
          borderRadius: 10,
          padding: "10px 12px",
          fontSize: 11.5,
          lineHeight: 1.55,
          color: "var(--fc-text-2)",
          maxHeight: 320,
          overflow: "auto",
        }}
      >
        {json}
      </pre>
    </div>
  );
}
