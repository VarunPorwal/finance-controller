"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ArrowRight, Plus, Sparkles, Upload } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise, humanizeSnakeCase } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { PageHeader } from "@/components/page-header";
import { Segmented } from "@/components/ui/segmented";
import { Pill } from "@/components/ui/pill";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { RuleAuthoringForm, type RuleSubmitPayload } from "@/components/rule-authoring-form";
import { BacktestDialog } from "@/components/backtest-dialog";
import { cn } from "@/lib/utils";
import { fetchRulesAndSuggestions, type BacktestOut, type Rule, type SuggestionOut } from "./loader";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "draft", label: "Draft" },
  { value: "retired", label: "Retired" },
];

const STATUS_TONE: Record<Rule["status"], "ok" | "neutral" | "warn"> = { active: "ok", draft: "neutral", retired: "warn" };

export default function RuleBookPage() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: queryKeys.rules({}), queryFn: fetchRulesAndSuggestions });
  const rules = data?.rules ?? null;
  const suggestions: SuggestionOut[] = data?.suggestions ?? [];
  const [status, setStatus] = useState("all");
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pendingBacktest, setPendingBacktest] = useState<{ ruleId: string; version: number; name: string } | null>(null);
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [actingId, setActingId] = useState<string | null>(null);

  function reload() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.rules({}) });
  }

  async function activateInline(rule: Rule) {
    const key = `${rule.rule_id}:${rule.version}`;
    setActingId(key);
    await apiClient.POST("/api/v1/rules/{rule_id}/activate", {
      params: { path: { rule_id: rule.rule_id }, query: { version: rule.version } },
      body: { reason: "Activated from Rule Book" },
    });
    setActingId(null);
    reload();
  }

  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  async function deleteInline(rule: Rule) {
    const key = `${rule.rule_id}:${rule.version}`;
    setConfirmDeleteId(null);
    setActingId(key);
    await apiClient.DELETE("/api/v1/rules/{rule_id}/versions/{version}", {
      params: { path: { rule_id: rule.rule_id, version: rule.version } },
    });
    setActingId(null);
    reload();
  }

  async function importRulesFile(file: File) {
    setImporting(true);
    setImportMessage(null);
    try {
      const text = await file.text();
      let entries: unknown;
      try {
        entries = JSON.parse(text);
      } catch {
        setImportMessage({ tone: "bad", text: "Not valid JSON." });
        return;
      }
      if (!Array.isArray(entries)) {
        setImportMessage({ tone: "bad", text: "Expected a JSON list of rules." });
        return;
      }
      const { data: out, error } = await apiClient.POST("/api/v1/rules/import", { body: entries as Record<string, unknown>[] });
      if (error || !out) {
        const detail = error && typeof error === "object" && "detail" in error ? String((error as { detail?: unknown }).detail) : "Import failed.";
        setImportMessage({ tone: "bad", text: detail });
        return;
      }
      const versionAdds = out.results.filter((r) => r.outcome === "created_version").length;
      setImportMessage({
        tone: "ok",
        text: `Imported ${out.created_count} draft${out.created_count === 1 ? "" : "s"}${versionAdds ? ` (${versionAdds} as a new version of an existing rule)` : ""}. Back-test and activate each from here.`,
      });
      reload();
    } finally {
      setImporting(false);
    }
  }

  const latest = useMemo(() => {
    if (!rules) return [] as Rule[];
    const map = new Map<string, Rule>();
    for (const r of rules) {
      const existing = map.get(r.rule_id);
      if (!existing || r.version > existing.version) map.set(r.rule_id, r);
    }
    return Array.from(map.values()).sort((a, b) => a.name.localeCompare(b.name));
  }, [rules]);

  const [setFilter, setSetFilter] = useState<string | null>(null);
  const { data: ruleSets } = useQuery({
    queryKey: ["rules", "sets"],
    queryFn: async () => (await apiClient.GET("/api/v1/rules/sets")).data ?? [],
  });

  // A back-test figure, not a live count: how many already-resolved or
  // written-off exceptions this rule would have explained.
  const { data: affected = {} } = useQuery({
    queryKey: ["rules", "affected", latest.map((r) => `${r.rule_id}:${r.version}`)],
    queryFn: async () => {
      const results = await Promise.all(
        latest.map((r) =>
          apiClient
            .POST("/api/v1/rules/{rule_id}/backtest", { params: { path: { rule_id: r.rule_id }, query: { version: r.version } } })
            .then((res) => [r.rule_id, res.data] as const),
        ),
      );
      const map: Record<string, BacktestOut> = {};
      for (const [id, d] of results) if (d) map[id] = d;
      return map;
    },
    enabled: latest.length > 0,
  });

  async function createRule(payload: RuleSubmitPayload) {
    setSubmitting(true);
    const { data: created } = await apiClient.POST("/api/v1/rules", { body: payload });
    setSubmitting(false);
    if (!created) return;
    setCreating(false);
    reload();
    setPendingBacktest({ ruleId: created.rule_id, version: created.version, name: created.name });
  }

  const filtered = latest.filter((r) => status === "all" || r.status === status);
  const counts = {
    all: latest.length,
    active: latest.filter((r) => r.status === "active").length,
    draft: latest.filter((r) => r.status === "draft").length,
    retired: latest.filter((r) => r.status === "retired").length,
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Rule Book"
        sub="Deduction and settlement policy, encoded. A rule shrinks an exception; it never passes or fails one. Versions are immutable."
        actions={
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json,.json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void importRulesFile(file);
              }}
            />
            <Button icon={<Upload width={13} height={13} />} disabled={importing} onClick={() => fileInputRef.current?.click()}>
              {importing ? "Importing…" : "Import JSON"}
            </Button>
            <Button variant="primary" icon={<Plus width={13} height={13} />} onClick={() => setCreating((c) => !c)}>
              {creating ? "Close editor" : "Create rule"}
            </Button>
          </>
        }
      />

      {importMessage && (
        <div className={cn("rounded-[8px] border px-4 py-2.5 text-[12.5px]", importMessage.tone === "ok" ? "border-[rgba(61,220,151,0.3)] bg-ok-soft text-ok" : "border-[rgba(255,107,107,0.3)] bg-bad-soft text-bad")}>
          {importMessage.text}
        </div>
      )}

      {creating && <RuleAuthoringForm onSubmit={createRule} submitting={submitting} />}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Segmented
          active={status}
          onChange={setStatus}
          options={FILTERS.map((f) => ({ ...f, count: counts[f.value as keyof typeof counts] }))}
        />
        {(ruleSets ?? []).length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="label mr-1">Rule set</span>
            <button
              type="button"
              onClick={() => setSetFilter(null)}
              className={cn("rounded-[6px] border px-2.5 py-1 text-[11.5px]", setFilter === null ? "border-accent-strong bg-accent-soft text-accent" : "border-line-strong text-ink-2")}
            >
              All
            </button>
            {(ruleSets ?? []).map((s) => (
              <button
                key={s.name}
                type="button"
                onClick={() => setSetFilter(s.name)}
                title={`${s.active_rule_count} active of ${s.rule_count}`}
                className={cn("num rounded-[6px] border px-2.5 py-1 text-[11.5px]", setFilter === s.name ? "border-accent-strong bg-accent-soft text-accent" : "border-line-strong text-ink-2")}
              >
                {s.name} <span className="text-ink-3">{s.active_rule_count}/{s.rule_count}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {!rules && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-[220px]" />
          ))}
        </div>
      )}

      {rules && filtered.length === 0 && suggestions.length === 0 && (
        <EmptyState
          title="No rules under this filter"
          note="Create one, or import a rulebook JSON. Every rule is born a draft and only a back-test can activate it."
          action={
            <Button variant="primary" icon={<Plus width={13} height={13} />} onClick={() => setCreating(true)}>
              Create rule
            </Button>
          }
        />
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((rule) => {
          const bt = affected[rule.rule_id];
          const key = `${rule.rule_id}:${rule.version}`;
          const busy = actingId === key;
          const inSelectedSet = setFilter === null || (rule.scope.rule_set ?? "default") === setFilter;
          return (
            <div
              key={rule.rule_id}
              className={cn("panel group relative flex flex-col transition-colors hover:border-line-strong", !inSelectedSet && "opacity-40")}
            >
              <div className="px-[18px] pt-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Link
                      href={`/rules/${rule.rule_id}`}
                      className="block truncate text-[14px] font-semibold text-ink after:absolute after:inset-0 after:content-[''] focus-visible:outline-none"
                    >
                      {rule.name}
                    </Link>
                    <div className="mt-0.5 truncate text-[11.5px] text-ink-3">
                      {rule.scope.counterparty_matches?.join(", ") ?? "Any counterparty"}
                      {rule.scope.rail ? ` · ${rule.scope.rail.toUpperCase()}` : ""}
                    </div>
                  </div>
                  <Pill tone={STATUS_TONE[rule.status]} dot>
                    {rule.status}
                  </Pill>
                </div>
              </div>
              <div className="flex-1 px-[18px] pt-3.5">
                <ul className="flex flex-col">
                  {(rule.deductions ?? []).slice(0, 4).map((d, i) => (
                    <li key={i} className="flex items-baseline justify-between border-b border-line py-1.5 text-[12.5px] last:border-0">
                      <span className="text-ink-2">
                        {humanizeSnakeCase(d.type)} <span className="text-ink-3">on {d.basis}</span>
                      </span>
                      <span className="num text-[15px] font-semibold text-ink">{d.rate != null ? `${d.rate}%` : formatPaise(d.fixed_paise ?? 0)}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="mt-3 flex items-center gap-2 border-t border-line px-[18px] py-3 text-[11px] text-ink-3">
                <span className="num rounded-[5px] border border-line-strong px-1.5 py-0.5 text-ink-2">v{rule.version}</span>
                <span className="num">{rule.scope.rule_set ?? "default"}</span>
                <span className="num">· from {rule.effective_from}</span>
                <span className="ml-auto" title="Back-tested against exceptions a human already resolved or wrote off">
                  {bt ? `${bt.would_explain.count} cases explained` : "…"}
                </span>
              </div>
              {rule.status === "draft" && (
                <div className="relative z-10 flex items-center gap-2 border-t border-line px-[18px] py-2.5">
                  {confirmDeleteId === key ? (
                    <>
                      <span className="text-[11.5px] text-ink-2">Delete v{rule.version}? This cannot be undone.</span>
                      <Button size="sm" variant="bad" disabled={busy} onClick={() => deleteInline(rule)}>
                        Delete
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmDeleteId(null)}>
                        Keep
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button size="sm" variant="ok" disabled={busy} onClick={() => activateInline(rule)}>
                        {busy ? "Working…" : "Activate"}
                      </Button>
                      <Button size="sm" variant="bad" disabled={busy} onClick={() => setConfirmDeleteId(key)}>
                        Delete draft
                      </Button>
                    </>
                  )}
                  <span className="ml-auto flex items-center gap-1 text-[11.5px] text-ink-2 opacity-0 transition-opacity group-hover:opacity-100">
                    Open <ArrowRight width={12} height={12} />
                  </span>
                </div>
              )}
            </div>
          );
        })}

        {suggestions.map((s) => (
          <div key={s.signature} className="panel-model relative flex flex-col px-[18px] pt-4 pb-4 transition-colors hover:border-model">
            <div className="flex items-center gap-1.5 text-[10.5px] font-semibold tracking-[0.08em] text-model uppercase">
              <Sparkles width={11} height={11} />
              Learned suggestion
            </div>
            <Link
              href={`/rules/${s.rule.rule_id}`}
              className="mt-2 block text-[14px] font-semibold text-ink after:absolute after:inset-0 after:content-[''] focus-visible:outline-none"
            >
              {s.rule.name}
            </Link>
            <div className="mt-0.5 text-[11.5px] text-ink-3">{humanizeSnakeCase(s.resolution_category)}</div>
            <div className="mt-3 flex items-center gap-2">
              <Pill tone="model">Draft only</Pill>
              <span className="num text-[11.5px] text-ink-3">seen {s.occurrences}× · rate {s.observed_rate_percent}%</span>
            </div>
            <p className="mt-3 text-[11.5px] text-model">Suggested rules never activate on their own. A back-test and a human do that.</p>
            <div className="mt-auto flex items-center justify-between border-t border-model-line pt-3 text-[11px] text-ink-3">
              <span className="num">{s.exception_ids.length} historical exceptions</span>
              <span className="flex items-center gap-1 text-ink-2">
                Review <ArrowRight width={12} height={12} />
              </span>
            </div>
          </div>
        ))}
      </div>

      {pendingBacktest && (
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
      )}
    </div>
  );
}

export type { components };
