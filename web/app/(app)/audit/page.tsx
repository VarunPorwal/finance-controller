"use client";

// Audit Trail. "Can I prove what happened?" The chain verifies itself on
// demand; the log shows who did what; the export carries the hashes out.
// Reskinned to the Finco design system (finco-tokens.css, `_components/fc-ui`).

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { ChevronDown, Download, FileJson } from "lucide-react";
import { errorMessage, useAuditAll, writes, type AuditEvent } from "../_lib/api";
import { isHumanActor } from "../_lib/labels";
import { formatCount, plural } from "../_lib/format";
import { FcCard, FcCardHeader, FcDivider, FcEmpty, FcErrorNote, FcHead, FcPage, FcSkeleton } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";
import { CHAIN_CAP, ChainStrip, SWEEP_MS, type Phase, type VerifyChainOut } from "./chain";
import { ChainVerdict } from "./verdict";
import { AuditTable } from "./table";
import { actionCategory, actorName, type ActionCategory } from "./actors";

const MONO = "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";

/** Fade-in on mount only, staggered by index — the wrapper never unmounts on
 * data refresh, so re-fetches don't replay the animation. */
function FadeCard({ index, children }: { index: number; children: ReactNode }) {
  const reduced = useReducedMotion();
  if (reduced) return <>{children}</>;
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2, delay: index * 0.04 }}>
      {children}
    </motion.div>
  );
}

type ActorTab = "people" | "system" | "all";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const EXPORT_FORMATS: { format: "csv" | "jsonl"; label: string; hint: string; icon: typeof Download }[] = [
  { format: "csv", label: "CSV", hint: "Flat rows for a spreadsheet.", icon: Download },
  { format: "jsonl", label: "JSONL", hint: "Full payload, one event per line.", icon: FileJson },
];

const CATS: { value: ActionCategory; label: string }[] = [
  { value: "decisions", label: "Decisions" },
  { value: "rules", label: "Rules" },
  { value: "runs", label: "Runs" },
];

function sleep(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

/** Export ▾ — the only formats offered are the ones the API actually serves
 * (`/api/v1/audit/export?format=csv|jsonl`, same endpoint used elsewhere in
 * the app, e.g. settlements/signoff.tsx). No "evidence pack" option exists
 * server-side, so none is offered here. */
function ExportMenu() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (ev: MouseEvent) => {
      if (ref.current && !ref.current.contains(ev.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button type="button" className="fc-btn fc-btn--ghost" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open}>
        Export
        <ChevronDown size={13} />
      </button>
      {open && (
        <div
          role="menu"
          className="fc-card"
          style={{ position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 20, minWidth: 240, padding: 6 }}
        >
          {EXPORT_FORMATS.map((f) => (
            <a
              key={f.format}
              role="menuitem"
              href={`${API_BASE}/api/v1/audit/export?format=${f.format}`}
              target="_blank"
              rel="noreferrer"
              onClick={() => setOpen(false)}
              className="flex items-start gap-2.5"
              style={{ padding: "8px 8px", borderRadius: "var(--fc-r-sm)" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "var(--fc-hover)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <f.icon size={14} className="fc-faint mt-0.5" />
              <span className="min-w-0">
                <span className="block fc-strong" style={{ fontSize: 12.5 }}>{f.label}</span>
                <span className="fc-faint block" style={{ fontSize: 11 }}>{f.hint}</span>
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function CategoryFilter({ selected, onToggle }: { selected: Set<ActionCategory>; onToggle: (c: ActionCategory | "all") => void }) {
  const allOn = selected.size === CATS.length;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {CATS.map((c) => {
        const active = allOn || selected.has(c.value);
        return (
          <button
            key={c.value}
            type="button"
            aria-pressed={active}
            onClick={() => onToggle(c.value)}
            className={active ? "fc-btn" : "fc-btn fc-btn--ghost"}
            style={{ padding: "6px 12px", fontSize: 12 }}
          >
            {c.label}
          </button>
        );
      })}
      <button
        type="button"
        aria-pressed={allOn}
        onClick={() => onToggle("all")}
        className={allOn ? "fc-btn" : "fc-btn fc-btn--ghost"}
        style={{ padding: "6px 12px", fontSize: 12 }}
      >
        All
      </button>
    </div>
  );
}

/** People, listed first with what each changed; the system summarised by
 * action type rather than enumerated (spec section 4). Pure aggregation of
 * real event counts — no figure derived here is financial. */
function WhoDidWhat({
  events,
  activeActor,
  onPickActor,
  onClear,
}: {
  events: AuditEvent[];
  activeActor: string | null;
  onPickActor: (actor: string) => void;
  onClear: () => void;
}) {
  const { people, systemTotal, systemByAction } = useMemo(() => {
    const byActor = new Map<string, { actions: Map<string, number>; count: number }>();
    let sysTotal = 0;
    const sysByAction = new Map<string, number>();
    for (const e of events) {
      if (isHumanActor(e.actor)) {
        const cur = byActor.get(e.actor) ?? { actions: new Map(), count: 0 };
        cur.count += 1;
        cur.actions.set(e.action, (cur.actions.get(e.action) ?? 0) + 1);
        byActor.set(e.actor, cur);
      } else {
        sysTotal += 1;
        sysByAction.set(e.action, (sysByAction.get(e.action) ?? 0) + 1);
      }
    }
    const peopleList = [...byActor.entries()]
      .map(([actor, v]) => ({
        actor,
        count: v.count,
        actions: [...v.actions.entries()].sort((a, b) => b[1] - a[1]),
      }))
      .sort((a, b) => b.count - a.count);
    const sysList = [...sysByAction.entries()].sort((a, b) => b[1] - a[1]);
    return { people: peopleList, systemTotal: sysTotal, systemByAction: sysList };
  }, [events]);

  if (people.length === 0 && systemTotal === 0) {
    return <FcEmpty title="Nothing here yet" sub="Actions in view will be grouped by who did them." />;
  }

  return (
    <div className="flex flex-1 flex-col" style={{ padding: "2px 0 6px" }}>
      {people.map((p) => {
        const isActive = activeActor === p.actor;
        return (
          <button
            key={p.actor}
            type="button"
            onClick={() => (isActive ? onClear() : onPickActor(p.actor))}
            className="fc-lrow w-full text-left"
            style={{ background: isActive ? "var(--fc-row-sel)" : undefined, cursor: "pointer" }}
          >
            <span className="min-w-0">
              <span className="fc-row-val fc-strong">{actorName(p.actor)}</span>
              <span className="fc-label mt-1 block truncate" style={{ maxWidth: 460 }}>
                {p.actions
                  .slice(0, 4)
                  .map(([action, n]) => `${actionShort(action)}${n > 1 ? ` ×${n}` : ""}`)
                  .join(" · ")}
                {p.actions.length > 4 ? ` · +${p.actions.length - 4} more` : ""}
              </span>
            </span>
            <span className="fc-num fc-strong shrink-0 self-center" style={{ fontFamily: MONO }}>
              {formatCount(p.count)}
            </span>
          </button>
        );
      })}
      {systemTotal > 0 && (
        <div className="fc-lrow items-center" style={{ opacity: 0.9 }}>
          <span className="min-w-0">
            <span className="fc-row-val fc-strong">System</span>
            <span className="fc-label mt-1 block truncate" style={{ maxWidth: 460 }}>
              {systemByAction
                .slice(0, 4)
                .map(([action, n]) => `${actionShort(action)} ×${n}`)
                .join(" · ")}
              {systemByAction.length > 4 ? ` · +${systemByAction.length - 4} more` : ""}
            </span>
          </span>
          <span className="fc-num fc-strong shrink-0 self-center" style={{ fontFamily: MONO }}>
            {formatCount(systemTotal)}
          </span>
        </div>
      )}
    </div>
  );
}

function actionShort(action: string): string {
  const dot = action.indexOf(".");
  return dot === -1 ? action : action.slice(dot + 1).replace(/_/g, " ");
}

/** A compact stat rail paired with the filter tabs — companion content for
 * the `fc-split` so the filter card and the "who did what" list don't sit as
 * two lone narrow blocks with blank space on either side. */
function ScopeStats({ inView, total, actorCount, systemCount }: { inView: number; total: number; actorCount: number; systemCount: number }) {
  const rows: { label: string; value: number }[] = [
    { label: "Events in view", value: inView },
    { label: "Total on record", value: total },
    { label: "People involved", value: actorCount },
    { label: "Written by the system", value: systemCount },
  ];
  return (
    <div className="flex flex-1 flex-col" style={{ padding: "2px 0 6px" }}>
      {rows.map((r) => (
        <div key={r.label} className="fc-lrow">
          <span className="fc-label">{r.label}</span>
          <span className="fc-num fc-strong" style={{ fontFamily: MONO }}>
            <CountUp value={r.value} />
          </span>
        </div>
      ))}
    </div>
  );
}

export default function AuditPage() {
  const audit = useAuditAll(400);
  const reduced = useReducedMotion();

  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<VerifyChainOut | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [tab, setTab] = useState<ActorTab>("all");
  const [activeActor, setActiveActor] = useState<string | null>(null);
  const [cats, setCats] = useState<Set<ActionCategory>>(() => new Set(["decisions", "runs"]));
  const [flashSeq, setFlashSeq] = useState<number | null>(null);

  const newestFirst = useMemo(() => [...(audit.data ?? [])].sort((a, b) => b.seq - a.seq), [audit.data]);
  const chainEvents = useMemo(() => newestFirst.slice(0, CHAIN_CAP).reverse(), [newestFirst]);
  const total = newestFirst.length;

  const allCats = cats.size === CATS.length;
  const categoryFiltered = useMemo(
    () => (allCats ? newestFirst : newestFirst.filter((e) => cats.has(actionCategory(e.action)))),
    [newestFirst, cats, allCats],
  );

  const people = useMemo(() => categoryFiltered.filter((e) => isHumanActor(e.actor)), [categoryFiltered]);
  const system = useMemo(() => categoryFiltered.filter((e) => !isHumanActor(e.actor)), [categoryFiltered]);
  const actorCount = useMemo(() => new Set(people.map((e) => e.actor)).size, [people]);

  const visible = useMemo(() => {
    let rows = tab === "people" ? people : tab === "system" ? system : categoryFiltered;
    if (activeActor) rows = rows.filter((e) => e.actor === activeActor);
    return rows;
  }, [tab, people, system, categoryFiltered, activeActor]);

  const toggleCat = useCallback((c: ActionCategory | "all") => {
    setCats((prev) => {
      if (c === "all") return new Set(CATS.map((x) => x.value));
      const next = new Set(prev.size === CATS.length ? [] : prev);
      if (next.has(c)) {
        if (next.size > 1) next.delete(c);
      } else {
        next.add(c);
      }
      return next;
    });
  }, []);

  const pickActor = useCallback((actor: string) => {
    setActiveActor(actor);
    setTab("people");
  }, []);
  const clearActor = useCallback(() => setActiveActor(null), []);

  const verify = useCallback(async () => {
    setPhase("sweeping");
    setResult(null);
    setVerifyError(null);
    const started = Date.now();
    const res = await writes.verifyChain();
    const remaining = reduced ? 0 : Math.max(0, SWEEP_MS - (Date.now() - started));
    await sleep(remaining);
    if (res.error || !res.data) setVerifyError(errorMessage(res.error));
    else setResult(res.data);
    setPhase("done");
  }, [reduced]);

  const jumpTo = useCallback(
    (seq: number) => {
      const target = newestFirst.find((e) => e.seq === seq);
      if (!target) return;
      setActiveActor(null);
      setCats(new Set(CATS.map((x) => x.value)));
      setTab("all");
      setFlashSeq(seq);
      setTimeout(() => document.getElementById(`audit-row-${seq}`)?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" }), 60);
    },
    [newestFirst, reduced],
  );

  useEffect(() => {
    if (flashSeq === null) return;
    const t = setTimeout(() => setFlashSeq(null), 1800);
    return () => clearTimeout(t);
  }, [flashSeq]);

  return (
    <FcPage>
      <FcHead
        title="Audit Trail"
        sub="Can I prove what happened?"
        actions={<ExportMenu />}
      />

      {audit.error ? (
        <FcErrorNote message={audit.error.message} />
      ) : (
        <>
          {/* 1. Verdict + 2. The chain */}
          <FadeCard index={0}>
            <FcCard variant="hero" className="mb-3">
              {audit.isPending ? (
                <div className="flex flex-col gap-4">
                  <FcSkeleton className="h-8 w-[60%]" />
                  <FcSkeleton className="h-5 w-[45%]" />
                  <FcSkeleton className="h-[30px] w-full" />
                </div>
              ) : (
                <>
                  <ChainVerdict total={total} phase={phase} result={result} error={verifyError} onVerify={verify} />
                  <FcDivider className="my-[18px]" />
                  <div className="fc-label mb-3" style={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    The chain
                  </div>
                  <ChainStrip events={chainEvents} phase={phase} result={result} onSelect={jumpTo} />
                </>
              )}
            </FcCard>
          </FadeCard>

          {/* 3. Filter + 4. Who did what, paired so neither sits alone as a
              lone narrow block with blank space either side. Stretched to a
              shared row height (`fc-split` normally aligns items to the
              start) so a short actor list never reads as a half-empty card
              beside a full stat rail. */}
          <div className="fc-split mb-3" style={{ alignItems: "stretch" }}>
            <FcCard variant="flat" className="flex flex-col">
              <FcCardHeader
                title="Who did what"
                sub={
                  audit.isPending ? undefined : (
                    <>
                      <span className="fc-num" style={{ fontFamily: MONO }}>{formatCount(people.length)}</span> by people
                      · <span className="fc-num" style={{ fontFamily: MONO }}>{formatCount(system.length)}</span> by the
                      system
                    </>
                  )
                }
                right={
                  <div className="flex items-center gap-1.5">
                    {(["all", "people", "system"] as ActorTab[]).map((t) => (
                      <button
                        key={t}
                        type="button"
                        aria-pressed={tab === t && !activeActor}
                        onClick={() => {
                          setTab(t);
                          setActiveActor(null);
                        }}
                        className={tab === t && !activeActor ? "fc-btn" : "fc-btn fc-btn--ghost"}
                        style={{ padding: "5px 11px", fontSize: 11.5 }}
                      >
                        {t === "all" ? "All" : t === "people" ? "People" : "System"}
                      </button>
                    ))}
                  </div>
                }
              />
              {audit.isPending ? (
                <div className="flex flex-col gap-3" style={{ padding: "0 16px 16px" }}>
                  {Array.from({ length: 4 }).map((_, i) => (
                    <FcSkeleton key={i} className="h-[34px] w-full" />
                  ))}
                </div>
              ) : (
                <WhoDidWhat events={categoryFiltered} activeActor={activeActor} onPickActor={pickActor} onClear={clearActor} />
              )}
            </FcCard>

            <div className="fc-stack" style={{ display: "flex", flexDirection: "column", height: "100%" }}>
              <FcCard style={{ padding: "12px 14px" }}>
                <div className="fc-label mb-2.5" style={{ textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Scope
                </div>
                <CategoryFilter selected={cats} onToggle={toggleCat} />
              </FcCard>
              <FcCard variant="flat" className="flex flex-1 flex-col">
                {audit.isPending ? (
                  <div className="flex flex-col gap-3" style={{ padding: "14px 16px" }}>
                    {Array.from({ length: 4 }).map((_, i) => (
                      <FcSkeleton key={i} className="h-[22px] w-full" />
                    ))}
                  </div>
                ) : (
                  <ScopeStats inView={categoryFiltered.length} total={total} actorCount={actorCount} systemCount={system.length} />
                )}
              </FcCard>
            </div>
          </div>

          {/* 5. Event log */}
          <FadeCard index={1}>
            <FcCard variant="flat" className="mb-3">
              <FcCardHeader
                title="Event log"
                sub={
                  activeActor
                    ? <>Filtered to <span className="fc-strong">{actorName(activeActor)}</span> · <button type="button" onClick={clearActor} className="fc-link" style={{ background: "none", border: 0, cursor: "pointer" }}>clear</button></>
                    : `${plural(visible.length, "event")} shown`
                }
              />
              {audit.isPending ? (
                <div className="flex flex-col gap-3" style={{ padding: "0 16px 16px" }}>
                  {Array.from({ length: 8 }).map((_, i) => (
                    <FcSkeleton key={i} className="h-[22px] w-full" />
                  ))}
                </div>
              ) : (
                <AuditTable
                  events={visible}
                  flashSeq={flashSeq}
                  emptyHint={
                    activeActor
                      ? "No events match this actor within the current filter."
                      : tab === "people"
                        ? "Resolving, escalating or writing off a decision, or activating a rule, will appear here under your name."
                        : tab === "system"
                          ? "Runs, rechecks and ingests written by the scheduler will appear here."
                          : "Every action on decisions, rules, runs and settings will appear here as it happens."
                  }
                />
              )}
            </FcCard>
          </FadeCard>

          <div className="flex flex-wrap items-center justify-between gap-3" style={{ padding: "0 4px" }}>
            <p className="fc-faint" style={{ fontSize: 12.5 }}>
              The export carries every hash, so anyone can re-verify it without this app.
            </p>
            <ExportMenu />
          </div>
        </>
      )}
    </FcPage>
  );
}
