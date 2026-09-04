"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowLeft, CheckCheck, GitBranchPlus, Trash2 } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise, formatPercent, humanizeSnakeCase } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/ui/panel";
import { Pill } from "@/components/ui/pill";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type Rule = components["schemas"]["Rule"];
type DeductionInput = components["schemas"]["Deduction-Input"];

interface DeductionDraft {
  type: DeductionInput["type"];
  basis: DeductionInput["basis"];
  rate: string;
  fixed_paise: string;
}

const STATUS_TONE: Record<Rule["status"], "ok" | "neutral" | "warn"> = { active: "ok", draft: "neutral", retired: "warn" };

export default function RuleDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<"activate" | "retire" | "delete" | null>(null);
  const [reason, setReason] = useState("");
  const [acting, setActing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [draftingVersion, setDraftingVersion] = useState(false);
  const [versionDeductions, setVersionDeductions] = useState<DeductionDraft[]>([]);
  const [submittingVersion, setSubmittingVersion] = useState(false);

  const { data: versions } = useQuery({
    queryKey: queryKeys.ruleVersions(id),
    queryFn: async () => (await apiClient.GET("/api/v1/rules/{rule_id}/versions", { params: { path: { rule_id: id } } })).data ?? null,
  });
  const latest = versions?.slice().sort((a, b) => b.version - a.version)[0] ?? null;

  const { data: backtest } = useQuery({
    queryKey: queryKeys.ruleBacktest(id, latest?.version ?? 0),
    queryFn: async () =>
      (await apiClient.POST("/api/v1/rules/{rule_id}/backtest", { params: { path: { rule_id: id }, query: { version: latest!.version } } })).data ?? null,
    enabled: !!latest,
  });

  function reload() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.ruleVersions(id) });
    void queryClient.invalidateQueries({ queryKey: ["rules"] });
  }

  if (!versions || !latest) {
    return (
      <div className="flex flex-col gap-5">
        <Skeleton className="h-10 w-80" />
        <Skeleton className="h-[420px]" />
      </div>
    );
  }

  async function confirmPending() {
    if (!latest || !pending || !reason.trim()) return;
    setActing(true);
    const path = pending === "activate" ? "/api/v1/rules/{rule_id}/activate" : "/api/v1/rules/{rule_id}/retire";
    await apiClient.POST(path, { params: { path: { rule_id: id }, query: { version: latest.version } }, body: { reason: reason.trim() } });
    setActing(false);
    setPending(null);
    setReason("");
    reload();
    router.refresh();
  }

  async function deleteDraft() {
    if (!latest) return;
    setPending(null);
    setDeleting(true);
    const { response } = await apiClient.DELETE("/api/v1/rules/{rule_id}/versions/{version}", {
      params: { path: { rule_id: id, version: latest.version } },
    });
    setDeleting(false);
    if (!response.ok) return;
    reload();
    router.push("/rules");
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
        deductions: versionDeductions.map((d) => ({ type: d.type, basis: d.basis, rate: d.rate, fixed_paise: d.fixed_paise ? Number(d.fixed_paise) : null })),
        tolerance: latest.tolerance,
        priority: latest.priority,
        effective_confidence: latest.effective_confidence,
      },
    });
    setSubmittingVersion(false);
    if (!data) return;
    setDraftingVersion(false);
    reload();
    router.refresh();
  }

  const scopeFields = [
    { label: "Counterparty", value: latest.scope.counterparty_matches?.join(", ") ?? "Any" },
    { label: "Payment rail", value: latest.scope.rail ?? "Any" },
    { label: "Source", value: latest.scope.source ?? "Any" },
    { label: "Method", value: latest.scope.method ?? "Any" },
    {
      label: "Amount",
      value:
        latest.scope.amount_min_paise != null || latest.scope.amount_max_paise != null
          ? `${latest.scope.amount_min_paise != null ? formatPaise(latest.scope.amount_min_paise) : "—"} to ${latest.scope.amount_max_paise != null ? formatPaise(latest.scope.amount_max_paise) : "—"}`
          : "Any",
    },
    { label: "Effective", value: `${latest.effective_from}${latest.effective_to ? ` to ${latest.effective_to}` : " onwards"}` },
  ];

  const notAffected = backtest
    ? Math.max(backtest.cases_considered - backtest.would_explain.count - backtest.would_wrongly_close.count - backtest.would_partially_explain.count, 0)
    : 0;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow={
          <Link href="/rules" className="flex items-center gap-1 text-[11.5px] text-ink-3 hover:text-ink">
            <ArrowLeft width={12} height={12} /> Rule Book
          </Link>
        }
        title={
          <span className="flex items-center gap-3">
            {latest.name}
            <Pill tone={STATUS_TONE[latest.status]} dot>
              {latest.status}
            </Pill>
            {latest.origin === "learned" && <Pill tone="model">learned</Pill>}
          </span>
        }
        sub={
          <span className="num">
            {latest.rule_id} · v{latest.version} · {latest.scope.rule_set ?? "default"} · priority {latest.priority}
          </span>
        }
        actions={
          <>
            {latest.status === "draft" && (
              <>
                <Button variant="ok" icon={<CheckCheck width={13} height={13} />} onClick={() => setPending("activate")}>
                  Activate
                </Button>
                <Button variant="bad" icon={<Trash2 width={13} height={13} />} disabled={deleting} onClick={() => setPending("delete")}>
                  {deleting ? "Deleting…" : "Delete draft"}
                </Button>
              </>
            )}
            {latest.status === "active" && (
              <>
                <Button icon={<GitBranchPlus width={13} height={13} />} onClick={openNewVersion}>
                  New version
                </Button>
                <Button variant="bad" icon={<Archive width={13} height={13} />} onClick={() => setPending("retire")}>
                  Retire
                </Button>
              </>
            )}
          </>
        }
      />

      {pending === "delete" && (
        <div className="panel flex flex-wrap items-center gap-3 px-[18px] py-3.5">
          <span className="text-[12.5px] text-ink">
            Delete draft v{latest.version} of {latest.name}? This cannot be undone.
          </span>
          <Button variant="bad" disabled={deleting} onClick={deleteDraft} autoFocus>
            Delete draft
          </Button>
          <Button variant="ghost" onClick={() => setPending(null)}>
            Keep it
          </Button>
        </div>
      )}
      {(pending === "activate" || pending === "retire") && (
        <div className="panel flex flex-wrap items-center gap-3 px-[18px] py-3.5">
          <span className="text-[12.5px] text-ink">
            {pending === "activate" ? "Reason to activate. The back-test gate requires one." : "Reason to retire. It stops applying to new runs."}
          </span>
          <input value={reason} onChange={(e) => setReason(e.target.value)} className="input max-w-[420px] flex-1" autoFocus aria-label="Reason" />
          <Button variant={pending === "activate" ? "ok" : "bad"} disabled={!reason.trim() || acting} onClick={confirmPending}>
            {acting ? "Working…" : pending === "activate" ? "Activate rule" : "Retire rule"}
          </Button>
          <Button variant="ghost" onClick={() => setPending(null)}>
            Cancel
          </Button>
        </div>
      )}

      {draftingVersion && (
        <Panel title={`Draft version ${latest.version + 1}`} sub="Edit the deduction rates. Scope, tolerance and priority carry over; the old version stays exactly as it was.">
          <div className="flex flex-col gap-2">
            {versionDeductions.map((d, i) => (
              <div key={i} className="grid grid-cols-[160px_100px_120px_160px] items-center gap-2 text-[12.5px]">
                <span className="text-ink-2">{humanizeSnakeCase(d.type)}</span>
                <span className="text-[11.5px] text-ink-3">on {d.basis}</span>
                <input
                  value={d.rate}
                  onChange={(e) => setVersionDeductions((prev) => prev.map((x, idx) => (idx === i ? { ...x, rate: e.target.value } : x)))}
                  placeholder="rate %"
                  className="input num"
                />
                <input
                  value={d.fixed_paise}
                  onChange={(e) => setVersionDeductions((prev) => prev.map((x, idx) => (idx === i ? { ...x, fixed_paise: e.target.value } : x)))}
                  placeholder="flat paise"
                  className="input num"
                />
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-center gap-2">
            <Button variant="primary" disabled={submittingVersion} onClick={submitNewVersion}>
              {submittingVersion ? "Creating…" : `Create v${latest.version + 1} as draft`}
            </Button>
            <Button variant="ghost" onClick={() => setDraftingVersion(false)}>
              Cancel
            </Button>
          </div>
        </Panel>
      )}

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_1fr]">
        <div className="flex flex-col gap-5">
          <Panel title="When" sub="The scope this rule applies inside">
            <div className="grid grid-cols-2 gap-x-6 gap-y-3.5 md:grid-cols-3">
              {scopeFields.map((f) => (
                <div key={f.label}>
                  <div className="label">{f.label}</div>
                  <div className="num mt-1 text-[13px] text-ink">{f.value}</div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Then expect" sub="The deduction stack, evaluated in order on its stated basis">
            <ul className="flex flex-col gap-2">
              {(latest.deductions ?? []).map((d, i) => (
                <li key={i} className="flex items-center justify-between rounded-[8px] border border-line bg-bg px-3.5 py-2.5">
                  <div>
                    <div className="text-[13px] font-medium text-ink">{humanizeSnakeCase(d.type)}</div>
                    <div className="text-[11px] text-ink-3">{d.rate != null ? `${d.rate}% of ${d.basis}` : `flat, per ${d.basis}`}</div>
                  </div>
                  <div className="num text-[15px] font-semibold">{d.rate != null ? `${d.rate}%` : formatPaise(d.fixed_paise ?? 0)}</div>
                </li>
              ))}
            </ul>
            <div className="mt-3.5 flex items-center justify-between border-t border-line pt-3 text-[12.5px]">
              <span className="text-ink-3">
                Tolerance <span className="text-ink-3">absolute, then percent</span>
              </span>
              <span className="num text-[15px] font-semibold">
                {formatPaise(latest.tolerance.absolute_paise)} · {latest.tolerance.percent}%
              </span>
            </div>
          </Panel>

          <Panel title="Back-test" sub="Run against exceptions a human already resolved or wrote off. The only screen that can turn a draft active.">
            {!backtest ? (
              <Skeleton className="h-28" />
            ) : (
              <>
                <div className="num text-[12.5px] text-ink-2">
                  {backtest.cases_considered} historical cases · {backtest.unverified} unverified
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
                  {[
                    { label: "Would explain", value: backtest.would_explain.count, paise: backtest.would_explain.total_paise, tone: "text-ok" },
                    { label: "Partially", value: backtest.would_partially_explain.count, paise: backtest.would_partially_explain.total_paise, tone: "text-warn" },
                    { label: "Not affected", value: notAffected, paise: null, tone: "text-ink-2" },
                    {
                      label: "Wrongly close",
                      value: backtest.would_wrongly_close.count,
                      paise: backtest.would_wrongly_close.total_paise,
                      tone: backtest.would_wrongly_close.count > 0 ? "text-bad" : "text-ok",
                    },
                  ].map((b) => (
                    <div key={b.label} className="rounded-[8px] border border-line bg-bg px-3 py-2.5">
                      <div className="label">{b.label}</div>
                      <div className={cn("num mt-1.5 text-[22px] leading-none font-semibold", b.tone)}>{b.value}</div>
                      {b.paise != null && <div className="num mt-1 text-[10.5px] text-ink-3">{formatPaise(b.paise)}</div>}
                    </div>
                  ))}
                </div>
                <div className="mt-3.5 flex flex-wrap items-center gap-5 border-t border-line pt-3 text-[12.5px]">
                  <span className="text-ink-3">
                    Precision <span className="num ml-1 text-[15px] font-semibold text-ink">{backtest.precision_pct != null ? formatPercent(Number(backtest.precision_pct)) : "—"}</span>
                  </span>
                  <span className="text-ink-3">
                    Coverage <span className="num ml-1 text-[15px] font-semibold text-ink">{formatPercent(Number(backtest.coverage_pct))}</span>
                  </span>
                  <span className="ml-auto text-[12px] text-ink">{backtest.net_recommendation}</span>
                </div>
              </>
            )}
          </Panel>
        </div>

        <Panel title="Version history" sub="Immutable per version. Edits create the next one." className="h-fit">
          <ol className="flex flex-col">
            {versions
              .slice()
              .sort((a, b) => b.version - a.version)
              .map((v, i, arr) => (
                <li key={v.version} className="relative flex gap-3 pb-4 last:pb-0">
                  {i < arr.length - 1 && <span className="absolute top-3 left-[4px] h-full w-px bg-line" />}
                  <span className={cn("relative mt-[5px] h-[9px] w-[9px] flex-none rounded-full", v.status === "active" ? "bg-ok" : v.status === "retired" ? "bg-warn" : "bg-line-strong")} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="num text-[12.5px] font-semibold">v{v.version}</span>
                      <Pill tone={STATUS_TONE[v.status]}>{v.status}</Pill>
                      <span className="num ml-auto text-[10.5px] text-ink-3">{v.effective_from}</span>
                    </div>
                    <div className="num mt-1 text-[11.5px] text-ink-2">
                      {(v.deductions ?? []).map((d) => `${d.rate ?? 0}% ${humanizeSnakeCase(d.type)}`).join(" · ")}
                    </div>
                    <div className="num mt-0.5 text-[10.5px] text-ink-3">{v.version_hash.slice(0, 12)}</div>
                  </div>
                </li>
              ))}
          </ol>
        </Panel>
      </div>
    </div>
  );
}
