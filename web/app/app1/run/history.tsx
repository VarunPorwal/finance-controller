"use client";

// The last runs, collapsed into one table. Filterable by kind (server-side)
// and by date (client-side, over whatever page was fetched) — both real
// fields on RunOut. A rule-set filter is not offered: RunOut only carries
// `ruleset_hash`, and nothing in the API maps a hash back to the rule set
// name it was built from, so a filter here would have to guess.

import { useMemo, useState } from "react";
import Link from "next/link";
import { clsx } from "clsx";
import { ArrowRight } from "lucide-react";
import { ErrorNote } from "../_components/ui";
import { formatCount, formatDateTime, formatDurationMs, shortId, hashShort } from "../_lib/format";
import { skel, fieldStyle } from "./_shared";
import type { RunOut } from "../_lib/api";

type Kind = "all" | "original" | "replay";

function statusDot(status: string): string | undefined {
  if (status === "complete" || status === "completed") return "var(--fc-ok)";
  if (status === "failed" || status === "error") return "var(--fc-bad)";
  if (status === "running" || status === "open" || status === "pending") return "var(--fc-warn)";
  return undefined;
}

export function RunHistory({
  runs,
  loading,
  error,
  currentRunId,
  kind,
  onKind,
}: {
  runs: RunOut[] | undefined;
  loading: boolean;
  error: string | null;
  currentRunId: string | undefined;
  kind: Kind;
  onKind: (k: Kind) => void;
}) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const filtered = useMemo(() => {
    if (!runs) return runs;
    return runs.filter((r) => {
      if (from && r.started_at < from) return false;
      if (to && r.started_at > `${to}T23:59:59`) return false;
      return true;
    });
  }, [runs, from, to]);

  return (
    <div className="fc-card fc-card--flat">
      <div className="fc-lhead">
        <span>Run history</span>
        <Link href="/app1/controller-activity#diff" className="fc-link inline-flex items-center gap-1">
          Diff vs current <ArrowRight size={11} />
        </Link>
      </div>
      <div className="flex flex-wrap items-center gap-2 px-4 pb-3">
        <select value={kind} onChange={(e) => onKind(e.target.value as Kind)} style={fieldStyle} aria-label="Kind">
          <option value="all">All kinds</option>
          <option value="original">Original</option>
          <option value="replay">Replay</option>
        </select>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} style={fieldStyle} aria-label="From date" />
        <span className="fc-faint">to</span>
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} style={fieldStyle} aria-label="To date" />
        {(from || to) && (
          <button
            className="fc-link"
            style={{ background: "none", border: 0, cursor: "pointer" }}
            onClick={() => {
              setFrom("");
              setTo("");
            }}
          >
            Clear dates
          </button>
        )}
      </div>
      <div className="px-2 pb-2">
        {loading ? (
          <div className="px-2 pb-2">{skel("h-24 w-full")}</div>
        ) : error ? (
          <div className="px-3 pb-3">
            <ErrorNote message={error} />
          </div>
        ) : !filtered || filtered.length === 0 ? (
          <div className="fc-body px-4 py-6">No runs match. Run the demo corpus above and the first row appears here.</div>
        ) : (
          <div style={{ maxHeight: 420, overflow: "auto" }}>
            <table className="fc-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Started</th>
                  <th style={{ textAlign: "right" }}>Rows</th>
                  <th style={{ textAlign: "right" }}>Runtime</th>
                  <th>Status</th>
                  <th>Kind</th>
                  <th>Rule set</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => {
                  const current = r.run_id === currentRunId;
                  return (
                    <tr key={r.run_id} className={clsx(current && "is-sel")}>
                      <td>
                        <span className={current ? "fc-ok" : "fc-muted"} title={r.run_id}>
                          run·{shortId(r.run_id)}
                        </span>
                        {current && <span className="fc-faint ml-2" style={{ fontSize: 11 }}>current</span>}
                      </td>
                      <td className="fc-muted">{formatDateTime(r.started_at)}</td>
                      <td className="fc-table-num">{r.record_count == null ? "—" : formatCount(r.record_count)}</td>
                      <td className="fc-table-num">{r.runtime_ms == null ? "—" : formatDurationMs(r.runtime_ms)}</td>
                      <td>
                        <span className="fc-status">
                          <span className="fc-dot" style={{ background: statusDot(r.status) ?? "var(--fc-text-3)" }} />
                          {r.status}
                        </span>
                      </td>
                      <td>
                        {r.parent_run_id ? (
                          <span className="fc-muted" title={r.replay_reason ?? undefined}>
                            Replay of <span className="fc-ref">{shortId(r.parent_run_id)}</span>
                          </span>
                        ) : (
                          <span className="fc-muted">Original</span>
                        )}
                      </td>
                      <td>
                        <span className="fc-faint" title={r.ruleset_hash}>
                          {hashShort(r.ruleset_hash)}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
