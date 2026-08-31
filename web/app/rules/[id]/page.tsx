"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { use } from "react";
import { CheckCheck, Archive, GitBranchPlus } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise, humanizeSnakeCase, formatPercent } from "@/lib/format";

type Rule = components["schemas"]["Rule"];
type BacktestOut = components["schemas"]["BacktestOut"];
type DeductionInput = components["schemas"]["Deduction-Input"];

interface DeductionDraft {
  type: DeductionInput["type"];
  basis: DeductionInput["basis"];
  rate: string;
  fixed_paise: string;
}

export default function RuleDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [versions, setVersions] = useState<Rule[] | null>(null);
  const [backtest, setBacktest] = useState<BacktestOut | null>(null);
  const [retiring, setRetiring] = useState(false);
  const [draftingVersion, setDraftingVersion] = useState(false);
  const [versionDeductions, setVersionDeductions] = useState<DeductionDraft[]>([]);
  const [submittingVersion, setSubmittingVersion] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const { data } = await apiClient.GET("/api/v1/rules/{rule_id}/versions", {
        params: { path: { rule_id: id } },
      });
      if (cancelled) return;
      setVersions(data ?? null);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const latest = versions?.slice().sort((a, b) => b.version - a.version)[0] ?? null;

  useEffect(() => {
    if (!latest) return;
    let cancelled = false;
    void apiClient
      .POST("/api/v1/rules/{rule_id}/backtest", {
        params: { path: { rule_id: id }, query: { version: latest.version } },
      })
      .then((res) => {
        if (!cancelled) setBacktest(res.data ?? null);
      });
    return () => {
      cancelled = true;
    };
  }, [id, latest]);

  if (!versions || !latest) return <div className="fc-card h-64 animate-pulse" aria-hidden />;

  async function activate() {
    if (!latest) return;
    const reason = window.prompt("Reason to activate (required by the backtest gate):");
    if (!reason?.trim()) return;
    await apiClient.POST("/api/v1/rules/{rule_id}/activate", {
      params: { path: { rule_id: id }, query: { version: latest.version } },
      body: { reason: reason.trim() },
    });
    router.refresh();
  }

  async function retire() {
    if (!latest) return;
    const reason = window.prompt("Reason to retire this rule (it stops applying to new runs):");
    if (!reason?.trim()) return;
    setRetiring(true);
    await apiClient.POST("/api/v1/rules/{rule_id}/retire", {
      params: { path: { rule_id: id }, query: { version: latest.version } },
      body: { reason: reason.trim() },
    });
    setRetiring(false);
    router.refresh();
  }

  function openNewVersion() {
    if (!latest) return;
    setVersionDeductions(
      (latest.deductions ?? []).map((d) => ({
        type: d.type,
        basis: d.basis,
        rate: d.rate != null ? String(d.rate) : "",
        fixed_paise: d.fixed_paise != null ? String(d.fixed_paise) : "",
      })),
    );
    setDraftingVersion(true);
  }

  async function submitNewVersion() {
    if (!latest) return;
    setSubmittingVersion(true);
    const { data } = await apiClient.POST("/api/v1/rules/{rule_id}/versions", {
      params: { path: { rule_id: id } },
      body: {
        scope: latest.scope,
        deductions: versionDeductions.map((d) => ({
          type: d.type,
          basis: d.basis,
          rate: d.rate,
          fixed_paise: d.fixed_paise ? Number(d.fixed_paise) : null,
        })),
        tolerance: latest.tolerance,
        priority: latest.priority,
        effective_confidence: latest.effective_confidence,
      },
    });
    setSubmittingVersion(false);
    if (!data) return;
    setDraftingVersion(false);
    router.refresh();
  }

  const scopeFields = [
    { label: "Counterparty", value: latest.scope.counterparty_matches ?? "Any" },
    { label: "Payment rail", value: latest.scope.rail ?? "Any" },
    {
      label: "Amount",
      value:
        latest.scope.amount_min_paise != null || latest.scope.amount_max_paise != null
          ? `${latest.scope.amount_min_paise != null ? formatPaise(latest.scope.amount_min_paise) : "—"} – ${latest.scope.amount_max_paise != null ? formatPaise(latest.scope.amount_max_paise) : "—"}`
          : "Any",
    },
    { label: "Effective from", value: latest.effective_from },
  ];

  const notAffected = backtest
    ? Math.max(
        backtest.cases_considered -
          backtest.would_explain.count -
          backtest.would_wrongly_close.count -
          backtest.would_partially_explain.count,
        0,
      )
    : 0;

  return (
    <div>
      <button
        type="button"
        onClick={() => router.push("/rules")}
        className="mb-2.5 flex items-center gap-1.5 text-[12.5px] text-text-muted"
      >
        ← Rule Book
      </button>
      <div className="mb-4.5 flex items-center justify-between">
        <div>
          <div className="text-[22px] font-semibold tracking-[-0.025em]">{latest.name}</div>
          <div className="mt-[3px] text-[13px] text-text-muted">
            {latest.scope.counterparty_matches ?? "Any counterparty"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {latest.status === "draft" && (
            <button
              type="button"
              onClick={activate}
              className="flex items-center gap-1.5 rounded-[7px] bg-success-bg px-3 py-1.5 text-xs font-semibold text-success"
            >
              <CheckCheck width={12} height={12} />
              Activate
            </button>
          )}
          {latest.status === "active" && (
            <>
              <button
                type="button"
                onClick={openNewVersion}
                className="flex items-center gap-1.5 rounded-[7px] border border-border px-3 py-1.5 text-xs font-semibold text-text-body"
              >
                <GitBranchPlus width={12} height={12} />
                New version
              </button>
              <button
                type="button"
                disabled={retiring}
                onClick={retire}
                className="flex items-center gap-1.5 rounded-[7px] bg-error-bg px-3 py-1.5 text-xs font-semibold text-error disabled:opacity-50"
              >
                <Archive width={12} height={12} />
                {retiring ? "Retiring…" : "Retire"}
              </button>
            </>
          )}
        </div>
      </div>

      {draftingVersion && (
        <div className="fc-card mb-5 p-5">
          <div className="mb-3 text-sm font-semibold">
            Draft version {latest.version + 1} — edit deduction rates
          </div>
          <div className="flex flex-col gap-2">
            {versionDeductions.map((d, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 text-[13px]">
                <span className="w-32 text-text-body">{humanizeSnakeCase(d.type)}</span>
                <span className="text-text-muted text-xs">on {d.basis}</span>
                <input
                  value={d.rate}
                  onChange={(e) =>
                    setVersionDeductions((prev) =>
                      prev.map((x, idx) => (idx === i ? { ...x, rate: e.target.value } : x)),
                    )
                  }
                  placeholder="rate %"
                  className="fc-numeric w-20 rounded-md border border-border bg-background p-1.5 text-xs"
                />
                <span className="text-xs text-text-muted">%</span>
                <input
                  value={d.fixed_paise}
                  onChange={(e) =>
                    setVersionDeductions((prev) =>
                      prev.map((x, idx) => (idx === i ? { ...x, fixed_paise: e.target.value } : x)),
                    )
                  }
                  placeholder="flat paise (optional)"
                  className="fc-numeric w-32 rounded-md border border-border bg-background p-1.5 text-xs"
                />
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-2.5">
            <button
              type="button"
              disabled={submittingVersion}
              onClick={submitNewVersion}
              className="rounded-lg bg-primary px-4 py-2 text-[12.5px] font-semibold text-white disabled:opacity-50"
            >
              {submittingVersion ? "Creating…" : `Create v${latest.version + 1} draft`}
            </button>
            <button
              type="button"
              onClick={() => setDraftingVersion(false)}
              className="rounded-lg border border-border px-4 py-2 text-[12.5px] font-semibold text-text-body"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-[1.4fr_1fr] gap-5">
        <div className="flex flex-col gap-5">
          <div className="fc-card">
            <div className="px-[22px] pt-4 text-[11px] font-semibold tracking-[0.06em] text-text-muted">WHEN</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-3.5 px-[22px] pt-3.5 pb-5">
              {scopeFields.map((f) => (
                <div key={f.label}>
                  <div className="text-[11.5px] text-text-muted">{f.label}</div>
                  <div className="mt-1 text-[13.5px] font-medium">{f.value}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="fc-card">
            <div className="px-[22px] pt-4 text-[11px] font-semibold tracking-[0.06em] text-text-muted">
              THEN EXPECT
            </div>
            <div className="px-[22px] pt-3.5 pb-5">
              <div className="flex flex-col gap-2.5">
                {(latest.deductions ?? []).map((d, i) => (
                  <div
                    key={i}
                    className="flex items-center justify-between rounded-[10px] border border-border px-3.5 py-3"
                  >
                    <div>
                      <div className="text-[13.5px] font-semibold whitespace-nowrap">{humanizeSnakeCase(d.type)}</div>
                      <div className="mt-0.5 text-[11.5px] whitespace-nowrap text-text-muted">
                        {d.rate != null ? `${d.rate}% of ${d.basis}` : `flat, per ${d.basis}`}
                      </div>
                    </div>
                    <div className="fc-numeric text-base font-semibold">
                      {d.rate != null ? `${d.rate}%` : formatPaise(d.fixed_paise ?? 0)}
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-3.5 flex justify-between border-t border-[color:var(--neutral-bg)] pt-3.5 text-[13px]">
                <span className="text-text-muted">Tolerance</span>
                <span className="fc-numeric text-base font-semibold">
                  {formatPaise(latest.tolerance.absolute_paise)}
                </span>
              </div>
            </div>
          </div>

          <div className="fc-card">
            <div className="px-[22px] pt-4 text-[11px] font-semibold tracking-[0.06em] text-text-muted">
              BACKTEST
            </div>
            <div className="px-[22px] pt-3.5 pb-5">
              {!backtest ? (
                <div className="h-24 animate-pulse rounded-[10px] bg-neutral-bg" aria-hidden />
              ) : (
                <>
                  <div className="mb-3.5 text-[13px] text-text-body">
                    {backtest.cases_considered} historical transactions tested against this rule
                  </div>
                  <div className="mb-4 grid grid-cols-2 gap-3">
                    {[
                      { label: "Would explain", value: backtest.would_explain.count, color: "var(--success)" },
                      { label: "Would partially explain", value: backtest.would_partially_explain.count, color: "var(--amber-text)" },
                      { label: "Would not affect", value: notAffected, color: "var(--text-body)" },
                      { label: "Would wrongly close", value: backtest.would_wrongly_close.count, color: backtest.would_wrongly_close.count > 0 ? "var(--error)" : "var(--success)" },
                    ].map((b) => (
                      <div key={b.label} className="flex justify-between border-b border-[color:var(--neutral-bg)] py-2.5 text-[13px]">
                        <span className="text-text-body">{b.label}</span>
                        <span className="fc-numeric text-base font-semibold" style={{ color: b.color }}>
                          {b.value}
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="flex gap-5 text-[12.5px]">
                      <div>
                        <span className="text-text-muted">Precision</span>{" "}
                        <span className="fc-numeric text-base font-semibold">
                          {backtest.precision_pct != null ? formatPercent(Number(backtest.precision_pct)) : "—"}
                        </span>
                      </div>
                      <div>
                        <span className="text-text-muted">Coverage</span>{" "}
                        <span className="fc-numeric text-base font-semibold">
                          {formatPercent(Number(backtest.coverage_pct))}
                        </span>
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>

        <div className="fc-card h-fit">
          <div className="px-[22px] pt-4 text-sm font-semibold">Version history</div>
          <div className="flex flex-col gap-4 px-[22px] pt-3.5 pb-5">
            {versions
              .slice()
              .sort((a, b) => b.version - a.version)
              .map((v) => (
                <div key={v.version} className="flex gap-3">
                  <div
                    className="mt-[5px] h-2 w-2 flex-none rounded-full"
                    style={{ background: v.status === "active" ? "var(--success)" : "#D8DEEB" }}
                  />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold">v{v.version}</span>
                      {v.status === "active" && (
                        <span className="rounded-[5px] bg-success-bg px-1.5 py-0.5 text-[10px] font-semibold text-success">
                          ACTIVE
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 text-[11.5px] text-text-muted">{v.effective_from}</div>
                    <div className="mt-1 text-[12.5px] text-text-body">
                      {(v.deductions ?? []).map((d) => `${d.rate ?? 0}% ${humanizeSnakeCase(d.type)}`).join(" · ")}
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </div>
      </div>
    </div>
  );
}
