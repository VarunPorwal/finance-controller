"use client";

// What ingestion pushed back on, and the guards that stood between the
// files and the cascade.

import { formatCount } from "../_lib/format";
import { GuardCheck, SourceDot } from "./_shared";
import type { SourceKey } from "./timeline";
import type { Uploads } from "./upload";

const GUARDS = [
  "Balance continuity on the bank statement",
  "Narration scan for injected instructions",
  "Idempotency by voucher GUID, entity id and line hash",
];

const ORDER: SourceKey[] = ["razorpay", "bank", "ledger"];

export function Findings({ uploads }: { uploads: Uploads }) {
  const rows = ORDER.flatMap((s) => {
    const r = uploads[s]?.result;
    if (!r) return [];
    return [{ source: s, rejections: r.rejections, deduplicated: r.deduplicated }];
  }).filter((x) => x.rejections.length > 0 || x.deduplicated > 0);

  const totalDeduped = rows.reduce((n, x) => n + x.deduplicated, 0);

  return (
    <div className="fc-split">
      <div className="fc-card fc-card--flat">
        <div className="fc-lhead">Findings</div>
        <div className="px-4 pb-4" style={{ marginTop: -4 }}>
          <p className="fc-body mb-2">Rows the parsers refused or folded, from files uploaded in this session.</p>
          {rows.length === 0 ? (
            <p className="fc-faint" style={{ fontSize: 12.5 }}>No rows rejected in the current session&apos;s uploads.</p>
          ) : (
            <div className="flex flex-col gap-4">
              {rows.map((x) => (
                <div key={x.source}>
                  <div className="mb-1.5 flex items-center gap-2">
                    <SourceDot source={x.source} />
                    {x.deduplicated > 0 && (
                      <span className="fc-faint" style={{ fontSize: 12 }}>
                        <span className="fc-num">{formatCount(x.deduplicated)}</span> duplicates folded
                      </span>
                    )}
                    {x.rejections.length > 0 && (
                      <span style={{ fontSize: 12, color: "var(--fc-warn)" }}>
                        <span className="fc-num">{formatCount(x.rejections.length)}</span> rejected
                      </span>
                    )}
                  </div>
                  {x.rejections.length > 0 && (
                    <table className="fc-table">
                      <thead>
                        <tr>
                          <th>Row</th>
                          <th>Reason</th>
                          <th style={{ textAlign: "right" }}>Fields</th>
                        </tr>
                      </thead>
                      <tbody>
                        {x.rejections.map((r, i) => (
                          <tr key={i}>
                            <td className="fc-ref">{r.source_row_id ?? "—"}</td>
                            <td>{r.reason}</td>
                            <td className="fc-table-num">{r.field_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="fc-card">
        <div className="fc-card-title mb-1">Guards that ran</div>
        <p className="fc-body mb-2">Checks that run before any matching.</p>
        <ul className="flex flex-col gap-2">
          {GUARDS.map((g) => (
            <GuardCheck key={g}>
              {g}
              {g.startsWith("Idempotency") && totalDeduped > 0 ? ` · ${formatCount(totalDeduped)} folded this session` : ""}
            </GuardCheck>
          ))}
        </ul>
      </div>
    </div>
  );
}
