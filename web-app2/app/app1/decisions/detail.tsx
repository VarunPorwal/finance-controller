"use client";

// The evidence pack for one exception, in a right-hand slide-over. The list
// stays visible behind it. Every figure is a server figure; arithmetic is
// shown as arithmetic, never a bare number. Finco-skinned: the panel chrome
// is built directly with fc-card/fc-ev-* classes rather than the old a1
// SlideOver, so this stays visually independent of pages still on the a1
// theme.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import {
  errorMessage,
  useAudit,
  useEvidence,
  useInvalidateAll,
  type Cluster,
  type Evidence,
  type Exception,
  type MatchResult,
  type TransactionEvent,
} from "../_lib/api";
import {
  ACTION_GROUP,
  CATEGORY,
  SOURCE,
  STATUS_LABEL,
  auditActionLabel,
  categoryLabel,
  decidedBy,
  isHumanActor,
  stageLabel,
} from "../_lib/labels";
import {
  daysBetween,
  formatDateLong,
  formatDateShort,
  formatDateTime,
  hashShort,
  money,
  pct,
  relativeDays,
} from "../_lib/format";
import { InstructionBox } from "./instruction";
import { QuickActions } from "./quick-actions";
import { Identifier, RefusalCard, StatusDot } from "../_components/fc-ui";
import { eventReference, isOpen, needsYou, neverAuto, titleCaseShort, type ClusterMode } from "./helpers";

const SOURCES: TransactionEvent["source"][] = ["razorpay", "bank", "ledger"];

function skel(className: string) {
  return <div className={`animate-pulse rounded-[8px] ${className}`} style={{ background: "var(--fc-divider)" }} />;
}

/* ---------- panel ---------- */

export function DetailPanel({
  id,
  ids,
  fallback,
  asOf,
  runId,
  clusterById,
  clusterMode,
  onClose,
  onNavigate,
}: {
  id: string | null;
  ids: string[];
  fallback?: Exception;
  asOf: string;
  runId: string | undefined;
  clusterById: Map<string, Cluster>;
  clusterMode: ClusterMode;
  onClose: () => void;
  onNavigate: (id: string) => void;
}) {
  const ev = useEvidence(id);
  const invalidate = useInvalidateAll();
  const e = ev.data?.exception ?? fallback ?? null;

  const idx = id ? ids.indexOf(id) : -1;
  const prevId = idx > 0 ? ids[idx - 1] : null;
  const nextId = idx >= 0 && idx < ids.length - 1 ? ids[idx + 1] : null;

  useEffect(() => {
    if (!id) return;
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (k: KeyboardEvent) => {
      if (k.key === "Escape") return onClose();
      const t = k.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (k.key === "j" && nextId) onNavigate(nextId);
      if (k.key === "k" && prevId) onNavigate(prevId);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [id, nextId, prevId, onNavigate, onClose]);

  const onApplied = () => void invalidate();

  return (
    <AnimatePresence>
      {id && (
        <>
          <motion.div
            key="scrim"
            className="fixed inset-0 z-40"
            style={{ background: "rgba(0,0,0,0.5)" }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={onClose}
          />
          <motion.aside
            key="panel"
            className="fc-card fc-card--flat fixed right-3 top-3 bottom-3 z-50 flex flex-col"
            style={{ width: "min(720px, calc(100vw - 24px))" }}
            initial={{ transform: "translateX(24px)", opacity: 0 }}
            animate={{ transform: "translateX(0px)", opacity: 1 }}
            exit={{ transform: "translateX(24px)", opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.32, 0.72, 0, 1] }}
            role="dialog"
            aria-modal
          >
            <Header e={e} clusterMode={clusterMode} onClose={onClose} />
            <div className="min-h-0 flex-1 overflow-y-auto" style={{ overscrollBehavior: "contain" }}>
              <Body
                id={id}
                e={e}
                evidence={ev.data}
                loading={ev.isLoading}
                error={ev.error}
                asOf={asOf}
                runId={runId}
                clusterById={clusterById}
                clusterMode={clusterMode}
                onApplied={onApplied}
              />
            </div>
            <div className="flex items-center justify-between border-t px-5 py-3">
              <div className="fc-faint fc-num text-[12px]">{idx >= 0 ? `${idx + 1} of ${ids.length}` : "Not in the current list"}</div>
              <div className="flex items-center gap-2">
                <button
                  className="fc-btn fc-btn--ghost inline-flex items-center gap-1"
                  style={{ padding: "6px 12px", fontSize: 12 }}
                  disabled={!prevId}
                  onClick={() => prevId && onNavigate(prevId)}
                >
                  <ChevronLeft size={14} />
                  Previous
                </button>
                <button
                  className="fc-btn fc-btn--ghost inline-flex items-center gap-1"
                  style={{ padding: "6px 12px", fontSize: 12 }}
                  disabled={!nextId}
                  onClick={() => nextId && onNavigate(nextId)}
                >
                  Next
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

/* ---------- header ---------- */

function Header({ e, clusterMode, onClose }: { e: Exception | null; clusterMode: ClusterMode; onClose: () => void }) {
  return (
    <div className="border-b px-6 pb-4 pt-5">
      <div className="flex items-start justify-between gap-4">
        {e ? (
          <div className="min-w-0">
            <div className="fc-label mb-1.5 inline-flex items-center gap-1.5">
              {ACTION_GROUP[e.action_group].label} &middot; <Identifier value={e.exception_id} />
            </div>
            <div style={{ fontSize: 16, fontWeight: 500 }}>{categoryLabel(e.category)}</div>
            <div className="fc-hero-num fc-num mt-2" style={{ color: needsYou(e) ? "var(--fc-bad)" : "var(--fc-text)" }}>
              {money(e.amount_paise)}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <StatusDot tone={isOpen(e) ? "warn" : "ok"} dot={false}>{STATUS_LABEL[e.status]}</StatusDot>
              {neverAuto(e.category) && (
                <span className="fc-chip" style={{ background: "var(--fc-divider)", color: "var(--fc-text-3)" }}>
                  Will not guess
                </span>
              )}
              {e.suspicious_narration && <StatusDot tone="bad" dot={false}>Injection flagged</StatusDot>}
              {clusterMode && (
                <span className="fc-chip" style={{ background: "var(--fc-divider)", color: "var(--fc-text-3)" }}>
                  One decision for {clusterMode.count}
                </span>
              )}
              <span className="fc-faint text-[12px]">{isOpen(e) ? "Waiting on you" : `Decided by ${decidedBy(e)}`}</span>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2 w-72">{skel("h-4 w-full")}{skel("h-4 w-2/3")}{skel("h-4 w-1/2")}</div>
        )}
        <button
          className="shrink-0 rounded-[8px] p-1.5"
          style={{ color: "var(--fc-text-3)" }}
          onClick={onClose}
          aria-label="Close"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );
}

/* ---------- body ---------- */

function Body({
  id,
  e,
  evidence,
  loading,
  error,
  asOf,
  runId,
  clusterById,
  clusterMode,
  onApplied,
}: {
  id: string;
  e: Exception | null;
  evidence: Evidence | undefined;
  loading: boolean;
  error: Error | null;
  asOf: string;
  runId: string | undefined;
  clusterById: Map<string, Cluster>;
  clusterMode: ClusterMode;
  onApplied: () => void;
}) {
  // A candidate pick or "neither" from the refusal card seeds the free-text
  // instruction box below with a sentence and previews it — there is no
  // per-candidate assignment endpoint, so this reuses the real parse/execute
  // mutation instead of inventing one.
  const [seed, setSeed] = useState<{ text: string; nonce: number } | null>(null);

  if (error) {
    return (
      <div className="p-6 text-[13px]" style={{ color: "var(--fc-bad)" }}>
        {errorMessage(error)}
      </div>
    );
  }
  if (!e) {
    return (
      <div className="flex flex-col gap-5 p-6">
        {skel("h-4 w-2/3")}
        <div className="grid grid-cols-3 gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i}>{skel("h-24 w-full")}</div>
          ))}
        </div>
        {skel("h-24 w-full")}
      </div>
    );
  }

  const events = evidence?.events ?? [];
  const matches = evidence?.matches ?? [];
  const cluster = e.cluster_id ? clusterById.get(e.cluster_id) : undefined;
  const expires = !!e.deadline && (neverAuto(e.category) || e.action_group === "act_today");
  const ambiguous = e.category === "ambiguous_multi_candidate";

  return (
    <div className="flex flex-col gap-4 px-6 py-5">
      {ambiguous ? (
        <Refusal e={e} events={events} loading={loading} onSeed={setSeed} />
      ) : (
        <Card>
          <Resolved e={e} matches={matches} loading={loading} />
        </Card>
      )}
      {expires && e.deadline && <Expires e={e} deadline={e.deadline} asOf={asOf} />}
      <Card>
        <Sources events={events} loading={loading} />
      </Card>
      <Card>
        <Block title="What to do">
          <p className="text-[13.5px] leading-relaxed">{e.recommended_action}</p>
          {e.consequence && (
            <p className="mt-2 text-[12.5px] leading-relaxed" style={{ color: "var(--fc-warn)" }}>
              {e.consequence}
            </p>
          )}
        </Block>
      </Card>
      <InstructionBox
        exception={e}
        runId={runId}
        clusterMode={clusterMode}
        cluster={cluster}
        onApplied={onApplied}
        seedText={seed?.text}
        seedNonce={seed?.nonce}
      />
      <Card>
        <QuickActions exception={e} onApplied={onApplied} />
      </Card>
      <Card>
        <History id={id} />
      </Card>
    </div>
  );
}

/** A compact fc-card block. Keeps the evidence pack a set of distinct
 * sections instead of one long unbroken scroll of full-bleed text. */
function Card({ children }: { children: ReactNode }) {
  return (
    <div className="fc-card" style={{ padding: "14px 16px" }}>
      {children}
    </div>
  );
}

function Block({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <section>
      <div className="mb-2.5">
        <div className="fc-label">{title}</div>
        {sub && <div className="fc-faint mt-0.5 text-[12px]">{sub}</div>}
      </div>
      {children}
    </section>
  );
}

/* ---------- resolved: what arithmetic already proved ---------- */

function Resolved({ e, matches, loading }: { e: Exception; matches: MatchResult[]; loading: boolean }) {
  const rules = e.rules_applied ?? [];
  const closedMatches = matches.filter((m) => m.auto_closed);
  const nothing = !loading && rules.length === 0 && closedMatches.length === 0;
  if (nothing) return null;

  const matchedBy =
    [...closedMatches.map((m) => stageLabel(m.stage)), ...rules.map((r) => r.rule_id)].join(", then ") || "—";

  return (
    <section>
      <div className="fc-label mb-2">Resolved</div>
      <div className="fc-ev-label">Matched by</div>
      <div className="fc-ev-val">{matchedBy}</div>

      <div className="fc-ev-math">
        <span>Amount</span>
        <span className="fc-num">{money(e.amount_paise)}</span>
      </div>
      {rules.map((r, i) => (
        <div key={`${r.rule_id}-${r.version}-${i}`}>
          <div className="fc-ev-math">
            <span>
              {r.rule_id} v{r.version} <span className="fc-faint">({hashShort(r.version_hash)})</span>
            </span>
            <span className="fc-num" style={{ color: "var(--fc-ok)" }}>
              −{money(r.explained_paise)}
            </span>
          </div>
          {r.arithmetic && <div className="fc-ev-rule">{r.arithmetic}</div>}
        </div>
      ))}
      {closedMatches.map((m) => (
        <div key={m.match_id}>
          <div className="fc-ev-math">
            <span>{stageLabel(m.stage)} match</span>
            <span className="fc-num">{pct(m.confidence)} confidence</span>
          </div>
          {m.evidence.map((x, i) =>
            x.arithmetic ? (
              <div key={i} className="fc-ev-rule">
                {x.arithmetic}
              </div>
            ) : null,
          )}
        </div>
      ))}
      <div className="fc-ev-math fc-ev-math--total">
        <span>Residual</span>
        <span className="fc-num" style={{ color: e.residual_paise === 0 ? "var(--fc-ok)" : "var(--fc-warn)" }}>
          {money(e.residual_paise)}
        </span>
      </div>
      {loading && rules.length === 0 && closedMatches.length === 0 && skel("h-16 w-full")}
    </section>
  );
}

/* ---------- unresolved: the refusal state (section 11) ---------- */

/** ambiguous_multi_candidate: the engine would not pick. The candidates here
 * are the real raw rows loaded for this exception (`events`) — the same set
 * the old text list showed. RefusalCard is built for exactly two side by
 * side, so when more than two rows fit, only the first two are offered here
 * and the rest remain visible below in "What each source says"; when fewer
 * than two are loaded, we fall back to a plain notice instead of inventing a
 * second candidate. */
function Refusal({
  e,
  events,
  loading,
  onSeed,
}: {
  e: Exception;
  events: TransactionEvent[];
  loading: boolean;
  onSeed: (seed: { text: string; nonce: number }) => void;
}) {
  if (loading) {
    return (
      <Card>
        <div className="fc-label mb-2">Unresolved</div>
        <div className="grid grid-cols-2 gap-2">
          {skel("h-24 w-full")}
          {skel("h-24 w-full")}
        </div>
      </Card>
    );
  }

  const pair = events.slice(0, 2);
  if (pair.length < 2) {
    return (
      <Card>
        <div className="fc-label mb-2">Unresolved</div>
        <div className="fc-ev-rule">{CATEGORY.ambiguous_multi_candidate.hint}</div>
        <div className="fc-faint mt-3 text-[12.5px]">
          {pair.length === 1
            ? "Only one candidate row is loaded for this exception — not enough to offer a side-by-side choice."
            : "No candidate row is loaded for this exception."}
        </div>
      </Card>
    );
  }

  const candidateLine = (ev: TransactionEvent) =>
    `${ev.counterparty ? titleCaseShort(ev.counterparty) : "an unnamed counterparty"} (${eventReference(ev)}, ${formatDateShort(ev.txn_date)})`;

  const confirm = (i: number) => {
    const ev = pair[i];
    onSeed({
      text: `This is ${candidateLine(ev)} for ${money(ev.amount_paise, { whole: true })}. Book the exception against it.`,
      nonce: Date.now(),
    });
    document.getElementById("instruction-box")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const neither = () => {
    onSeed({
      text: "Neither candidate is the match. Escalate this for someone else to look at.",
      nonce: Date.now(),
    });
    document.getElementById("instruction-box")?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <RefusalCard
      reason={e.consequence?.trim() || CATEGORY.ambiguous_multi_candidate.hint}
      candidates={pair.map((ev) => ({
        label: ev.counterparty ? titleCaseShort(ev.counterparty) : "Unnamed counterparty",
        sub: `${eventReference(ev)} · ${formatDateShort(ev.txn_date)}`,
        amountPaise: ev.amount_paise,
      }))}
      onConfirm={confirm}
      onNeither={neither}
    />
  );
}

function Expires({ e, deadline, asOf }: { e: Exception; deadline: string; asOf: string }) {
  const days = asOf ? daysBetween(asOf, deadline) : null;
  const urgent = days !== null && days <= 0;
  return (
    <div className="fc-card" style={{ borderColor: "color-mix(in srgb, var(--fc-warn) 35%, var(--fc-border))" }}>
      <div className="fc-label" style={{ color: "var(--fc-warn)" }}>
        Money on a clock
      </div>
      <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2" style={{ fontSize: 18 }}>
        <span className="fc-num fc-strong">{money(e.amount_paise)}</span>
        <span>becomes unrecoverable after {formatDateLong(deadline)}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-baseline gap-3 text-[12.5px]">
        {days !== null && (
          <span className="fc-num" style={{ color: urgent ? "var(--fc-bad)" : "var(--fc-text-2)", fontWeight: urgent ? 500 : 400 }}>
            {relativeDays(deadline, asOf)}
          </span>
        )}
        {e.consequence && <span className="fc-muted">{e.consequence}</span>}
      </div>
    </div>
  );
}

/* ---------- three sources, always ---------- */

function Sources({ events, loading }: { events: TransactionEvent[]; loading: boolean }) {
  return (
    <Block title="What each source says" sub="The raw rows this exception is built from, from every file that carries the reference">
      <div className="grid grid-cols-3 gap-3">
        {SOURCES.map((s) => {
          const rows = events.filter((ev) => ev.source === s);
          return (
            <div key={s} className="min-w-0">
              <div className="mb-2 flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-[12px]">
                  {SOURCE[s].short}
                </span>
                <span className="fc-faint fc-num text-[11px]">{rows.length}</span>
              </div>
              {loading ? (
                skel("h-24 w-full")
              ) : rows.length === 0 ? (
                <div className="fc-faint rounded-[10px] border border-dashed px-3 py-6 text-center text-[12px]">
                  No {SOURCE[s].short} row
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {rows.map((ev) => (
                    <EventRow key={ev.event_id} ev={ev} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-3 text-right">
        <a href="/app1/records" className="fc-link">
          View in records →
        </a>
      </div>
    </Block>
  );
}

function EventRow({ ev }: { ev: TransactionEvent }) {
  return (
    <div className="min-w-0 rounded-[10px] border p-3 text-[12px]" style={{ background: "var(--fc-hover)" }}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="fc-faint fc-num">{formatDateShort(ev.txn_date)}</span>
        <span className="flex items-baseline gap-1">
          <span className="fc-num fc-strong">{money(ev.amount_paise)}</span>
          <span className="fc-faint text-[10.5px] uppercase">{ev.direction === "credit" ? "Cr" : "Dr"}</span>
        </span>
      </div>
      <div className="mt-1.5">
        <Identifier value={eventReference(ev)} />
      </div>
      {ev.counterparty && (
        <div className="fc-muted truncate mt-1" title={ev.counterparty}>
          {titleCaseShort(ev.counterparty)}
        </div>
      )}
      {ev.raw_narration && (
        <div className="fc-faint truncate mt-1 text-[11.5px]" title={ev.raw_narration}>
          {ev.raw_narration}
        </div>
      )}
    </div>
  );
}

/* ---------- history, always ---------- */

function actorName(actor: string): string {
  return isHumanActor(actor) ? actor.slice("user:".length) || "Human" : actor;
}

function History({ id }: { id: string }) {
  const audit = useAudit({ subject_id: id, subject_type: "exception", limit: 20 });
  const rows = useMemo(
    () =>
      [...(audit.data ?? [])].sort(
        (a, b) => Number(isHumanActor(b.actor)) - Number(isHumanActor(a.actor)) || b.seq - a.seq,
      ),
    [audit.data],
  );
  return (
    <Block title="History" sub="From the audit chain — resolved by a stage, a rule, or a person and when. People first.">
      {audit.isLoading ? (
        skel("h-16 w-full")
      ) : audit.error ? (
        <div className="text-[12.5px]" style={{ color: "var(--fc-bad)" }}>
          {errorMessage(audit.error)}
        </div>
      ) : rows.length === 0 ? (
        <div className="fc-faint text-[12.5px]">Nothing has been done to this yet. The first decision starts its history.</div>
      ) : (
        <div className="rounded-[10px] border divide-y" style={{ background: "var(--fc-hover)" }}>
          {rows.map((r) => {
            const reason = typeof r.payload.reason === "string" ? r.payload.reason : null;
            return (
              <div key={r.seq} className="px-3 py-2.5 text-[12px]">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="fc-chip">{actorName(r.actor)}</span>
                    <span style={{ fontWeight: 500 }}>{auditActionLabel(r.action)}</span>
                  </div>
                  <span className="fc-faint fc-num">{formatDateTime(r.created_at)}</span>
                </div>
                {reason && <div className="fc-muted mt-1">{reason}</div>}
              </div>
            );
          })}
        </div>
      )}
    </Block>
  );
}
