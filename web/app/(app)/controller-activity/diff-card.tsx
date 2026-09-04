"use client";

// Replay and diff. Decisions keyed by the transactions they cover, so two
// runs compare even when ids differ. The determinism gate itself (same seed,
// same output) lives on Evaluation — this card duplicates the tiny
// Counts/Tick helpers rather than importing across folders.

import { useEffect, useMemo, useState } from "react";
import { Check, X, GitCompare } from "lucide-react";
import { useRuns, useRunDiff, errorMessage, type DiffOut, type RunOut } from "../_lib/api";
import { categoryLabel } from "../_lib/labels";
import { formatDateTime, shortId } from "../_lib/format";
import { FcCard, FcCardHeader, FcChip, FcErrorNote, FcMoney, FcSkeleton } from "../_components/fc-ui";

function Counts({ d }: { d: DiffOut }) {
  const n = [d.diff.changed.length, d.diff.added.length, d.diff.removed.length];
  const identical = n.every((x) => x === 0);
  return (
    <div className="flex items-center gap-4">
      <Tick ok={identical} />
      <div className="flex items-baseline gap-3">
        {(["changed", "added", "removed"] as const).map((k, i) => (
          <span key={k} className="flex items-baseline gap-1.5">
            <span className="fc-num" style={{ fontSize: 22, color: n[i] === 0 ? "var(--fc-ok)" : "var(--fc-bad)" }}>
              {n[i]}
            </span>
            <span className="fc-faint" style={{ fontSize: 12 }}>{k}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function Tick({ ok }: { ok: boolean }) {
  return (
    <span
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
      style={{
        border: `1px solid color-mix(in srgb, ${ok ? "var(--fc-ok)" : "var(--fc-bad)"} 40%, transparent)`,
        background: `color-mix(in srgb, ${ok ? "var(--fc-ok)" : "var(--fc-bad)"} 14%, transparent)`,
        color: ok ? "var(--fc-ok)" : "var(--fc-bad)",
      }}
    >
      {ok ? <Check size={13} /> : <X size={13} />}
    </span>
  );
}

export function DiffCard({ runId }: { runId: string | undefined }) {
  const runs = useRuns("all", 10);
  const replay = runs.data?.find((r) => r.parent_run_id === runId && r.status !== "failed");
  const [a, setA] = useState<string>("");
  const [b, setB] = useState<string>("");
  const list = useMemo(() => runs.data ?? [], [runs.data]);

  useEffect(() => {
    if (!a && runId) setA(runId);
  }, [a, runId]);
  useEffect(() => {
    if (b) return;
    const fallback = list.find((r) => r.run_id !== (runId ?? ""))?.run_id;
    const pick = replay?.run_id ?? fallback;
    if (pick) setB(pick);
  }, [b, replay?.run_id, list, runId]);

  const diff = useRunDiff(a || undefined, b || undefined);
  const runLabel = (r: RunOut) =>
    `${shortId(r.run_id)} · ${formatDateTime(r.started_at)}${r.parent_run_id ? " · replay" : ""}`;

  return (
    <FcCard variant="flat" id="diff" className="scroll-mt-20">
      <FcCardHeader
        title={
          <span className="flex items-center gap-2">
            <GitCompare size={14} className="fc-faint" />
            Replay and diff
          </span>
        }
        sub="Decisions keyed by the transactions they cover, so two runs compare even when ids differ"
      />
      <div className="flex flex-col gap-3" style={{ padding: "0 16px 16px" }}>
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
          <select className="fc-btn fc-btn--ghost" style={{ justifyContent: "flex-start" }} value={a} onChange={(e) => setA(e.target.value)} aria-label="From run" disabled={runs.isLoading}>
            {list.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {runLabel(r)}
              </option>
            ))}
          </select>
          <span className="fc-faint" style={{ fontSize: 12 }}>→</span>
          <select className="fc-btn fc-btn--ghost" style={{ justifyContent: "flex-start" }} value={b} onChange={(e) => setB(e.target.value)} aria-label="To run" disabled={runs.isLoading}>
            {list.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {runLabel(r)}
              </option>
            ))}
          </select>
        </div>
        {a && b && a === b && <p className="fc-faint" style={{ fontSize: 12 }}>Pick two different runs.</p>}
        {diff.isLoading && <FcSkeleton className="h-16" />}
        {diff.error && <FcErrorNote message={errorMessage(diff.error)} />}
        {diff.data && (
          <>
            <Counts d={diff.data} />
            {diff.data.diff.changed.length > 0 && (
              <div className="fc-card fc-card--flat" style={{ padding: 0, overflow: "hidden" }}>
                <table className="fc-table">
                  <thead>
                    <tr>
                      <th>Why</th>
                      <th>Before</th>
                      <th>After</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diff.data.diff.changed.slice(0, 10).map((c, i) => (
                      <tr key={i}>
                        <td className="fc-muted" style={{ maxWidth: 320, fontSize: 12 }}>{c.why}</td>
                        <td>
                          {c.before ? (
                            <span className="flex flex-col gap-0.5">
                              <FcChip>{categoryLabel(c.before.category)}</FcChip>
                              <FcMoney paise={c.before.amount_paise} size="sm" />
                            </span>
                          ) : (
                            <span className="fc-faint">none</span>
                          )}
                        </td>
                        <td>
                          {c.after ? (
                            <span className="flex flex-col gap-0.5">
                              <FcChip tone={c.before && c.after.category !== c.before.category ? "warn" : "neutral"}>
                                {categoryLabel(c.after.category)}
                              </FcChip>
                              <FcMoney paise={c.after.amount_paise} size="sm" />
                            </span>
                          ) : (
                            <span className="fc-faint">none</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {diff.data.diff.changed.length > 10 && (
                  <div className="fc-faint" style={{ padding: "8px 12px", fontSize: 11.5 }}>
                    Showing 10 of {diff.data.diff.changed.length} changed.
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </FcCard>
  );
}
