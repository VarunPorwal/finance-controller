"use client";

// Decisions. "Where is my money unexplained, and what do I do about it?"
// Finco-skinned: bands in priority order, each a table of counterparty /
// what happened / reference / amount / age / action. Confidence, tier and
// cause-cluster columns are dropped — confidence never explains an open
// item, tier reads HIGH on every row, and cause-cluster duplicates the
// exception column. A cluster still collapses to one row and expands.

import { Suspense, useCallback, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, ChevronDown, Clock3, MessageSquare, RefreshCw, Search } from "lucide-react";
import {
  errorMessage,
  useClusters,
  useCurrentRun,
  useEvents,
  useExceptions,
  type Cluster,
  type Exception,
  type TransactionEvent,
} from "../_lib/api";
import { ACTION_GROUP, CATEGORY, type ActionGroup } from "../_lib/labels";
import { daysBetween, money, plural, shortId, sumPaise } from "../_lib/format";
import { useShell } from "../_components/shell/shell-context";
import { CountUp } from "../_components/motion";
import { BandHeader, ClusterRow, DeadlineChip, DecisionTable, ExceptionRow, HandledRow } from "./cards";
import { DetailPanel } from "./detail";
import {
  CATEGORIES,
  GROUP_ORDER,
  byPriority,
  eventReference,
  firstEvent,
  handledWithoutYou,
  isCategory,
  isOpen,
  needsYou,
  priority,
  toneVar,
  type ClusterMode,
  type StatusFilter,
} from "./helpers";

export default function DecisionsPage() {
  return (
    <Suspense fallback={<DecisionsSkeleton />}>
      <DecisionsScreen />
    </Suspense>
  );
}

/* ---------- list structure ---------- */

type Entry =
  | { kind: "one"; e: Exception; priority: number }
  | { kind: "cluster"; cluster: Cluster; members: Exception[]; priority: number };

function buildEntries(items: Exception[], clusterById: Map<string, Cluster>, collapse: boolean): Entry[] {
  const entries: Entry[] = [];
  const consumed = new Set<string>();
  if (collapse) {
    const groups = new Map<string, Exception[]>();
    for (const e of items) {
      if (!e.cluster_id || !clusterById.has(e.cluster_id)) continue;
      groups.set(e.cluster_id, [...(groups.get(e.cluster_id) ?? []), e]);
    }
    for (const [cid, members] of groups) {
      const cluster = clusterById.get(cid);
      if (!cluster || members.length < 2) continue;
      const sorted = [...members].sort(byPriority);
      entries.push({ kind: "cluster", cluster, members: sorted, priority: priority(sorted[0]) });
      for (const m of members) consumed.add(m.exception_id);
    }
  }
  for (const e of items) {
    if (!consumed.has(e.exception_id)) entries.push({ kind: "one", e, priority: priority(e) });
  }
  entries.sort((a, b) => b.priority - a.priority);
  return entries;
}

function entryIds(entries: Entry[]): string[] {
  const ids: string[] = [];
  for (const en of entries) {
    if (en.kind === "one") ids.push(en.e.exception_id);
    else for (const m of en.members) ids.push(m.exception_id);
  }
  return ids;
}

/** Substring match over the real fields a person would search by: category,
 * cause, reference and counterparty (from the first loaded row), and the
 * formatted amount. No new figure is derived, only filtered. */
function matchesSearch(e: Exception, eventsById: Map<string, TransactionEvent>, term: string): boolean {
  if (!term) return true;
  const ev = firstEvent(e, eventsById);
  const haystack = [
    CATEGORY[e.category]?.label,
    e.recommended_action,
    ev?.counterparty,
    ev ? eventReference(ev) : undefined,
    money(e.amount_paise),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(term);
}

/* ---------- screen ---------- */

function DecisionsScreen() {
  const { run, runId, loading: runLoading, error: runError, refresh } = useCurrentRun();
  const ex = useExceptions(runId);
  const cl = useClusters(runId);
  const events = useEvents(runId);
  const { openAssistant } = useShell();

  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const setParam = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(params.toString());
      if (value) next.set(key, value);
      else next.delete(key);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  const openId = params.get("open");
  const categoryParam = params.get("category");
  const category = isCategory(categoryParam) ? categoryParam : null;

  const [status, setStatus] = useState<StatusFilter>("open");
  const [clusterMode, setClusterMode] = useState<ClusterMode>(null);
  const [handledOpen, setHandledOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [activeBand, setActiveBand] = useState<ActionGroup | null>(null);

  const asOf = run?.started_at ?? "";
  const all = useMemo(() => ex.data ?? [], [ex.data]);
  const clusters = useMemo(() => cl.data ?? [], [cl.data]);
  const clusterById = useMemo(() => new Map(clusters.map((c) => [c.cluster_id, c])), [clusters]);
  const byId = useMemo(() => new Map(all.map((e) => [e.exception_id, e])), [all]);
  const eventsById = useMemo(() => new Map((events.data ?? []).map((ev) => [ev.event_id, ev])), [events.data]);

  // Headline figures: everything open that the cascade did not close.
  const needs = useMemo(() => all.filter(needsYou), [all]);
  const unexplained = sumPaise(needs.map((e) => e.amount_paise));
  const dueNow = asOf ? needs.filter((e) => e.deadline && daysBetween(asOf, e.deadline) <= 0).length : 0;
  const deadlines = useMemo(
    () => needs.filter((e) => !!e.deadline).sort((a, b) => (a.deadline ?? "").localeCompare(b.deadline ?? "")),
    [needs],
  );

  // The filtered pool, then what is yours versus what was handled.
  const term = search.trim().toLowerCase();
  const pool = useMemo(
    () =>
      all
        .filter((e) => (category ? e.category === category : true))
        .filter((e) => (status === "open" ? isOpen(e) : status === "resolved" ? !isOpen(e) : true))
        .filter((e) => matchesSearch(e, eventsById, term)),
    [all, category, status, eventsById, term],
  );
  const main = useMemo(() => (status === "resolved" ? pool : pool.filter(needsYou)), [pool, status]);
  const handled = useMemo(() => (status === "resolved" ? [] : pool.filter(handledWithoutYou)), [pool, status]);
  const handledTotal = sumPaise(handled.map((e) => e.amount_paise));

  const layout = useMemo(() => {
    const bands: { group: ActionGroup; entries: Entry[]; subtotal: number; count: number }[] = [];
    for (const g of GROUP_ORDER) {
      const items = main.filter((e) => e.action_group === g);
      if (items.length === 0) continue;
      bands.push({
        group: g,
        entries: buildEntries(items, clusterById, true),
        subtotal: sumPaise(items.map((e) => e.amount_paise)),
        count: items.length,
      });
    }
    const ids = bands.flatMap((b) => entryIds(b.entries));
    ids.push(...handled.map((e) => e.exception_id));
    return { bands, ids };
  }, [main, handled, clusterById]);

  const open = useCallback(
    (id: string) => {
      setClusterMode(null);
      setParam("open", id);
    },
    [setParam],
  );
  const close = useCallback(() => {
    setClusterMode(null);
    setParam("open", null);
  }, [setParam]);
  const applyAll = useCallback(
    (cluster: Cluster, members: Exception[]) => {
      if (members.length === 0) return;
      setClusterMode({ clusterId: cluster.cluster_id, count: members.length });
      setParam("open", members[0].exception_id);
    },
    [setParam],
  );

  const loading = runLoading || (!!runId && (ex.isLoading || cl.isLoading));
  const error = runError ?? (ex.error ? errorMessage(ex.error) : null);

  return (
    <div style={{ minHeight: "100%", padding: "20px 26px 32px" }}>
      <div className="fc-head">
        <h1 className="fc-title" style={{ fontSize: 32 }}>
          Decisions
          {run && (
            <span className="fc-faint" style={{ fontSize: 15, marginLeft: 10 }}>
              · Run #{shortId(run.run_id)}
            </span>
          )}
        </h1>
        <div className="flex gap-2">
          <button
            className="fc-btn fc-btn--ghost inline-flex items-center gap-1.5"
            onClick={() => openAssistant("Which decisions should I take first, and why?")}
          >
            <MessageSquare size={14} />
            Ask about this queue
          </button>
          <button className="fc-btn fc-btn--ghost inline-flex items-center gap-1.5" onClick={refresh} aria-label="Refresh">
            <RefreshCw size={14} />
            Refresh
          </button>
        </div>
      </div>

      {!run ? (
        <div className="fc-faint mt-2" style={{ fontSize: 13 }}>
          Loading run…
        </div>
      ) : (
        <div className="fc-row4 mt-3">
          <StatTile
            icon={<AlertTriangle size={14} />}
            label="Open, unexplained"
            value={unexplained}
            format={(n) => money(Math.round(n))}
            valueColor={unexplained > 0 ? "var(--fc-bad)" : undefined}
            sub="across the whole queue"
          />
          <StatTile
            icon={<Search size={14} />}
            label="Items waiting on you"
            value={needs.length}
            format={(n) => String(Math.round(n))}
            sub={plural(needs.length, "item")}
          />
          <StatTile
            icon={<Clock3 size={14} />}
            label="Due today"
            value={dueNow}
            format={(n) => String(Math.round(n))}
            sub={dueNow > 0 ? "act before it expires" : "nothing on the clock"}
          />
          <StatTile
            icon={<CheckCircle2 size={14} />}
            label="Handled without you"
            value={handledTotal}
            format={(n) => money(Math.round(n))}
            sub={plural(handled.length, "item")}
          />
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-[10px] border p-3 text-[13px]" style={{ borderColor: "color-mix(in srgb, var(--fc-bad) 35%, var(--fc-border))", color: "var(--fc-bad)" }}>
          {error}
        </div>
      )}

      {loading && !error ? (
        <DecisionsSkeleton bare />
      ) : (
        <>
          {/* deadline strip */}
          {deadlines.length > 0 && (
            <div className="mt-5">
              <div className="fc-label mb-2">Money on a clock</div>
              <div className="flex gap-2 overflow-x-auto pb-2">
                {deadlines.map((e) => (
                  <DeadlineChip key={e.exception_id} e={e} asOf={asOf} onOpen={open} />
                ))}
              </div>
            </div>
          )}

          {/* filters */}
          <div className="mt-5 flex flex-wrap items-center gap-2">
            <select
              className="rounded-[8px] border bg-[var(--fc-hover)] px-3 py-2 text-[12.5px] text-[var(--fc-text)] outline-none"
              value={category ?? ""}
              onChange={(ev) => setParam("category", ev.target.value || null)}
              aria-label="Band / category"
            >
              <option value="">All categories</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {CATEGORY[c].label}
                </option>
              ))}
            </select>
            <div className="flex items-center gap-1" role="group" aria-label="Status">
              {(
                [
                  ["open", "Open"],
                  ["resolved", "Resolved"],
                  ["all", "All"],
                ] as [StatusFilter, string][]
              ).map(([s, label]) => (
                <button
                  key={s}
                  className={s === status ? "fc-btn" : "fc-btn fc-btn--ghost"}
                  style={{ padding: "6px 12px", fontSize: 12 }}
                  aria-pressed={status === s}
                  onClick={() => setStatus(s)}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="relative ml-auto">
              <Search size={13} className="fc-faint absolute left-2.5 top-1/2 -translate-y-1/2" />
              <input
                className="w-64 rounded-[8px] border bg-[var(--fc-hover)] py-2 pl-8 pr-3 text-[12.5px] text-[var(--fc-text)] outline-none placeholder:text-[var(--fc-text-3)]"
                placeholder="Reference, counterparty or amount"
                value={search}
                onChange={(ev) => setSearch(ev.target.value)}
                aria-label="Search"
              />
            </div>
          </div>

          {/* band tabs + content: one bordered box, the active tab visually
              attaches to the table beneath it via a matching accent edge */}
          {layout.bands.length > 0 && main.length > 0 && (
            <div className="fc-card fc-card--flat mt-5 overflow-hidden">
              <div className="fc-row4" style={{ padding: "10px 10px 0", gap: 8 }}>
                {layout.bands.map((b) => {
                  const isActive = (activeBand ?? layout.bands[0].group) === b.group;
                  const select = () => setActiveBand(b.group);
                  return (
                    <div
                      key={b.group}
                      role="tab"
                      aria-selected={isActive}
                      tabIndex={0}
                      className="cursor-pointer"
                      style={{
                        padding: "14px 18px",
                        borderRadius: "10px 10px 0 0",
                        background: isActive ? "var(--fc-accent-dim)" : "transparent",
                        border: isActive ? "1px solid var(--fc-accent)" : "1px solid transparent",
                        borderBottom: isActive ? "3px solid var(--fc-accent)" : "3px solid transparent",
                        opacity: isActive ? 1 : 0.6,
                      }}
                      onClick={select}
                      onKeyDown={(k) => {
                        if (k.key === "Enter" || k.key === " ") {
                          k.preventDefault();
                          select();
                        }
                      }}
                    >
                      <span className="truncate" style={{ fontSize: 16, fontWeight: 600, color: "var(--fc-text)" }}>
                        {ACTION_GROUP[b.group].label}
                      </span>
                      <div className="mt-2.5 flex items-baseline justify-between gap-3">
                        <span
                          className="fc-num"
                          style={{ fontSize: 15, fontWeight: 500, letterSpacing: "-0.01em", color: "var(--fc-text-2)" }}
                        >
                          <CountUp value={b.subtotal} format={(n) => money(Math.round(n), { compact: true })} />
                        </span>
                        <span className="fc-faint shrink-0" style={{ fontSize: 11 }}>
                          {plural(b.count, "item")}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* the active tab's content, inside the same bordered box */}
              {(() => {
                const b = layout.bands.find((x) => x.group === (activeBand ?? layout.bands[0].group)) ?? layout.bands[0];
                if (!b) return null;
                return (
                  <div key={b.group} style={{ borderTop: "1px solid var(--fc-divider)", marginTop: 2 }}>
                    <BandHeader group={b.group} subtotal={b.subtotal} count={b.count} />
                    <div className="overflow-x-auto">
                      <DecisionTable>
                        {b.entries.map((en) =>
                          en.kind === "one" ? (
                            <ExceptionRow key={en.e.exception_id} e={en.e} asOf={asOf} onOpen={open} eventsById={eventsById} />
                          ) : (
                            <ClusterRow
                              key={en.cluster.cluster_id}
                              cluster={en.cluster}
                              members={en.members}
                              asOf={asOf}
                              onOpen={open}
                              onApplyAll={applyAll}
                              eventsById={eventsById}
                            />
                          ),
                        )}
                      </DecisionTable>
                    </div>
                  </div>
                );
              })()}
            </div>
          )}

          {/* empty state */}
          {main.length === 0 && (
            <div className="fc-card mt-5 py-10 text-center">
              <div style={{ fontSize: 14 }}>{status === "resolved" ? "Nothing resolved matches" : "Nothing is waiting on you"}</div>
              <div className="fc-faint mt-1.5 text-[12.5px]">
                {status === "resolved"
                  ? "Decisions you or the cascade closed will appear here, with who decided and why."
                  : "New exceptions appear here as a run flags them. Everything else was closed with evidence."}
              </div>
              {category && (
                <button className="fc-btn fc-btn--ghost mt-3" style={{ padding: "6px 14px", fontSize: 12 }} onClick={() => setParam("category", null)}>
                  Clear the category filter
                </button>
              )}
            </div>
          )}

          {/* handled without you */}
          {handled.length > 0 && (
            <div className="fc-card fc-card--flat mt-6 overflow-hidden">
              <button className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left" onClick={() => setHandledOpen((v) => !v)} aria-expanded={handledOpen}>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>Handled without you</div>
                  <div className="fc-faint text-[12px]">Closed by the cascade, a rule or a person. Each one carries its evidence.</div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="fc-num" style={{ fontSize: 14, color: "var(--fc-ok)" }}>
                    {money(handledTotal)}
                  </span>
                  <span className="fc-faint fc-num text-[12px]">{plural(handled.length, "item")}</span>
                  <ChevronDown size={16} className="fc-faint" style={{ transform: handledOpen ? "rotate(180deg)" : undefined, transition: "transform 0.15s" }} />
                </div>
              </button>
              <AnimatePresence initial={false}>
                {handledOpen && (
                  <motion.div
                    key="handled"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.18 }}
                    className="overflow-hidden"
                  >
                    <div className="border-t">
                      {handled.map((e) => (
                        <HandledRow key={e.exception_id} e={e} onOpen={open} />
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </>
      )}

      <DetailPanel
        id={openId}
        ids={layout.ids}
        fallback={openId ? byId.get(openId) : undefined}
        asOf={asOf}
        runId={runId}
        clusterById={clusterById}
        clusterMode={clusterMode}
        onClose={close}
        onNavigate={open}
      />
    </div>
  );
}

/* ---------- header stat tile ---------- */

function StatTile({
  icon,
  label,
  value,
  format,
  valueColor,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  format: (n: number) => string;
  valueColor?: string;
  sub?: string;
}) {
  return (
    <div className="fc-card h-full" style={{ padding: "13px 15px" }}>
      <div className="flex items-center justify-between">
        <div className="fc-label">{label}</div>
        <span className="fc-faint">{icon}</span>
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <span className="fc-num" style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em", color: valueColor ?? "var(--fc-text)" }}>
          <CountUp value={value} format={format} />
        </span>
      </div>
      {sub && (
        <div className="fc-faint mt-1" style={{ fontSize: 12 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

/* ---------- skeleton in the layout of the content ---------- */

function skel(className: string) {
  return <div className={`animate-pulse rounded-[8px] ${className}`} style={{ background: "var(--fc-divider)" }} />;
}

function DecisionsSkeleton({ bare }: { bare?: boolean }) {
  const body = (
    <>
      <div className="fc-row4 mt-3">
        {[0, 1, 2, 3].map((i) => (
          <div key={i}>{skel("h-20 w-full")}</div>
        ))}
      </div>
      <div className="mt-5 flex items-center gap-2">
        {skel("h-9 w-40")}
        {skel("h-9 w-56")}
        {skel("h-9 w-64 ml-auto")}
      </div>
      <div className="fc-row4 mt-5">
        {[0, 1, 2, 3].map((i) => (
          <div key={i}>{skel("h-20 w-full")}</div>
        ))}
      </div>
      <div className="mt-5 flex flex-col gap-2">
        {[0, 1, 2, 3].map((i) => (
          <div key={i}>{skel("h-12 w-full")}</div>
        ))}
      </div>
    </>
  );
  if (bare) return body;
  return (
    <div style={{ minHeight: "100%", padding: "20px 26px 32px" }}>
      <h1 className="fc-title" style={{ fontSize: 32 }}>
        Decisions
      </h1>
      {body}
    </div>
  );
}
