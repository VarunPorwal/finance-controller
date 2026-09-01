"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Plus, Sparkle, Upload } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { humanizeSnakeCase } from "@/lib/format";
import { FilterPills } from "@/components/ui/filter-pills";
import { StatusPill } from "@/components/ui/status-pill";
import { RuleAuthoringForm, type RuleSubmitPayload } from "@/components/rule-authoring-form";
import { BacktestDialog } from "@/components/backtest-dialog";
import { queryKeys } from "@/lib/query-keys";
import { BacktestOut, Rule, SuggestionOut, fetchRulesAndSuggestions } from "./loader";


const FILTERS = [
  { value: "all", label: "All" },
  { value: "active", label: "Active" },
  { value: "draft", label: "Draft" },
  { value: "retired", label: "Archived" },
];

export default function RuleBookPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: queryKeys.rules({}),
    queryFn: fetchRulesAndSuggestions,
  });
  const rules = data?.rules ?? null;
  const suggestions: SuggestionOut[] = data?.suggestions ?? [];
  const [status, setStatus] = useState("all");
  const [creating, setCreating] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pendingBacktest, setPendingBacktest] = useState<{ ruleId: string; version: number; name: string } | null>(null);
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
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

  async function deleteInline(rule: Rule) {
    if (!window.confirm(`Delete draft ${rule.rule_id} v${rule.version}?`)) return;
    const key = `${rule.rule_id}:${rule.version}`;
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
        setImportMessage({ tone: "error", text: "Not valid JSON." });
        return;
      }
      if (!Array.isArray(entries)) {
        setImportMessage({ tone: "error", text: "Expected a JSON list of rules." });
        return;
      }
      const { data, error } = await apiClient.POST("/api/v1/rules/import", {
        body: entries as Record<string, unknown>[],
      });
      if (error || !data) {
        const detail =
          error && typeof error === "object" && "detail" in error
            ? String((error as { detail?: unknown }).detail)
            : "Import failed.";
        setImportMessage({ tone: "error", text: detail });
        return;
      }
      const versionAdds = data.results.filter((r) => r.outcome === "created_version").length;
      setImportMessage({
        tone: "success",
        text: `Imported ${data.created_count} draft${data.created_count === 1 ? "" : "s"}${
          versionAdds ? ` (${versionAdds} as a new version of an existing rule)` : ""
        }. Back-test and activate each from Rule Book.`,
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
  const [setDetailOpen, setSetDetailOpen] = useState(false);
  const { data: ruleSets } = useQuery({
    queryKey: ["rules", "sets"],
    queryFn: async () => (await apiClient.GET("/api/v1/rules/sets")).data ?? [],
  });

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
        <div className="flex items-center gap-2.5">
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
          <button
            type="button"
            disabled={importing}
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3.5 py-2 text-[12.5px] font-medium text-text-heading disabled:opacity-50"
          >
            <Upload width={14} height={14} />
            {importing ? "Importing…" : "Upload rules JSON"}
          </button>
          <button
            type="button"
            onClick={() => setCreating((c) => !c)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-[12.5px] font-semibold text-white"
          >
            <Plus width={14} height={14} />
            Create rule
          </button>
        </div>
      </div>

      {importMessage && (
        <div
          className={
            "mb-4 rounded-lg border px-4 py-2.5 text-[12.5px] " +
            (importMessage.tone === "success"
              ? "border-success/30 bg-success-bg text-success"
              : "border-error/30 bg-error-bg text-error")
          }
        >
          {importMessage.text}
        </div>
      )}

      {creating && (
        <div className="fc-card mb-5 p-5">
          <RuleAuthoringForm onSubmit={createRule} submitting={submitting} />
        </div>
      )}

      {/*
        Which rulebook is in play, before anything else on the page. A tenant
        can hold several — the demo corpus's and each uploaded dataset's — and
        a rule from a set this run does not use looks identical to one that is
        live unless the page says so.
      */}
      <RuleSetBar
        sets={ruleSets ?? []}
        selected={setFilter}
        onSelect={setSetFilter}
        expanded={setDetailOpen}
        onToggle={() => setSetDetailOpen((v) => !v)}
      />

      <FilterPills options={FILTERS} active={status} onChange={setStatus} />

      <div className="grid grid-cols-2 gap-5">
        {filtered.map((rule) => {
          const bt = affected[rule.rule_id];
          const key = `${rule.rule_id}:${rule.version}`;
          const busy = actingId === key;
          const inSelectedSet =
            setFilter === null || (rule.scope.rule_set ?? "default") === setFilter;
          return (
            <div
              key={rule.rule_id}
              className={
                "fc-card cursor-pointer" + (inSelectedSet ? "" : " opacity-45 saturate-50")
              }
              onClick={() => router.push(`/rules/${rule.rule_id}`)}
            >
              <div className="px-[22px] pt-5">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-[15px] font-semibold">{rule.name}</div>
                  <span className="shrink-0 rounded-[5px] bg-[color:var(--neutral-bg)] px-1.5 py-0.5 text-[10.5px] text-text-muted">
                    {rule.scope.rule_set ?? "default"}
                  </span>
                </div>
                <div className="mt-[3px] text-xs text-text-muted">
                  {rule.scope.counterparty_matches ?? "Any counterparty"}
                </div>
              </div>
              <div className="px-[22px] pt-3.5 pb-5">
                <div className="mb-3.5 flex flex-col gap-1.5">
                  {(rule.deductions ?? []).slice(0, 3).map((d, i) => (
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
                {rule.status === "draft" && (
                  <div className="mb-2.5 flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => activateInline(rule)}
                      className="rounded-[6px] bg-success-bg px-2.5 py-1 text-[11px] font-semibold text-success disabled:opacity-50"
                    >
                      {busy ? "…" : "Activate"}
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => deleteInline(rule)}
                      className="rounded-[6px] bg-error-bg px-2.5 py-1 text-[11px] font-semibold text-error disabled:opacity-50"
                    >
                      {busy ? "…" : "Delete"}
                    </button>
                  </div>
                )}
                <div className="flex items-center justify-between border-t border-[color:var(--neutral-bg)] pt-3">
                  {/*
                    A back-test figure, not a live count: it asks how many
                    *already-resolved or written-off* exceptions this rule
                    would have explained. On a tenant where nobody has closed
                    anything by hand that set is empty, so every rule reads 0
                    however well it works — which is what it was doing.
                  */}
                  <span className="text-xs text-text-muted" title="Back-tested against exceptions a human has already resolved or written off">
                    {bt ? `${bt.would_explain.count} resolved cases explained` : "…"}
                  </span>
                  <span className="text-[12.5px] font-semibold text-primary">View rule →</span>
                </div>
              </div>
            </div>
          );
        })}

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


/**
 * The rule-set strip at the top of the Rulebook.
 *
 * Uploading a rulebook used to retire every active rule the tenant had, so
 * only one dataset could be configured at a time and each upload permanently
 * destroyed the previous set. Sets fixed that; this is what makes the fix
 * visible, because "which rules are actually in play" is otherwise
 * indistinguishable from "every rule ever uploaded".
 */
function RuleSetBar({
  sets,
  selected,
  onSelect,
  expanded,
  onToggle,
}: {
  sets: components["schemas"]["RuleSetOut"][];
  selected: string | null;
  onSelect: (name: string | null) => void;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (sets.length === 0) return null;
  const active = sets.find((s) => s.name === selected) ?? null;
  return (
    <div className="fc-card mb-4 px-[22px] py-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onToggle}
          className="text-text-heading text-[12.5px] font-semibold"
        >
          Rule set{active ? `: ${active.name}` : ": all"} {expanded ? "▾" : "▸"}
        </button>
        <div className="ml-auto flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => onSelect(null)}
            className={
              "rounded-[6px] px-2.5 py-1 text-[11.5px] font-medium " +
              (selected === null
                ? "bg-primary text-white"
                : "border-border text-text-body border")
            }
          >
            All
          </button>
          {sets.map((s) => (
            <button
              key={s.name}
              type="button"
              onClick={() => onSelect(s.name)}
              className={
                "rounded-[6px] px-2.5 py-1 text-[11.5px] font-medium " +
                (selected === s.name
                  ? "bg-primary text-white"
                  : "border-border text-text-body border")
              }
            >
              {s.name}
            </button>
          ))}
        </div>
      </div>
      {expanded && (
        <ul className="border-border mt-3 flex flex-col gap-1.5 border-t pt-3">
          {sets.map((s) => (
            <li key={s.name} className="flex items-baseline justify-between text-[12.5px]">
              <span className="text-text-body">{s.name}</span>
              <span className="text-text-muted text-[11.5px]">
                {s.active_rule_count} active of {s.rule_count}
                {s.updated_at
                  ? ` · updated ${new Date(s.updated_at).toLocaleDateString("en-IN")}`
                  : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
