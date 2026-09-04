"use client";

// Same seed, same output. Proven by a replay when one exists, and by the eval
// gate otherwise. The run-vs-run diff picker lives on Controller Activity
// (diff-card.tsx) — this card only proves the gate, so it duplicates the tiny
// Counts/Tick helpers rather than importing across folders.

import { Check, X } from "lucide-react";
import { useRuns, useRunDiff, errorMessage, type DiffOut } from "../_lib/api";
import { hashShort, shortId } from "../_lib/format";
import { FcCard, FcErrorNote, FcSkeleton } from "../_components/fc-ui";
import type { Gate } from "./shape";

const MONO: React.CSSProperties = { fontFamily: "var(--font-geist-mono)" };

export function Determinism({ runId, rulesetHash, gates }: { runId: string | undefined; rulesetHash?: string; gates: Gate[] }) {
  const runs = useRuns("all", 10);
  const replay = runs.data?.find((r) => r.parent_run_id === runId && r.status !== "failed");
  const diff = useRunDiff(runId, replay?.run_id);
  const gate = gates.find((g) => g.name.startsWith("determinism"));

  return (
    <FcCard>
      <div className="fc-label mb-3">Same seed, same output</div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 mb-4" style={{ fontSize: 12.5 }}>
        <dt className="fc-faint whitespace-nowrap">Ruleset hash</dt>
        <dd className="fc-num min-w-0 text-right" style={MONO}>{hashShort(rulesetHash, 12)}</dd>
        <dt className="fc-faint whitespace-nowrap">Run</dt>
        <dd className="fc-num min-w-0 text-right" style={MONO}>{runId ? shortId(runId) : "—"}</dd>
        {replay && (
          <>
            <dt className="fc-faint whitespace-nowrap">Replay</dt>
            <dd className="fc-num min-w-0 text-right" style={MONO}>{shortId(replay.run_id)}</dd>
          </>
        )}
      </dl>
      {replay ? (
        diff.isLoading ? (
          <FcSkeleton className="h-8" />
        ) : diff.error ? (
          <FcErrorNote message={errorMessage(diff.error)} />
        ) : diff.data ? (
          <Counts d={diff.data} />
        ) : null
      ) : gate ? (
        <div className="flex items-center gap-3" style={{ fontSize: 13 }}>
          <Tick ok={gate.passed} />
          <span>{gate.actual}</span>
          <span className="fc-faint" style={{ fontSize: 11.5 }}>
            the pipeline ran twice over the corpus and every match, refusal and unmatched id compared
          </span>
        </div>
      ) : (
        <p className="fc-faint" style={{ fontSize: 12.5 }}>No replay of this run yet. Replay it from the Run screen to prove it.</p>
      )}
    </FcCard>
  );
}

function Counts({ d }: { d: DiffOut }) {
  const n = [d.diff.changed.length, d.diff.added.length, d.diff.removed.length];
  const identical = n.every((x) => x === 0);
  return (
    <div className="flex items-center gap-4">
      <Tick ok={identical} />
      <div className="flex items-baseline gap-3">
        {(["changed", "added", "removed"] as const).map((k, i) => (
          <span key={k} className="flex items-baseline gap-1.5">
            <span className="fc-num" style={{ ...MONO, fontSize: 22, color: n[i] === 0 ? "var(--fc-ok)" : "var(--fc-bad)" }}>
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
