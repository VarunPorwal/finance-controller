"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRun } from "@/lib/run-context";
import { formatCount, formatDateTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { IngestPanel } from "@/components/ingest-panel";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/ui/panel";
import { Pill } from "@/components/ui/pill";
import { SourceGlyph, sourceMeta } from "@/components/ui/source-glyph";
import { fetchSourcesBundle } from "./loader";

// Ledger rows are stored with source="ledger" (fc/ingest/tally.py); the
// lookup key into by_source has to match what the pipeline wrote.
const CONNECTORS = [
  { key: "razorpay", name: "Razorpay", format: "Recon report · JSON", note: "Settlements, fees, GST and TDS per transaction" },
  { key: "bank", name: "Bank statement", format: "NetBanking CSV or PDF", note: "The only source that proves money moved" },
  { key: "ledger", name: "Tally", format: "Day book export · CSV or XML", note: "What the books say should have happened" },
];

export default function IngestPage() {
  const router = useRouter();
  const { summary, refresh } = useRun();
  const runId = summary?.run.run_id;

  function onRunComplete() {
    refresh();
    router.push("/reconcile");
  }

  const { data } = useQuery({ queryKey: queryKeys.sources(runId), queryFn: () => fetchSourcesBundle(runId!), enabled: !!runId });
  const counts = data?.counts ?? null;
  const history = data?.history ?? [];
  const lastBySource = new Map(history.map((h) => [h.action.replace("ingest.", ""), h]));

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title="Ingest" sub="Three sources, normalised to integer paise, checked for balance continuity before a single row is saved." />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {CONNECTORS.map((c) => {
          const count = counts?.by_source[c.key] ?? 0;
          const connected = count > 0;
          const last = lastBySource.get(c.key);
          const rejections = Number((last?.payload as Record<string, unknown> | undefined)?.rejection_count ?? 0);
          const { color } = sourceMeta(c.key);
          return (
            <div key={c.key} className="panel relative overflow-hidden px-[18px] pt-4 pb-[18px]">
              <div className="absolute inset-x-0 top-0 h-[2px]" style={{ background: connected ? color : "var(--line-strong)" }} />
              <div className="flex items-start justify-between">
                <SourceGlyph source={c.key} size={34} />
                <Pill tone={connected ? (rejections > 0 ? "warn" : "ok") : "neutral"} dot={connected}>
                  {connected ? (rejections > 0 ? `${rejections} rejected` : "Ingested") : "Waiting"}
                </Pill>
              </div>
              <div className="mt-3 text-[14px] font-semibold">{c.name}</div>
              <div className="text-[11.5px] text-ink-3">{c.format}</div>
              <div className="num mt-3 text-[22px] leading-none font-semibold">{connected ? formatCount(count) : "-"}</div>
              <div className="mt-1 text-[11px] text-ink-3">
                {connected ? `rows in this run${last ? ` · ${formatDateTime(last.created_at)}` : ""}` : c.note}
              </div>
            </div>
          );
        })}
      </div>

      <IngestPanel onComplete={onRunComplete} />

      <Panel title="Import history" sub="Every ingest is an audit event" flush>
        {history.length === 0 ? (
          <div className="px-[18px] py-6 text-center text-[12.5px] text-ink-3">Nothing imported into this run yet.</div>
        ) : (
          <table className="w-full">
            <thead>
              <tr>
                <th className="th pl-[18px]">Source</th>
                <th className="th">File</th>
                <th className="th text-right">Rows</th>
                <th className="th">Status</th>
                <th className="th pr-[18px] text-right">When</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => {
                const payload = h.payload as Record<string, unknown>;
                const rejected = Number(payload.rejection_count ?? 0);
                const src = h.action.replace("ingest.", "");
                return (
                  <tr key={h.seq} className="text-[12.5px]">
                    <td className="td pl-[18px]">
                      <span className="flex items-center gap-2">
                        <SourceGlyph source={src} size={20} />
                        {sourceMeta(src).label}
                      </span>
                    </td>
                    <td className="td num text-[11.5px] text-ink-2">{String(payload.filename ?? "-")}</td>
                    <td className="td num text-right text-[15px]">{String(payload.event_count ?? 0)}</td>
                    <td className="td">
                      <Pill tone={rejected > 0 ? "warn" : "ok"}>{rejected > 0 ? `${rejected} rejected` : "Healthy"}</Pill>
                    </td>
                    <td className="td num pr-[18px] text-right text-ink-3">{formatDateTime(h.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
