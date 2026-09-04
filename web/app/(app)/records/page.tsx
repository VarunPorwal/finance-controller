"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRun } from "@/lib/run-context";
import { formatCount, formatDateShort, formatDateTime, formatPaise } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/ui/panel";
import { Pill } from "@/components/ui/pill";
import { Segmented } from "@/components/ui/segmented";
import { SkeletonRows } from "@/components/ui/skeleton";
import { SourceGlyph, sourceMeta } from "@/components/ui/source-glyph";
import { fetchRecordsBundle } from "./loader";

const SOURCES = ["razorpay", "bank", "ledger"] as const;

export default function RecordsPage() {
  const { summary } = useRun();
  const runId = summary?.run.run_id;
  const { data } = useQuery({ queryKey: queryKeys.records(runId), queryFn: () => fetchRecordsBundle(runId!), enabled: !!runId });
  const [filter, setFilter] = useState("all");
  const counts = data?.counts ?? null;
  const history = data?.history ?? [];
  const events = (data?.events ?? []).filter((e) => filter === "all" || e.source === filter);
  const lastBySource = new Map(history.map((h) => [h.action.replace("ingest.", ""), h]));

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Records"
        sub="Normalised rows from every source. Amounts are integer paise; references are shown as the source wrote them."
        actions={
          <Segmented
            active={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "All", count: counts?.total },
              ...SOURCES.map((s) => ({ value: s, label: sourceMeta(s).label, count: counts?.by_source[s] })),
            ]}
          />
        }
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {SOURCES.map((source) => {
          const count = counts?.by_source[source] ?? 0;
          const last = lastBySource.get(source);
          const rejections = Number((last?.payload as Record<string, unknown> | undefined)?.rejection_count ?? 0);
          return (
            <div key={source} className="panel flex items-center gap-4 px-[18px] py-4">
              <SourceGlyph source={source} size={38} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold">{sourceMeta(source).label}</span>
                  <Pill tone={rejections > 0 ? "warn" : count > 0 ? "ok" : "neutral"}>
                    {rejections > 0 ? `${rejections} rejected` : count > 0 ? "Healthy" : "No data"}
                  </Pill>
                </div>
                <div className="text-[11px] text-ink-3">{last ? `imported ${formatDateTime(last.created_at)}` : "never imported"}</div>
              </div>
              <div className="num text-[22px] font-semibold">{formatCount(count)}</div>
            </div>
          );
        })}
      </div>

      <Panel title="Ledger" sub={`First ${events.length} rows of this run`} flush>
        {!data ? (
          <SkeletonRows rows={10} />
        ) : events.length === 0 ? (
          <div className="px-[18px] py-8 text-center text-[12.5px] text-ink-3">No rows under this filter.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th pl-[18px]">Date</th>
                  <th className="th">Source</th>
                  <th className="th">Reference</th>
                  <th className="th">Counterparty</th>
                  <th className="th">Rail</th>
                  <th className="th text-right">Amount</th>
                  <th className="th pr-[18px] text-right">Direction</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.event_id} className="text-[12.5px]">
                    <td className="td num pl-[18px] text-ink-2">{formatDateShort(e.txn_date)}</td>
                    <td className="td">
                      <span className="flex items-center gap-2">
                        <SourceGlyph source={e.source} size={20} />
                        {sourceMeta(e.source).label}
                      </span>
                    </td>
                    <td className="td num max-w-[260px] truncate text-[11.5px] text-ink-2" title={e.raw_narration ?? undefined}>
                      {e.utr ?? e.settlement_id ?? e.voucher_number ?? e.order_id ?? "—"}
                    </td>
                    <td className="td max-w-[200px] truncate text-ink-2">{e.counterparty ?? "—"}</td>
                    <td className="td text-ink-3 uppercase">{e.rail ?? e.method ?? "—"}</td>
                    <td className="td num text-right text-[15px] font-medium">{formatPaise(e.amount_paise)}</td>
                    <td className="td pr-[18px] text-right">
                      <Pill tone={e.direction === "credit" ? "ok" : "neutral"}>{e.direction}</Pill>
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
