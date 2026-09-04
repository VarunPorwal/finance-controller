"use client";

// The chain as a seal: one segment per event, oldest on the left. During a
// verification a highlight sweeps across it; once the verdict is in, every
// segment is underlined green (intact) or the run from the first break is
// turned coral.

import { useState, type ReactNode } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import type { AuditEvent, S } from "../_lib/api";
import { auditActionLabel } from "../_lib/labels";
import { formatDateTime } from "../_lib/format";
import { CHAIN_COLOR, actorName, chainKind } from "./actors";

export type VerifyChainOut = S["VerifyChainOut"];
export type Phase = "idle" | "sweeping" | "done";

export const SWEEP_MS = 1600;
export const CHAIN_CAP = 200;

const MONO = "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";

/** A minimal hover tooltip, themed with fc- tokens only (the shared `Tip` in
 * `_components/motion.tsx` is styled for the old `.a1` surface and is used by
 * pages this pass does not touch). */
function SegTip({ label, children }: { label: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span
      className="relative inline-flex w-full"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      {children}
      <AnimatePresence>
        {open && (
          <motion.span
            role="tooltip"
            className="pointer-events-none absolute left-1/2 z-50 w-max max-w-[260px]"
            style={{
              bottom: "calc(100% + 6px)",
              transform: "translateX(-50%)",
              background: "var(--fc-card)",
              border: "1px solid var(--fc-border)",
              borderRadius: 8,
              padding: "7px 10px",
              fontSize: 11.5,
              lineHeight: 1.5,
              color: "var(--fc-text-2)",
            }}
            initial={{ opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
          >
            {label}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  );
}

export function ChainStrip({
  events,
  phase,
  result,
  onSelect,
}: {
  /** Ascending by seq, already capped. */
  events: AuditEvent[];
  phase: Phase;
  result: VerifyChainOut | null;
  onSelect: (seq: number) => void;
}) {
  const reduced = useReducedMotion();
  const n = events.length;
  const sweeping = phase === "sweeping";
  const settled = phase === "done" && result !== null;
  const valid = settled && result.valid;
  const breakAt = settled && !result.valid ? (result.first_break_seq ?? null) : null;

  const legend = [
    { label: "People", color: CHAIN_COLOR.human },
    { label: "System", color: CHAIN_COLOR.system },
    { label: "Settings and rules", color: CHAIN_COLOR.settings },
  ];

  if (n === 0) {
    return <div className="fc-faint" style={{ fontSize: 12 }}>No events to draw yet.</div>;
  }

  return (
    <div>
      <div className="relative">
        <div className="grid gap-[2px]" style={{ gridTemplateColumns: `repeat(${n}, minmax(2px, 1fr))` }}>
          {events.map((e, i) => {
            const kind = chainKind(e);
            const broken = breakAt !== null && e.seq >= breakAt;
            const color = broken ? "var(--fc-bad)" : CHAIN_COLOR[kind];
            const delay = reduced ? 0 : (i / Math.max(1, n - 1)) * (SWEEP_MS / 1000) * 0.92;
            return (
              <SegTip
                key={e.seq}
                label={
                  <span className="flex flex-col gap-0.5">
                    <span>
                      <span className="fc-num" style={{ fontFamily: MONO }}>#{e.seq}</span> · {auditActionLabel(e.action)}
                    </span>
                    <span className="fc-faint">
                      {actorName(e.actor)} · <span style={{ fontFamily: MONO }}>{formatDateTime(e.created_at)}</span>
                    </span>
                  </span>
                }
              >
                <button
                  type="button"
                  aria-label={`Event ${e.seq}, ${auditActionLabel(e.action)}`}
                  onClick={() => onSelect(e.seq)}
                  className="flex w-full flex-col gap-[3px] outline-none"
                  style={{ cursor: "pointer" }}
                >
                  <motion.span
                    className="block h-[26px] w-full rounded-[2px]"
                    style={{ background: color }}
                    initial={false}
                    animate={
                      sweeping
                        ? { opacity: [0.42, 1, 0.62], scaleY: [1, 1.12, 1] }
                        : { opacity: settled ? (broken ? 0.9 : 0.72) : 0.5, scaleY: 1 }
                    }
                    whileHover={{ opacity: 1 }}
                    transition={sweeping ? { duration: 0.42, delay, ease: "easeOut" } : { duration: 0.25 }}
                  />
                  <motion.span
                    className="block h-[2px] w-full rounded-full"
                    style={{ background: broken ? "var(--fc-bad)" : "var(--fc-ok)" }}
                    initial={false}
                    animate={{ opacity: settled ? (valid || broken ? 0.75 : 0) : 0 }}
                    transition={{ duration: 0.35, delay: reduced ? 0 : 0.05 + (i / Math.max(1, n)) * 0.5 }}
                  />
                </button>
              </SegTip>
            );
          })}
        </div>

        {sweeping && !reduced && (
          <motion.div
            aria-hidden
            className="pointer-events-none absolute top-[-6px] bottom-[-6px] w-[72px]"
            style={{
              background:
                "linear-gradient(90deg, transparent, rgba(255,255,255,0.16) 45%, rgba(62,168,43,0.55) 60%, transparent)",
              filter: "blur(1px)",
              mixBlendMode: "screen",
            }}
            initial={{ left: "-72px" }}
            animate={{ left: "100%" }}
            transition={{ duration: SWEEP_MS / 1000, ease: [0.3, 0, 0.2, 1] }}
          />
        )}
      </div>

      <div className="fc-faint mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-1" style={{ fontSize: 11.5 }}>
        <div className="flex items-center gap-4">
          {legend.map((l) => (
            <span key={l.label} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-[2px]" style={{ background: l.color, opacity: 0.8 }} />
              {l.label}
            </span>
          ))}
        </div>
        <span>
          Oldest on the left · latest <span className="fc-num" style={{ fontFamily: MONO }}>{n}</span> events · hover for
          detail, click to jump
        </span>
      </div>
    </div>
  );
}
