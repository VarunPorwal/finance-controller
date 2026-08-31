"use client";

import { useEffect, useState } from "react";
import { Download, ShieldCheck, ShieldAlert } from "lucide-react";
import { useRun } from "@/lib/run-context";
import { apiClient, type components } from "@/lib/client";
import { StatusPill } from "@/components/ui/status-pill";
import { PlaceholderPanel } from "@/components/placeholder-panel";
import { cacheGet, cacheSet } from "@/lib/page-cache";

type AuditEvent = components["schemas"]["AuditEventOut"];
type VerifyChainOut = components["schemas"]["VerifyChainOut"];
type AuditBundle = { events: AuditEvent[]; chain: VerifyChainOut | null };

export default function AuditPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const cacheKey = `audit:${runId ?? "all"}`;
  const cached = cacheGet<AuditBundle>(cacheKey);
  const [events, setEvents] = useState<AuditEvent[] | null>(cached?.events ?? null);
  const [chain, setChain] = useState<VerifyChainOut | null>(cached?.chain ?? null);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const key = `audit:${runId ?? "all"}`;
    const seeded = cacheGet<AuditBundle>(key);
    if (seeded) {
      setEvents(seeded.events);
      setChain(seeded.chain);
    }
    async function load() {
      const [eventsRes, chainRes] = await Promise.all([
        apiClient.GET("/api/v1/audit", { params: { query: { run_id: runId, limit: 100 } } }),
        apiClient.GET("/api/v1/audit/verify-chain", { params: { query: {} } }),
      ]);
      if (cancelled) return;
      const bundle: AuditBundle = { events: eventsRes.data?.items ?? [], chain: chainRes.data ?? null };
      cacheSet(key, bundle);
      setEvents(bundle.events);
      setChain(bundle.chain);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  async function exportAudit(format: "csv" | "jsonl") {
    setExporting(true);
    try {
      const res = await apiClient.GET("/api/v1/audit/export", {
        params: { query: { run_id: runId, format } },
        parseAs: "blob",
      });
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
    <div>
      <div className="mb-4.5 flex items-center justify-between">
        <div>
          <div className="text-2xl font-semibold tracking-[-0.025em]">Audit Trail</div>
          <div className="mt-[3px] text-[13px] text-text-muted">
            Every decision, hash-chained — tamper-evident, not just logged
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={exporting}
            onClick={() => exportAudit("csv")}
            className="flex items-center gap-1.5 rounded-[7px] border border-border px-3 py-1.5 text-xs font-medium disabled:opacity-50"
          >
            <Download width={13} height={13} />
            Export CSV
          </button>
          <button
            type="button"
            disabled={exporting}
            onClick={() => exportAudit("jsonl")}
            className="flex items-center gap-1.5 rounded-[7px] border border-border px-3 py-1.5 text-xs font-medium disabled:opacity-50"
          >
            <Download width={13} height={13} />
            Export JSONL
          </button>
        </div>
      </div>

      {chain && (
        <div
          className="fc-card mb-5 flex items-center gap-3 px-5 py-4"
          style={{
            background: chain.valid ? "var(--success-bg)" : "var(--error-bg)",
          }}
        >
          {chain.valid ? (
            <ShieldCheck width={18} height={18} color="var(--success)" />
          ) : (
            <ShieldAlert width={18} height={18} color="var(--error)" />
          )}
          <div className="flex-1">
            <div className="text-[13.5px] font-semibold" style={{ color: chain.valid ? "var(--success)" : "var(--error)" }}>
              {chain.valid ? "Hash chain verified" : "Hash chain broken"}
            </div>
            <div className="mt-0.5 text-[12px] text-text-muted">
              {chain.checked} events checked
              {chain.first_break_seq != null && ` — first break at seq ${chain.first_break_seq}`}
              {chain.reason && ` — ${chain.reason}`}
              {chain.advisory && ` — ${chain.advisory}`}
            </div>
          </div>
          <StatusPill tone={chain.valid ? "success" : "error"}>{chain.valid ? "INTACT" : "BROKEN"}</StatusPill>
        </div>
      )}

      <div className="fc-card overflow-hidden">
        <div className="border-b border-border px-5 py-3.5 text-sm font-semibold">
          Event log{runId ? ", this run" : ""}
        </div>
        {events === null && <div className="h-40 animate-pulse" aria-hidden />}
        {events && events.length === 0 && (
          <div className="p-5">
            <PlaceholderPanel title="No audit events" note="Nothing has been recorded for this run yet." />
          </div>
        )}
        {events && events.length > 0 && (
          <table className="w-full">
            <thead>
              <tr className="border-b border-[color:var(--neutral-bg)] text-[11px] font-semibold tracking-[0.03em] text-text-muted">
                <th className="px-5 py-2.5 text-left">SEQ</th>
                <th className="px-3 py-2.5 text-left">WHEN</th>
                <th className="px-3 py-2.5 text-left">ACTOR</th>
                <th className="px-3 py-2.5 text-left">ACTION</th>
                <th className="px-3 py-2.5 text-left">SUBJECT</th>
                <th className="px-5 py-2.5 text-right">HASH</th>
              </tr>
            </thead>
            <tbody>
              {events.map((e) => (
                <tr key={e.seq} className="border-b border-[color:var(--neutral-bg)] text-[13px] last:border-0">
                  <td className="fc-numeric px-5 py-3 text-text-muted">{e.seq}</td>
                  <td className="fc-numeric px-3 py-3 text-xs text-text-muted">
                    {new Date(e.created_at).toLocaleString("en-IN")}
                  </td>
                  <td className="px-3 py-3">{e.actor}</td>
                  <td className="px-3 py-3">{e.action}</td>
                  <td className="px-3 py-3 text-text-muted">
                    {e.subject_type} {e.subject_id}
                  </td>
                  <td className="fc-numeric px-5 py-3 text-right text-[11px] text-text-faint" title={e.this_hash}>
                    {e.this_hash.slice(0, 10)}…
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
