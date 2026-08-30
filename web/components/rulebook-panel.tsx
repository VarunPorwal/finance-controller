"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { formatDecimalPercent, humanizeSnakeCase } from "@/lib/format";
import { RuleAuthoringForm, type RuleSubmitPayload } from "@/components/rule-authoring-form";
import { BacktestDialog } from "@/components/backtest-dialog";

type Rule = components["schemas"]["Rule"];
type SuggestionOut = components["schemas"]["SuggestionOut"];

const STATUS_COLOR: Record<Rule["status"], string> = {
  draft: "text-paper-300",
  active: "text-sig-green",
  retired: "text-paper-500",
};

/**
 * PRD §13.6: rule list, authoring form with live preview, suggestions
 * inbox, and the back-test dialog shown before any activation. Rules are
 * immutable per version (CLAUDE.md hard rule 8) — this panel never edits a
 * rule in place, only creates new versions/rules and shows their history.
 */
export function RulebookPanel() {
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestionOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pendingBacktest, setPendingBacktest] = useState<{
    ruleId: string;
    version: number;
    name: string;
  } | null>(null);
  const [expandedRuleId, setExpandedRuleId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const reload = useCallback(() => setRefreshKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [rulesRes, suggestionsRes] = await Promise.all([
        apiClient.GET("/api/v1/rules", { params: { query: {} } }),
        apiClient.GET("/api/v1/rules/suggestions", {}),
      ]);
      if (cancelled) return;
      if (rulesRes.error) {
        setError("could not load rules");
        return;
      }
      setRules(rulesRes.data ?? []);
      setSuggestions(suggestionsRes.data ?? []);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const latestByRuleId = useMemo(() => {
    if (!rules) return [] as Rule[];
    const map = new Map<string, Rule>();
    for (const rule of rules) {
      const existing = map.get(rule.rule_id);
      if (!existing || rule.version > existing.version) map.set(rule.rule_id, rule);
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [rules]);

  async function createRule(payload: RuleSubmitPayload) {
    setCreating(true);
    const { data, error: createError } = await apiClient.POST("/api/v1/rules", {
      body: payload,
    });
    setCreating(false);
    if (createError || !data) {
      setError("could not create the rule");
      return;
    }
    reload();
    setPendingBacktest({ ruleId: data.rule_id, version: data.version, name: data.name });
  }

  async function acceptSuggestion(signature: string) {
    const { data, error: acceptError } = await apiClient.POST(
      "/api/v1/rules/suggestions/{signature}/accept",
      { params: { path: { signature } } },
    );
    if (acceptError || !data) {
      setError("could not accept the suggestion");
      return;
    }
    reload();
    setPendingBacktest({ ruleId: data.rule_id, version: data.version, name: data.name });
  }

  async function dismissSuggestion(signature: string) {
    await apiClient.POST("/api/v1/rules/suggestions/{signature}/dismiss", {
      params: { path: { signature } },
      body: { reason: "dismissed from the Rulebook tab" },
    });
    setSuggestions((prev) => (prev ? prev.filter((s) => s.signature !== signature) : prev));
  }

  if (error) {
    return <div className="text-sig-amber border-rule bg-ink-800 rounded-lg border p-4 text-sm">{error}</div>;
  }

  return (
    <div className="flex flex-col gap-6">
      <section aria-label="Suggestions inbox">
        <h2 className="font-heading text-paper-300 mb-2 text-xs font-semibold uppercase tracking-wide">
          Suggestions inbox {suggestions ? `· ${suggestions.length}` : ""}
        </h2>
        {suggestions && suggestions.length === 0 && (
          <p className="text-paper-500 text-sm">No learned drafts waiting on approval.</p>
        )}
        <ul className="flex flex-col gap-2">
          {suggestions?.map((s) => (
            <li
              key={s.signature}
              className="border-rule bg-ink-800 flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3"
            >
              <div>
                <p className="text-paper-100 text-sm font-medium">{s.rule.name}</p>
                <p className="text-paper-500 text-xs">
                  {s.occurrences}× {humanizeSnakeCase(s.resolution_category)} · observed rate{" "}
                  {s.observed_rate_percent}%
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => acceptSuggestion(s.signature)}
                  className="bg-rzp-blue hover:bg-rzp-blue/90 rounded-md px-3 py-1.5 text-xs font-medium text-white"
                >
                  Accept
                </button>
                <button
                  type="button"
                  onClick={() => dismissSuggestion(s.signature)}
                  className="border-rule text-paper-300 hover:bg-ink-700 rounded-md border px-3 py-1.5 text-xs"
                >
                  Dismiss
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Rule list">
        <h2 className="font-heading text-paper-300 mb-2 text-xs font-semibold uppercase tracking-wide">
          Rules {rules ? `· ${latestByRuleId.length}` : ""}
        </h2>
        {!rules && (
          <div className="border-rule bg-ink-800 h-24 animate-pulse rounded-lg border" aria-hidden />
        )}
        {rules && latestByRuleId.length === 0 && (
          <p className="text-paper-500 text-sm">No rules yet — create one below.</p>
        )}
        <ul className="flex flex-col gap-1">
          {latestByRuleId.map((rule) => (
            <RuleRow
              key={rule.rule_id}
              rule={rule}
              expanded={expandedRuleId === rule.rule_id}
              onToggle={() =>
                setExpandedRuleId((prev) => (prev === rule.rule_id ? null : rule.rule_id))
              }
            />
          ))}
        </ul>
      </section>

      <section aria-label="New rule">
        <h2 className="font-heading text-paper-300 mb-2 text-xs font-semibold uppercase tracking-wide">
          New rule
        </h2>
        <RuleAuthoringForm onSubmit={createRule} submitting={creating} />
      </section>

      {pendingBacktest && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/60"
            onClick={() => setPendingBacktest(null)}
            aria-hidden
          />
          <BacktestDialog
            ruleId={pendingBacktest.ruleId}
            version={pendingBacktest.version}
            ruleName={pendingBacktest.name}
            onClose={() => setPendingBacktest(null)}
            onActivated={() => {
              setPendingBacktest(null);
              reload();
            }}
          />
        </>
      )}
    </div>
  );
}

function RuleRow({
  rule,
  expanded,
  onToggle,
}: {
  rule: Rule;
  expanded: boolean;
  onToggle: () => void;
}) {
  const [versions, setVersions] = useState<Rule[] | null>(null);

  useEffect(() => {
    if (!expanded || versions) return;
    void (async () => {
      const { data } = await apiClient.GET("/api/v1/rules/{rule_id}/versions", {
        params: { path: { rule_id: rule.rule_id } },
      });
      setVersions(data ?? null);
    })();
  }, [expanded, versions, rule.rule_id]);

  return (
    <li className="border-rule bg-ink-800 rounded-lg border">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-3 p-3 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rzp-blue"
      >
        <div className="min-w-0">
          <p className="text-paper-100 truncate text-sm font-medium">{rule.name}</p>
          <p className="text-paper-500 fc-numeric text-xs">
            {rule.rule_id} · v{rule.version} · effective {rule.effective_from}
            {rule.effective_to ? ` – ${rule.effective_to}` : " –"}
          </p>
        </div>
        <span className={"shrink-0 text-xs font-semibold " + STATUS_COLOR[rule.status]}>
          {rule.status}
        </span>
      </button>
      {expanded && (
        <div className="border-rule border-t p-3">
          {rule.backtest_result ? (
            <p className="text-paper-300 mb-2 text-xs">
              Last back-test:{" "}
              {typeof rule.backtest_result.net_recommendation === "string"
                ? rule.backtest_result.net_recommendation
                : "recorded"}
            </p>
          ) : (
            <p className="text-paper-500 mb-2 text-xs">No back-test recorded on this version.</p>
          )}
          <p className="text-paper-300 mb-1 text-xs font-medium">Version history</p>
          {!versions && <p className="text-paper-500 text-xs">loading…</p>}
          <ul className="flex flex-col gap-1">
            {versions
              ?.slice()
              .sort((a, b) => a.version - b.version)
              .map((v, i, arr) => (
                <li key={v.version} className="fc-numeric text-paper-300 text-xs">
                  v{v.version} · {v.status} · {formatDecimalPercent(v.effective_confidence)} confidence
                  {i > 0 && <VersionDiff before={arr[i - 1]} after={v} />}
                </li>
              ))}
          </ul>
        </div>
      )}
    </li>
  );
}

function VersionDiff({ before, after }: { before: Rule; after: Rule }) {
  const changed: string[] = [];
  if (JSON.stringify(before.scope) !== JSON.stringify(after.scope)) changed.push("scope");
  if (JSON.stringify(before.deductions) !== JSON.stringify(after.deductions)) changed.push("deductions");
  if (JSON.stringify(before.tolerance) !== JSON.stringify(after.tolerance)) changed.push("tolerance");
  if (before.priority !== after.priority) changed.push("priority");
  if (!changed.length) return null;
  return <span className="text-paper-500"> — changed: {changed.join(", ")}</span>;
}
