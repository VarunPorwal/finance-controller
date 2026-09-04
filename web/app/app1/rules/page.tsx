"use client";

// Rule Book. "Why did Finco calculate this amount this way?" Every deduction
// the system applies is a named, versioned rule; this screen shows what each
// one does, what it did in this run, and who put it there. Reskinned to the
// Finco design system — see `finco-tokens.css` and `_components/fc-ui.tsx`.

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, Plus, Search } from "lucide-react";
import {
  useCurrentRun,
  useExceptions,
  useRules,
  useRuleSets,
  useSuggestions,
  errorMessage,
  type Rule,
} from "../_lib/api";
import { money, plural } from "../_lib/format";
import { FcCard, FcErrorNote, FcHead, FcPage, FcSkeleton, WhyLabel, WhyWrap } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";
import { SuggestionsInbox } from "./suggestions";
import { RuleCard } from "./cards";
import { RuleDetail } from "./detail";
import { AuthorRule } from "./author";
import { GENERAL, groupRules, latestPerRule, matchesSearch, ruleUsage } from "./shared";

/** One figure in the compact header strip: label above, value below, a
 * 1px divider rule between items instead of separate cards. */
function StripItem({
  label,
  first,
  title,
  children,
}: {
  label: string;
  first?: boolean;
  title?: string;
  children: ReactNode;
}) {
  return (
    <div
      className="flex flex-col justify-center"
      title={title}
      style={{ padding: `0 20px 0 ${first ? 0 : 20}px`, borderLeft: first ? undefined : "1px solid var(--fc-divider)" }}
    >
      <div style={{ fontSize: 11, color: "var(--fc-text-3)" }}>{label}</div>
      <div className="fc-num" style={{ fontSize: 18, fontWeight: 500, marginTop: 2 }}>
        {children}
      </div>
    </div>
  );
}

type Status = Rule["status"];
const STATUSES: { value: Status; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "draft", label: "Draft" },
  { value: "retired", label: "Retired" },
];

export default function RulesPage() {
  const { run, runId } = useCurrentRun();
  const rules = useRules();
  const sets = useRuleSets();
  const suggestions = useSuggestions();
  const exceptions = useExceptions(runId);

  const [ruleSet, setRuleSet] = useState<string>("all");
  const [ruleSetTouched, setRuleSetTouched] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const GROUP_PREVIEW_COUNT = 3;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [created, setCreated] = useState<Rule | null>(null);
  const [promptBacktest, setPromptBacktest] = useState(false);
  const [authoring, setAuthoring] = useState(false);
  const groupsRef = useRef<HTMLDivElement>(null);

  const latest = useMemo(() => latestPerRule(rules.data), [rules.data]);
  const usage = useMemo(() => ruleUsage(exceptions.data), [exceptions.data]);

  // The rule set this run actually applied: the scope.rule_set of every rule
  // that fired at least once. A run only ever applies one rulebook, so if
  // more than one name shows up here the run can't be attributed and the
  // filter falls back to "all" rather than guessing.
  const currentRunRuleSet = useMemo(() => {
    const names = new Set<string>();
    for (const r of latest) {
      const u = usage.get(r.rule_id);
      if (u && u.fired > 0 && r.scope.rule_set) names.add(r.scope.rule_set);
    }
    return names.size === 1 ? [...names][0] : null;
  }, [latest, usage]);

  // Default the filter to the run's own rule set, once it's known, unless
  // the person has already picked something themselves.
  useEffect(() => {
    if (!ruleSetTouched && currentRunRuleSet && ruleSet === "all") setRuleSet(currentRunRuleSet);
  }, [currentRunRuleSet, ruleSetTouched, ruleSet]);

  const explicitAllSets = ruleSet === "all" && ruleSetTouched;

  const inSet = useMemo(
    () => (ruleSet === "all" ? latest : latest.filter((r) => r.scope.rule_set === ruleSet)),
    [latest, ruleSet],
  );

  const counts = useMemo(() => {
    const c: Record<Status, number> = { active: 0, draft: 0, retired: 0 };
    for (const r of inSet) c[r.status] += 1;
    return c;
  }, [inSet]);

  const headerStats = useMemo(() => {
    let fired = 0;
    let explained = 0;
    for (const r of inSet) {
      const u = usage.get(r.rule_id);
      if (u && u.fired > 0) {
        fired += 1;
        explained += u.explained;
      }
    }
    return { count: inSet.length, fired, explained };
  }, [inSet, usage]);

  const visible = useMemo(
    () => inSet.filter((r) => (status ? r.status === status : true) && matchesSearch(r, search)),
    [inSet, status, search],
  );
  const groups = useMemo(() => groupRules(visible), [visible]);

  const selected = selectedId
    ? (latest.find((r) => r.rule_id === selectedId) ?? (created?.rule_id === selectedId ? created : null))
    : null;

  const ruleSetNames = (sets.data ?? []).map((s) => s.name);

  const toggleGroup = (g: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g);
      else next.add(g);
      return next;
    });

  return (
    <FcPage>
      <FcHead
        title="Rule Book"
        actions={
          <button className="fc-btn" onClick={() => setAuthoring(true)}>
            <Plus size={14} />
            Create rule
          </button>
        }
      />

      {rules.data && (
        <div className="mb-6 flex items-stretch" style={{ height: 52 }}>
          <StripItem
            label="Rules in view"
            first
            title={ruleSet === "all" ? "across all rule sets" : `in ${ruleSet}`}
          >
            <CountUp value={headerStats.count} />
            {explicitAllSets && (
              <span className="fc-faint" style={{ fontSize: 12, fontWeight: 400 }}>
                {" "}
                (all sets)
              </span>
            )}
          </StripItem>
          <StripItem label="Fired this run" title={`${plural(headerStats.count - headerStats.fired, "rule")} never fired`}>
            <CountUp value={headerStats.fired} />
          </StripItem>
          <StripItem label="Explained" title="deducted by rules that fired">
            <WhyWrap>
              <span className="fc-why-figure" style={{ color: "var(--fc-ok)" }}>
                <CountUp value={headerStats.explained} format={(n) => money(Math.round(n))} />
              </span>
              <WhyLabel onClick={() => groupsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" })} />
            </WhyWrap>
          </StripItem>
        </div>
      )}

      {suggestions.data && suggestions.data.length > 0 && <SuggestionsInbox suggestions={suggestions.data} />}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="fc-muted" style={{ fontSize: 12.5 }}>
            Rule set
          </span>
          <div className="relative inline-flex items-center">
            <select
              value={ruleSet}
              onChange={(e) => {
                setRuleSetTouched(true);
                setRuleSet(e.target.value);
              }}
              className="fc-num"
              style={{
                appearance: "none",
                background: "var(--fc-hover)",
                border: "1px solid var(--fc-border)",
                color: "var(--fc-text)",
                borderRadius: 8,
                padding: "6px 26px 6px 10px",
                fontSize: 12.5,
              }}
            >
              <option value="all">All rule sets</option>
              {ruleSetNames.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <ChevronDown size={13} className="fc-faint pointer-events-none absolute right-2" />
          </div>
        </div>
        <div className="relative">
          <Search size={13} className="fc-faint pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search rule name, id, counterparty"
            className="fc-num"
            style={{
              background: "var(--fc-hover)",
              border: "1px solid var(--fc-border)",
              color: "var(--fc-text)",
              borderRadius: 8,
              padding: "6px 10px 6px 28px",
              fontSize: 12.5,
              width: 260,
            }}
          />
        </div>
      </div>

      <div className="mb-6 flex items-center gap-1.5" role="group" aria-label="Filter by status">
        {STATUSES.map((s) => (
          <button
            key={s.value}
            type="button"
            onClick={() => setStatus(status === s.value ? null : s.value)}
            className="fc-chip fc-num"
            style={{
              cursor: "pointer",
              border: "1px solid transparent",
              ...(status === s.value ? { borderColor: "var(--fc-accent)", color: "var(--fc-text)" } : undefined),
              opacity: status && status !== s.value ? 0.5 : 1,
            }}
            aria-pressed={status === s.value}
          >
            {s.label} {counts[s.value]}
          </button>
        ))}
      </div>

      {rules.isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <FcSkeleton key={i} className="h-[210px]" />
          ))}
        </div>
      )}
      {rules.error && <FcErrorNote message={errorMessage(rules.error)} />}

      {rules.data && groups.length === 0 && (
        <FcCard>
          <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
            <div className="fc-strong" style={{ fontSize: 14 }}>
              {status ? `No ${status} rules here` : "No rules match"}
            </div>
            <div className="fc-faint max-w-sm" style={{ fontSize: 12.5 }}>
              A rule explains a recurring deduction: MDR, GST on the fee, TDS. Draft one, back-test it, and activate it
              when the numbers hold.
            </div>
            <button className="fc-btn mt-2" onClick={() => setAuthoring(true)}>
              <Plus size={14} />
              Create rule
            </button>
          </div>
        </FcCard>
      )}

      <div ref={groupsRef}>
      {groups.map(([group, list]) => {
        const isCollapsed = collapsed.has(group);
        let explained = 0;
        let anyFired = false;
        for (const r of list) {
          const u = usage.get(r.rule_id);
          if (u && u.fired > 0) {
            explained += u.explained;
            anyFired = true;
          }
        }
        return (
          <section key={group} className="mb-6">
            <button
              type="button"
              onClick={() => toggleGroup(group)}
              className="mb-3 flex w-full items-center justify-between gap-4"
            >
              <span className="flex items-center gap-1.5">
                {isCollapsed ? (
                  <ChevronRight size={14} className="fc-faint" />
                ) : (
                  <ChevronDown size={14} className="fc-faint" />
                )}
                <span className="fc-strong" style={{ fontSize: 13.5, letterSpacing: "0.02em", textTransform: "uppercase" }}>
                  {group === GENERAL ? "General" : group}
                </span>
              </span>
              <span className="fc-faint fc-num" style={{ fontSize: 12 }}>
                {plural(list.length, "rule")} ·{" "}
                {anyFired ? <span style={{ color: "var(--fc-ok)" }}>{money(explained)} explained</span> : "never fired"}
              </span>
            </button>
            {!isCollapsed && (() => {
              const isExpanded = expandedGroups.has(group);
              const shown = isExpanded ? list : list.slice(0, GROUP_PREVIEW_COUNT);
              const hidden = list.length - shown.length;
              return (
                <>
                  <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4">
                    {shown.map((r) => (
                      <RuleCard
                        key={`${r.rule_id}:${r.version}`}
                        rule={r}
                        usage={usage.get(r.rule_id)}
                        onOpen={() => {
                          setPromptBacktest(false);
                          setSelectedId(r.rule_id);
                        }}
                      />
                    ))}
                  </div>
                  {hidden > 0 && (
                    <button
                      type="button"
                      className="fc-btn fc-btn--ghost mt-3"
                      style={{ padding: "6px 14px", fontSize: 12 }}
                      onClick={() =>
                        setExpandedGroups((prev) => {
                          const next = new Set(prev);
                          next.add(group);
                          return next;
                        })
                      }
                    >
                      View {plural(hidden, "more rule")}
                    </button>
                  )}
                </>
              );
            })()}
          </section>
        );
      })}
      </div>

      <RuleDetail
        rule={selected}
        open={!!selected}
        onClose={() => setSelectedId(null)}
        usage={selected ? usage.get(selected.rule_id) : undefined}
        promptBacktest={promptBacktest}
      />

      <AuthorRule
        open={authoring}
        onClose={() => setAuthoring(false)}
        ruleSets={ruleSetNames}
        defaultDateFrom={run?.period_start ?? null}
        onCreated={(rule) => {
          setAuthoring(false);
          setCreated(rule);
          setPromptBacktest(true);
          setSelectedId(rule.rule_id);
        }}
      />
    </FcPage>
  );
}
