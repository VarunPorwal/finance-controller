"use client";

// Run progress: six named stages, live counts while a run plays out, and the
// real committed numbers the moment it lands. The run POST is one long
// synchronous call, so "live" here is a paced storyboard timed to the
// previous run's runtime (see timeline.ts) that snaps to the real result the
// instant it returns — never a fact until that snap. On completion the
// screen routes to Overview, which is where "is my money under control?"
// gets answered from the same run.

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { formatCount, formatDurationMs, shortId } from "../_lib/format";
import type { RunSummary } from "../_lib/api";
import type { Stage } from "../_lib/labels";
import { stageTarget, useTimeline, type StageKey, type StageStatus, type Targets } from "./timeline";

export type RunAction = "demo" | "replay" | "finalize";

export type RunPhase =
  | { kind: "idle" }
  | { kind: "running"; action: RunAction }
  | { kind: "done"; runId: string; action: RunAction }
  | { kind: "error"; message: string };

interface SimpleStage {
  label: string;
  members: StageKey[];
}

const SIMPLE_STAGES: SimpleStage[] = [
  { label: "Normalising", members: ["ingest"] },
  { label: "Scoping", members: ["block"] },
  { label: "Exact reference", members: ["exact_ref"] },
  { label: "Grouping", members: ["fee_adjusted", "date_shift", "many_to_one", "fuzzy"] },
  { label: "Rules", members: ["rule"] },
  { label: "Classify", members: ["classify"] },
];

function combinedStatus(members: StageKey[], status: Record<StageKey, StageStatus>): StageStatus {
  const statuses = members.map((k) => status[k]);
  if (statuses.every((s) => s === "done")) return "done";
  if (statuses.some((s) => s === "active")) return "active";
  if (statuses.every((s) => s === "idle")) return "idle";
  return "pending";
}

function StageChip({ label, status, value }: { label: string; status: StageStatus; value: number | null }) {
  const dotColor =
    status === "done" ? "var(--fc-ok)" : status === "active" ? "var(--fc-accent)" : "var(--fc-text-3)";
  return (
    <div
      className={`fc-card fc-card--flat relative flex flex-col gap-1.5 p-3 ${status === "active" ? "fc-pipe-chip--active" : ""} ${status === "done" ? "fc-pipe-chip--done" : ""}`}
      style={{
        opacity: status === "idle" || status === "pending" ? 0.55 : 1,
        transition: "opacity 0.4s ease, border-color 0.4s ease, box-shadow 0.4s ease",
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="fc-label">{label}</span>
        <span
          className={status === "active" ? "fc-dot fc-pipe-dot-active" : "fc-dot"}
          style={{ background: dotColor, transition: "background 0.3s ease" }}
        />
      </div>
      <span className="fc-metric-val fc-num">{value === null ? "—" : formatCount(Math.round(value))}</span>
    </div>
  );
}

export function Pipeline({
  phase,
  baseline,
  baselineIsReal,
  baselineRunId,
  durationMs,
  result,
  resultByStage,
}: {
  phase: RunPhase;
  baseline: Targets;
  baselineIsReal: boolean;
  baselineRunId?: string;
  durationMs: number;
  result: RunSummary | null | undefined;
  resultByStage: Record<Stage, number> | null;
}) {
  const running = phase.kind === "running";
  const done = phase.kind === "done";
  const router = useRouter();
  const timeline = useTimeline(running, durationMs, baseline);

  const finalTargets: Targets | null = useMemo(() => {
    if (!result) return null;
    return {
      rows: result.event_count,
      bySource: baseline.bySource,
      byStage: resultByStage ?? baseline.byStage,
      matches: result.match_count,
      exceptions: result.exception_count,
      clusters: result.cluster_count,
    };
  }, [result, resultByStage, baseline]);

  const [redirecting, setRedirecting] = useState(false);
  useEffect(() => {
    if (done && result) {
      setRedirecting(true);
      const t = window.setTimeout(() => router.push("/overview"), 1600);
      return () => window.clearTimeout(t);
    }
    setRedirecting(false);
  }, [done, result, router]);

  const valueFor = (keys: StageKey[]): number | null => {
    if (running) return keys.reduce((n, k) => n + timeline.counters[k], 0);
    if (done) {
      if (!finalTargets) return null;
      return keys.reduce((n, k) => n + stageTarget(k, finalTargets), 0);
    }
    return baselineIsReal ? keys.reduce((n, k) => n + stageTarget(k, baseline), 0) : null;
  };

  const statusFor = (keys: StageKey[]): StageStatus => {
    if (running) return combinedStatus(keys, timeline.status);
    if (done) return "done";
    return "idle";
  };

  const doneStageCount = done
    ? SIMPLE_STAGES.length
    : SIMPLE_STAGES.filter((s) => statusFor(s.members) === "done").length +
      SIMPLE_STAGES.filter((s) => statusFor(s.members) === "active").length * 0.5;

  const stateLabel = running ? (
    <span className="fc-chip" style={{ color: "var(--fc-warn)" }}>{phase.action === "replay" ? "Replaying" : "Reconciling"}</span>
  ) : done ? (
    <span className="fc-chip" style={{ color: "var(--fc-ok)" }}>Complete · run·{shortId(phase.runId)}</span>
  ) : baselineRunId ? (
    <span className="fc-chip">Last run · run·{shortId(baselineRunId)}</span>
  ) : (
    <span className="fc-chip">No run yet</span>
  );

  return (
    <div className="fc-card fc-card--hero flex flex-col gap-3">
      <div className="fc-card-title">
        <span>Run progress</span>
        {stateLabel}
      </div>
      <p className="fc-body" style={{ margin: 0 }}>
        {running
          ? "Stages light as they run; figures appear when the run commits."
          : "Counts from the committed run."}
      </p>

      <div className="relative">
        <div className="fc-pipe-track">
          <div
            className="fc-pipe-track-fill"
            style={{ transform: `scaleX(${doneStageCount / SIMPLE_STAGES.length})` }}
          />
          <div className={running ? "fc-pipe-runner" : "fc-pipe-runner fc-pipe-runner--idle"} />
          <div className={running ? "fc-pipe-runner fc-pipe-runner--trail" : "fc-pipe-runner fc-pipe-runner--idle fc-pipe-runner--trail"} />
        </div>
        <div className="relative grid grid-cols-6 gap-2.5">
          {SIMPLE_STAGES.map((s) => (
            <StageChip key={s.label} label={s.label} status={statusFor(s.members)} value={valueFor(s.members)} />
          ))}
        </div>
      </div>

      {done && result && (
        <div className="fc-card mt-1 flex items-center gap-4" style={{ padding: "12px 17px" }}>
          {(
            [
              { label: "Rows", value: formatCount(result.event_count) },
              { label: "Matched", value: formatCount(result.match_count) },
              { label: "Open", value: formatCount(result.exception_count) },
              ...(result.run.runtime_ms != null ? [{ label: "Runtime", value: formatDurationMs(result.run.runtime_ms) }] : []),
            ] as const
          ).map((it, i) => (
            <div
              key={it.label}
              className="flex min-w-0 flex-col justify-center"
              style={{ flex: 1, borderLeft: i > 0 ? "1px solid var(--fc-divider)" : undefined, paddingLeft: i > 0 ? 20 : 0 }}
            >
              <span className="fc-label" style={{ fontSize: 11 }}>
                {it.label}
              </span>
              <span className="fc-num fc-strong" style={{ fontSize: 18, marginTop: 2 }}>
                {it.value}
              </span>
            </div>
          ))}
          <div className="flex shrink-0 flex-col items-end gap-2">
            <span className="fc-faint" style={{ fontSize: 12 }}>
              {redirecting ? "Routing to Overview…" : "Run complete."}
            </span>
            <button className="fc-btn fc-btn--light inline-flex items-center gap-1.5" onClick={() => router.push("/overview")}>
              Go to Overview <ArrowRight size={13} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
