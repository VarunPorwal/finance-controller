"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Sparkle } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { humanizeSnakeCase } from "@/lib/format";
import { FilterPills } from "@/components/ui/filter-pills";
import { StatusPill } from "@/components/ui/status-pill";
import { RuleAuthoringForm, type RuleSubmitPayload } from "@/components/rule-authoring-form";
import { BacktestDialog } from "@/components/backtest-dialog";

type Rule = components["schemas"]["Rule"];
type SuggestionOut = components["schemas"]["SuggestionOut"];
type BacktestOut = components["schemas"]["BacktestOut"];

const FILTERS = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "draft", label: "Draft" },
  { value: "retired", label: "Archived" },
];

export default function RuleBookPage() {
  const router = useRouter();
  const [rules, setRules] = useState<Rule[] | null>(null);
  const [suggestions, setSuggestions] = useState<SuggestionOut[]>([]);
  const [affected, setAffected] = useState<Record<string, BacktestOut>>({});
  const [status, setStatus] = useState("all");
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pendingBacktest, setPendingBacktest] = useState<{ ruleId: string; version: number; name: string } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [rulesRes, suggestionsRes] = await Promise.all([
        apiClient.GET("/api/v1/rules", { params: { query: {} } }),
        apiClient.GET("/api/v1/rules/suggestions", {}),
      ]);
      if (cancelled) return;
      setRules(rulesRes.data ?? []);
      setSuggestions(suggestionsRes.data ?? []);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const latest = useMemo(() => {
    if (!rules) return [] as Rule[];
    const map = new Map<string, Rule>();
    for (const r of rules) {
      const existing = map.get(r.rule_id);
      if (!existing || r.version > existing.version) map.set(r.rule_id, r);
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [rules]);

  useEffect(() => {
    if (!latest.length) return;
    let cancelled = false;
    void Promise.all(
      latest.map((r) =>
        apiClient
          .POST("/api/v1/rules/{rule_id}/backtest", { params: { path: { rule_id: r.rule_id }, query: { version: r.version } } })
          .then((res) => [r.rule_id, res.data] as const),
      ),
    ).then((results) => {
      if (cancelled) return;
      const map: Record<string, BacktestOut> = {};
      for (const [id, data] of results) if (data) map[id] = data;
      setAffected(map);
    });
    return () => {
      cancelled = true;
    };
  }, [latest]);

  async function createRule(payload: RuleSubmitPayload) {
    setSubmitting(true);
    const { data } = await apiClient.POST("/api/v1/rules", { body: payload });
    setSubmitting(false);
    if (!data) return;
    setCreating(false);
    reload();
    setPendingBacktest({ ruleId: data.rule_id, version: data.version, name: data.name });
  }

  const filtered = latest.filter((r) => status === "all" || r.status === status);

  return (
    <div>
      <div className="mb-4.5 flex items-center justify-between">
        <div>
          <div className="text-2xl font-semibold tracking-[-0.025em]">Rule Book</div>
          <div className="mt-[3px] text-[13px] text-text-muted">
            Your business&apos;s deduction and settlement policy, encoded
          </div>
        </div>
        <button
          type="button"
          onClick={() => setCreating((c) => !c)}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[12.5px] font-semibold text-white"
        >
          <Plus width={14} height={14} />
          Create rule
        </button>
      </div>

      {creating && (
        <div className="fc-card mb-5 p-5">
          <RuleAuthoringForm onSubmit={createRule} submitting={submitting} />
        </div>
      )}

      <FilterPills options={FILTERS} active={status} onChange={setStatus} />

      <div className="grid grid-cols-2 gap-5">
        {suggestions.map((s) => (
          <div
            key={s.signature}
            className="cursor-pointer rounded-[var(--radius-card)] border border-model-border p-5"
            style={{ background: "var(--model-bg)" }}
            onClick={() => router.push(`/rules/${s.rule.rule_id}`)}
          >
            <div className="mb-2.5 flex items-center gap-1.5 text-[11px] font-semibold text-model-text">
              <Sparkle width={12} height={12} />
              LEARNED SUGGESTION
            </div>
            <div className="text-[15px] font-semibold">{s.rule.name}</div>
            <div className="mt-1 text-xs text-text-muted">
              {humanizeSnakeCase(s.resolution_category)}
            </div>
            <div className="mt-3.5 flex items-center gap-2.5">
              <StatusPill tone="model">Draft only</StatusPill>
              <span className="text-[11.5px] text-text-muted">Seen {s.occurrences} times</span>
            </div>
            <div className="mt-2.5 text-[11.5px] text-model-text">
              Suggested rules never activate on their own
            </div>
            <div className="mt-2.5 flex items-center justify-between border-t border-model-border pt-3">
              <span className="text-xs text-text-muted">{s.exception_ids.length} historical exceptions</span>
              <span className="text-[12.5px] font-semibold text-primary">View rule →</span>
            </div>
          </div>
        ))}

        {filtered.map((rule) => {
          const bt = affected[rule.rule_id];
          return (
            <div
              key={rule.rule_id}
              className="fc-card cursor-pointer"
              onClick={() => router.push(`/rules/${rule.rule_id}`)}
            >
              <div className="px-[22px] pt-5">
                <div className="text-[15px] font-semibold">{rule.name}</div>
                <div className="mt-[3px] text-xs text-text-muted">
                  {rule.scope.counterparty_matches ?? "Any counterparty"}
                </div>
              </div>
              <div className="px-[22px] pt-3.5 pb-5">
                <div className="mb-3.5 flex flex-col gap-1.5">
                  {rule.deductions.slice(0, 3).map((d, i) => (
                    <div key={i} className="flex justify-between text-[13px]">
                      <span className="text-text-body">{humanizeSnakeCase(d.type)}</span>
                      <span className="fc-numeric text-base font-semibold">
                        {d.rate != null ? `${d.rate}%` : `₹${(d.fixed_paise ?? 0) / 100}`}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="mb-2.5 flex items-center gap-2.5">
                  <span className="rounded-[6px] bg-neutral-bg px-2 py-[3px] text-[11px] font-semibold text-neutral-text">
                    v{rule.version}
                  </span>
                  <StatusPill tone={rule.status === "active" ? "success" : "neutral"}>
                    {rule.status.toUpperCase()}
                  </StatusPill>
                  <span className="text-[11.5px] whitespace-nowrap text-text-muted">
                    Effective {rule.effective_from}
                  </span>
                </div>
                <div className="flex items-center justify-between border-t border-[color:var(--neutral-bg)] pt-3">
                  <span className="text-xs text-text-muted">
                    {bt ? `${bt.would_explain.count} transactions affected` : "…"}
                  </span>
                  <span className="text-[12.5px] font-semibold text-primary">View rule →</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {pendingBacktest && (
        <>
          <div className="fixed inset-0 z-40 bg-black/60" onClick={() => setPendingBacktest(null)} aria-hidden />
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
