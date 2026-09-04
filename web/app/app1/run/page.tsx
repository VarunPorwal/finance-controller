"use client";

// Run. "Did it read my evidence correctly?" Reskinned to the Finco design
// system (finco-tokens.css, `.fc` scope) — see `page.tsx` and
// `_overview-fc/blocks.tsx` on Overview for the reference pass.
//
// The demo corpus and replay buttons are long synchronous POSTs, so the page
// enters running mode and lets the pipeline storyboard play until the
// response lands, then snaps to the real summary and routes to Overview.

import type { CSSProperties } from "react";
import { useCallback, useMemo, useState } from "react";
import { Play, RotateCcw } from "lucide-react";
import { ErrorNote } from "../_components/ui";
import {
  errorMessage,
  useCurrentRun,
  useEventsCount,
  useFiles,
  useMatches,
  useRuleSets,
  useRuns,
  useRunSummary,
  writes,
  type MatchResult,
} from "../_lib/api";
import type { Stage } from "../_lib/labels";
import { formatCount } from "../_lib/format";
import { fieldStyle, SectionHead } from "./_shared";
import { Pipeline, type RunAction, type RunPhase } from "./pipeline";
import { SourceCards, latestFiles } from "./sources";
import { UploadPanel, type Uploads, type UploadSlot } from "./upload";
import { Findings } from "./findings";
import { RunHistory } from "./history";
import { clampDuration, MATCH_STAGES, PACING_FALLBACK, type SourceKey, type Targets } from "./timeline";

const DEFAULT_RULE_SET = "demo-corpus";

function countByStage(matches: MatchResult[] | undefined): Record<Stage, number> | null {
  if (!matches) return null;
  const out = Object.fromEntries(MATCH_STAGES.map((s) => [s, 0])) as Record<Stage, number>;
  for (const m of matches) out[m.stage] = (out[m.stage] ?? 0) + 1;
  return out;
}

function FunnelStep({ label, value, of }: { label: string; value: number | undefined; of: number | undefined }) {
  const frac = value !== undefined && of ? Math.min(1, value / of) : 0;
  return (
    <div>
      <div className="fc-k-top">
        <span>{label}</span>
        <span className="fc-num fc-strong">{value === undefined ? "—" : formatCount(value)}</span>
      </div>
      <div className="fc-bar">
        <span style={{ width: `${(frac * 100).toFixed(1)}%` }} />
      </div>
    </div>
  );
}

export default function RunPage() {
  const { run, summary, runId, loading: runLoading, refresh } = useCurrentRun();
  const ruleSets = useRuleSets();
  const files = useFiles();
  const counts = useEventsCount(runId);
  const baselineMatches = useMatches(runId);

  const [kind, setKind] = useState<"all" | "original" | "replay">("all");
  const runs = useRuns(kind, 50);

  const [ruleSet, setRuleSet] = useState(DEFAULT_RULE_SET);
  const [phase, setPhase] = useState<RunPhase>({ kind: "idle" });
  const [uploads, setUploads] = useState<Uploads>({});
  const [pendingRunId, setPendingRunId] = useState<string | null>(null);

  const doneRunId = phase.kind === "done" ? phase.runId : undefined;
  const result = useRunSummary(doneRunId);
  const resultMatches = useMatches(doneRunId);
  const resultCounts = useEventsCount(doneRunId);

  const baseline: Targets = useMemo(() => {
    if (!summary) return PACING_FALLBACK;
    const by = counts.data?.by_source ?? {};
    return {
      rows: summary.event_count,
      bySource: {
        razorpay: by.razorpay ?? 0,
        bank: by.bank ?? 0,
        ledger: by.ledger ?? 0,
      },
      byStage: countByStage(baselineMatches.data) ?? PACING_FALLBACK.byStage,
      matches: summary.match_count,
      exceptions: summary.exception_count,
      clusters: summary.cluster_count,
    };
  }, [summary, counts.data, baselineMatches.data]);

  const durationMs = clampDuration(run?.runtime_ms);
  const running = phase.kind === "running";

  const launch = useCallback(
    async (action: RunAction, target?: string) => {
      setPhase({ kind: "running", action });
      const startedAt = performance.now();
      let newId: string | null = null;
      let message: string | null = null;
      if (action === "demo") {
        const res = await writes.createRun({ mode: "demo", seed: 7, rule_set: ruleSet, label: null });
        if (res.error || !res.data) message = errorMessage(res.error);
        else newId = res.data.run_id;
      } else if (action === "replay") {
        if (!target) message = "There is no run to replay yet.";
        else {
          const res = await writes.replayRun(target, { reason: "Replay from the Run screen", seed: 8 });
          if (res.error || !res.data) message = errorMessage(res.error);
          else newId = res.data.new_run_id;
        }
      } else {
        if (!target) message = "No open run to finalise.";
        else {
          const res = await writes.finalizeRun(target);
          if (res.error || !res.data) message = errorMessage(res.error);
          else newId = res.data.run_id;
        }
      }
      if (!newId) {
        setPhase({ kind: "error", message: message ?? "The run did not complete." });
        return;
      }
      // The pipeline storyboard is paced to `durationMs` so the six stages can be
      // seen lighting up in turn; a fast backend response must not cut that short,
      // or the running state (and its live animation) flashes for a fraction of a
      // second and never actually reads as "live".
      const remaining = durationMs - (performance.now() - startedAt);
      if (remaining > 0) await new Promise((r) => setTimeout(r, remaining));
      if (action === "finalize") setPendingRunId(null);
      refresh();
      setPhase({ kind: "done", runId: newId, action });
    },
    [ruleSet, refresh, durationMs],
  );

  const onSlot = useCallback((source: SourceKey, slot: UploadSlot) => {
    setUploads((u) => ({ ...u, [source]: slot }));
  }, []);

  const activeRunId = doneRunId ?? runId;
  const activeSummary = result.data ?? summary;
  const haveRun = !!activeRunId;

  return (
    <div style={{ minHeight: "100%", padding: "20px 26px 40px", "--fc-warn": "#3b93ce" } as CSSProperties}>
      <div className="fc-head mb-3">
        <div>
          <h1 className="fc-title">Run</h1>
          <p className="fc-sub" style={{ margin: "6px 0 0" }}>
            Did it read my evidence correctly? Any slot may be empty — reconciling reads whatever was provided.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={ruleSet}
            onChange={(e) => setRuleSet(e.target.value)}
            disabled={running}
            aria-label="Rule set"
            style={fieldStyle}
          >
            {(ruleSets.data ?? []).some((s) => s.name === ruleSet) ? null : <option value={ruleSet}>{ruleSet}</option>}
            {(ruleSets.data ?? []).map((s) => (
              <option key={s.name} value={s.name}>
                {s.name} · {s.active_rule_count} active
              </option>
            ))}
          </select>
          <button
            className="fc-btn fc-btn--ghost inline-flex items-center gap-1.5"
            disabled={running || !runId}
            onClick={() => void launch("replay", runId)}
            title="Re-run the current run's inputs with the rule set as it stands now."
          >
            <RotateCcw size={13} />
            Replay current run
          </button>
          <button
            className="fc-btn fc-btn--ghost inline-flex items-center gap-1.5"
            disabled={running}
            onClick={() => void launch("demo")}
          >
            <Play size={13} />
            {running && phase.action === "demo" ? "Running…" : "Run the demo corpus"}
          </button>
        </div>
      </div>

      {phase.kind === "error" && (
        <div className="mb-3">
          <ErrorNote message={phase.message} />
        </div>
      )}

      <div className="mb-3">
        <UploadPanel
          ruleSet={ruleSet}
          pendingRunId={pendingRunId}
          onRunOpened={setPendingRunId}
          uploads={uploads}
          onSlot={onSlot}
          onFinalize={(id) => void launch("finalize", id)}
          busy={running}
        />
      </div>

      <div className="mb-3">
        <Pipeline
          phase={phase}
          baseline={baseline}
          baselineIsReal={!!summary}
          baselineRunId={runId}
          durationMs={durationMs}
          result={result.data}
          resultByStage={countByStage(resultMatches.data)}
        />
      </div>

      {haveRun && (
        <>
          <div className="mb-3">
            <SectionHead title="Sources" sub="What was read, and how much of it is in scope for this run." />
            <SourceCards
              files={latestFiles(files.data)}
              counts={(doneRunId ? resultCounts.data : counts.data)?.by_source}
              loading={runLoading || files.isLoading}
              bankSlot={uploads.bank}
            />
          </div>

          <div className="mb-3">
            <SectionHead title="Findings" sub="What ingestion refused, and the guards it ran before anything matched." />
            <Findings uploads={uploads} />
          </div>

          <div className="mb-3">
            <SectionHead title="Pipeline funnel" sub="Simplified: what came in, what matched, what is still open." />
            <div className="fc-card grid grid-cols-3 gap-4" style={{ padding: "14px 16px" }}>
              <FunnelStep label="Ingested" value={activeSummary?.event_count} of={activeSummary?.event_count} />
              <FunnelStep label="Matched" value={activeSummary?.match_count} of={activeSummary?.event_count} />
              <FunnelStep label="Open" value={activeSummary?.exception_count} of={activeSummary?.event_count} />
            </div>
          </div>

          <div>
            <SectionHead title="History" />
            <RunHistory
              runs={runs.data}
              loading={runs.isLoading}
              error={runs.error ? errorMessage(runs.error) : null}
              currentRunId={activeRunId}
              kind={kind}
              onKind={setKind}
            />
          </div>
        </>
      )}

      {!haveRun && !running && (
        <div className="fc-faint" style={{ fontSize: 13 }}>
          {runLoading ? "Loading…" : "No run yet. Upload files above or run the demo corpus."}
        </div>
      )}
    </div>
  );
}
