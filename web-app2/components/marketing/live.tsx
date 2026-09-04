"use client";

import type { CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient, type components } from "@/lib/client";
import { useRun } from "@/lib/run-context";
import { formatCount, formatDurationMs, formatPaise, formatPaiseWhole, formatPercent } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { ProofTree } from "@/components/evidence-pack";
import { CountUp } from "@/components/marketing/count-up";
import { TypedTree, type Run } from "@/components/marketing/typed-tree";
import { cn } from "@/lib/utils";

type Evidence = components["schemas"]["ExceptionEvidenceOut"];

const cascadeStyle = (i: number) => ({ "--i": i }) as CSSProperties;

/**
 * Live figures for the landing page. Where a design shows a number, the
 * real one from the API is used, never a mock. When the API is unreachable
 * the slots read "—" and say so.
 */
export function LiveStats() {
  const { summary, loading, error } = useRun();
  const runId = summary?.run.run_id;
  const { data: evalResult } = useQuery({
    queryKey: queryKeys.eval(runId),
    queryFn: async () => (await apiClient.GET("/api/v1/eval/{run_id}", { params: { path: { run_id: runId! } } })).data ?? null,
    enabled: !!runId,
  });
  const { data: bridge } = useQuery({
    queryKey: queryKeys.cashBridge(runId),
    queryFn: async () => (await apiClient.GET("/api/v1/cash/bridge", { params: { query: { run_id: runId! } } })).data ?? null,
    enabled: !!runId,
  });
  const autoMatched = summary ? summary.event_count - summary.exception_count : null;
  const stats = [
    { label: "Total cash", value: bridge?.actual_bank_paise ?? null, format: (n: number) => formatPaiseWhole(n), tone: "text-ok" },
    { label: "Runtime", value: summary?.run.runtime_ms ?? null, format: formatDurationMs },
    {
      label: "Auto-resolved",
      value: summary && autoMatched != null ? (summary.event_count ? autoMatched / summary.event_count : 0) : null,
      format: formatPercent,
      tone: "text-ok",
    },
    { label: "Needs a human", value: summary?.escalated_count ?? null, format: formatCount, tone: "text-warn" },
    {
      label: "False auto-closes",
      value: evalResult?.false_auto_resolutions ?? null,
      format: (n: number) => String(Math.round(n)),
      tone: evalResult && evalResult.false_auto_resolutions === 0 ? "text-ok" : "text-ink",
    },
  ];
  return (
    <div className="m-frame grid grid-cols-2 divide-x divide-[rgba(255,255,255,0.06)] md:grid-cols-5">
      {stats.map((s, i) => (
        <div key={s.label} className="cascade px-5 py-4" style={cascadeStyle(i)}>
          <div className="label">{s.label}</div>
          <div className={cn("num mt-2 text-[28px] leading-none font-semibold", loading ? "text-ink-4" : (s.tone ?? "text-ink"))}>
            <CountUp value={s.value} format={s.format} />
          </div>
        </div>
      ))}
      {error && <div className="col-span-full border-t border-[rgba(255,255,255,0.06)] px-5 py-2 text-[11px] text-ink-3">Live numbers appear when the API is reachable. {error}.</div>}
    </div>
  );
}

export function LiveBridge() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data: bridge } = useQuery({
    queryKey: queryKeys.cashBridge(runId),
    queryFn: async () => (await apiClient.GET("/api/v1/cash/bridge", { params: { query: { run_id: runId! } } })).data ?? null,
    enabled: !!runId,
  });

  if (!bridge) {
    return (
      <pre className="tree m-frame p-6 text-ink-4">
        {`GROSS COLLECTED                                     —
  ├─ deductions, per rule, per row               —
  └─ EXPECTED NET                                     —
       vs BANK CREDITED                                —
       ─────────────────────────────────────────────────
       UNEXPLAINED                                     —`}
      </pre>
    );
  }

  const pad = (s: string, n: number) => (s.length >= n ? s : " ".repeat(n - s.length) + s);
  const col = 58;
  const line = (label: string, amount: string, indent = 0) => {
    const left = " ".repeat(indent) + label;
    return left + pad(amount, Math.max(1, col - left.length));
  };
  const gapNonZero = bridge.unexplained_paise !== 0;

  const runs: Run[] = [{ text: line("GROSS COLLECTED", formatPaise(bridge.gross_collected_paise)) + "\n", className: "bold" }];
  bridge.deductions.forEach((d, i) => {
    runs.push({
      text: line(`${i === bridge.deductions.length - 1 ? "└─" : "├─"} ${d.label}`, "−" + formatPaise(d.amount_paise), 2) + "\n",
    });
  });
  runs.push(
    { text: line("EXPECTED NET", formatPaise(bridge.expected_net_paise), 2) + "\n", className: "bold" },
    { text: line("vs BANK CREDITED", formatPaise(bridge.actual_bank_paise), 7) + "\n", className: "ok" },
    { text: "       " + "─".repeat(col - 7) + "\n", className: "dim" },
    { text: line("UNEXPLAINED", formatPaise(bridge.unexplained_paise), 7) + "\n", className: cn("bold", gapNonZero ? "warn" : "ok") },
    {
      text:
        "       " +
        (gapNonZero
          ? `${bridge.segments.find((s) => s.label === "Unexplained")?.exception_ids.length ?? 0} exceptions carry it · click the gap in the product to see them`
          : "balances to the paise"),
      className: "dim",
    },
  );

  return <TypedTree runs={runs} className="m-frame p-6 text-[12.5px]" />;
}

export function LiveProof() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data: evidenceList } = useQuery({
    queryKey: ["landing", "proof", runId],
    queryFn: async (): Promise<Evidence[]> => {
      const { data } = await apiClient.GET("/api/v1/exceptions", { params: { query: { run_id: runId!, status: "open", limit: 50 } } });
      const items = data?.items ?? [];
      const primary = items.find((e) => e.tier === "escalate" && (e.rules_applied?.length ?? 0) > 0) ?? items.find((e) => e.tier === "escalate") ?? items[0];
      const secondary =
        items.find((e) => e.exception_id !== primary?.exception_id && e.category !== primary?.category) ??
        items.find((e) => e.exception_id !== primary?.exception_id);
      const picks = [primary, secondary].filter((e): e is NonNullable<typeof e> => !!e);
      const evidences = await Promise.all(
        picks.map(async (p) => {
          const { data: ev } = await apiClient.GET("/api/v1/exceptions/{exception_id}/evidence", { params: { path: { exception_id: p.exception_id } } });
          return ev ?? null;
        }),
      );
      return evidences.filter((e): e is Evidence => !!e);
    },
    enabled: !!runId,
  });

  if (!evidenceList || evidenceList.length === 0) {
    return (
      <pre className="tree m-frame p-6 text-ink-4">
        {`missing_in_bank · 1 event · residual —
├─ stage fee_adjusted  held  confidence —
│  └─ agreed amount, date · disagreed reference
│     base — → result —
└─ rule — v—  explained —`}
      </pre>
    );
  }
  return (
    <div className="flex flex-col gap-4">
      {evidenceList.map((evidence) => (
        <div key={evidence.exception.exception_id} className="m-frame p-6">
          <ProofTree evidence={evidence} />
        </div>
      ))}
    </div>
  );
}

export function LiveGates() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data: evalResult } = useQuery({
    queryKey: queryKeys.eval(runId),
    queryFn: async () => (await apiClient.GET("/api/v1/eval/{run_id}", { params: { path: { run_id: runId! } } })).data ?? null,
    enabled: !!runId,
  });
  const gates = (evalResult?.gates ?? []) as { name: string; passed: boolean; actual: unknown; threshold: unknown }[];
  const fallback = [
    { name: "false_auto_resolutions", threshold: "== 0" },
    { name: "recall", threshold: ">= 90%" },
    { name: "precision", threshold: "== 100%" },
    { name: "determinism", threshold: "byte-identical" },
  ];
  const rows = gates.length ? gates : fallback.map((g) => ({ ...g, passed: null as boolean | null, actual: "—" }));
  return (
    <ul className="m-frame divide-y divide-[rgba(255,255,255,0.06)]">
      {rows.map((g, i) => (
        <li
          key={g.name}
          className={cn("cascade m-row flex items-center gap-4 px-5 py-3.5", g.passed === null ? "text-ink-4" : g.passed ? "text-ok" : "text-bad")}
          style={cascadeStyle(i)}
        >
          <span className={cn("h-2 w-2 rounded-full", g.passed === null ? "bg-ink-4" : g.passed ? "bg-ok" : "bg-bad")} />
          <span className="num flex-1 text-[12.5px] text-ink">{g.name.replace(/_/g, " ")}</span>
          <span className="num text-[11.5px] text-ink-3">gate {String(g.threshold)}</span>
          <span className={cn("num w-24 text-right text-[15px] font-semibold", g.passed === null ? "text-ink-4" : g.passed ? "text-ok" : "text-bad")}>{String(g.actual)}</span>
        </li>
      ))}
    </ul>
  );
}
