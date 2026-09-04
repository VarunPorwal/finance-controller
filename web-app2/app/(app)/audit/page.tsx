"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, ShieldAlert, ShieldCheck } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient } from "@/lib/client";
import { formatDateTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/ui/panel";
import { Pill } from "@/components/ui/pill";
import { Button } from "@/components/ui/button";
import { SkeletonRows } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { fetchAuditBundle } from "./loader";

const ACTOR_TONE: Record<string, "ok" | "model" | "accent" | "neutral"> = {
  system: "neutral",
  engine: "ok",
  agent: "model",
  human: "accent",
};

export default function AuditPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data } = useQuery({ queryKey: queryKeys.auditPage(runId), queryFn: () => fetchAuditBundle(runId) });
  const events = data?.events ?? null;
  const chain = data?.chain ?? null;
  const [exporting, setExporting] = useState(false);

  async function exportAudit(format: "csv" | "jsonl") {
    setExporting(true);
    try {
      const res = await apiClient.GET("/api/v1/audit/export", { params: { query: { run_id: runId, format } }, parseAs: "blob" });
      if (!res.data) return;
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit_${runId ?? "all"}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Audit Trail"
        sub="Every decision, hash-chained. Tamper-evident, not just logged."
        actions={
          <>
            <Button icon={<Download width={13} height={13} />} disabled={exporting} onClick={() => exportAudit("csv")}>
              CSV
            </Button>
            <Button icon={<Download width={13} height={13} />} disabled={exporting} onClick={() => exportAudit("jsonl")}>
              JSONL
            </Button>
          </>
        }
      />

      {chain && (
        <div
          className={cn(
            "panel flex items-center gap-4 px-[18px] py-4",
            chain.valid ? "border-[rgba(61,220,151,0.3)]" : "border-[rgba(255,107,107,0.4)]",
          )}
        >
          <span
            className={cn(
              "flex h-10 w-10 items-center justify-center rounded-[10px] border",
              chain.valid ? "border-[rgba(61,220,151,0.3)] bg-ok-soft text-ok" : "border-[rgba(255,107,107,0.3)] bg-bad-soft text-bad",
            )}
          >
            {chain.valid ? <ShieldCheck width={18} height={18} /> : <ShieldAlert width={18} height={18} />}
          </span>
          <div className="flex-1">
            <div className={cn("text-[13.5px] font-semibold", chain.valid ? "text-ok" : "text-bad")}>
              {chain.valid ? "Hash chain verified" : "Hash chain broken"}
            </div>
            <div className="num mt-0.5 text-[11.5px] text-ink-3">
              {chain.checked} events checked
              {chain.first_break_seq != null && ` · first break at seq ${chain.first_break_seq}`}
              {chain.reason && ` · ${chain.reason}`}
              {chain.advisory && ` · ${chain.advisory}`}
            </div>
          </div>
          <Pill tone={chain.valid ? "ok" : "bad"} dot>
            {chain.valid ? "intact" : "broken"}
          </Pill>
        </div>
      )}

      <Panel title={`Event log${runId ? ", this run" : ""}`} sub="Each row carries the hash of the one before it" flush>
        {events === null && <SkeletonRows rows={8} />}
        {events && events.length === 0 && <div className="px-[18px] py-8 text-center text-[12.5px] text-ink-3">Nothing recorded for this run yet.</div>}
        {events && events.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th pl-[18px] text-right">Seq</th>
                  <th className="th">When</th>
                  <th className="th">Actor</th>
                  <th className="th">Action</th>
                  <th className="th">Subject</th>
                  <th className="th pr-[18px] text-right">Hash</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.seq} className="text-[12.5px]">
                    <td className="td num pl-[18px] text-right text-ink-3">{e.seq}</td>
                    <td className="td num text-[11.5px] text-ink-3">{formatDateTime(e.created_at)}</td>
                    <td className="td">
                      <Pill tone={ACTOR_TONE[e.actor] ?? "neutral"}>{e.actor}</Pill>
                    </td>
                    <td className="td num text-ink">{e.action}</td>
                    <td className="td num max-w-[320px] truncate text-[11.5px] text-ink-3">
                      {e.subject_type} {e.subject_id}
                    </td>
                    <td className="td num pr-[18px] text-right text-[11px] text-ink-3" title={e.this_hash}>
                      {e.this_hash.slice(0, 12)}…
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
