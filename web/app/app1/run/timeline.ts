"use client";

// The run POST is synchronous, so the pipeline cannot show real progress.
// This is a paced storyboard: each stage lights in turn over the previous
// run's runtime, counters tick toward the previous run's figures, and the
// page snaps every number to the real result the moment the POST returns.
// Nothing here is a fact until that snap; the screen labels it as such.

import { useEffect, useMemo, useRef, useState } from "react";
import type { Stage } from "../_lib/labels";

export type StageKey =
  | "ingest"
  | "block"
  | "exact_ref"
  | "fee_adjusted"
  | "date_shift"
  | "many_to_one"
  | "fuzzy"
  | "rule"
  | "classify"
  | "cluster"
  | "results";

export interface StageDef {
  key: StageKey;
  label: string;
  unit: string;
  hint: string;
  /** Activation window as a fraction of the whole storyboard. */
  start: number;
  end: number;
  row: 0 | 1;
}

export const STAGES: StageDef[] = [
  { key: "ingest", label: "Ingest", unit: "rows", hint: "Three files parsed into one event stream, amounts in paise.", start: 0, end: 0.14, row: 0 },
  { key: "block", label: "Block", unit: "rows bucketed", hint: "Amount bucket, date window and reference prefix. Nothing decides here.", start: 0.12, end: 0.22, row: 0 },
  { key: "exact_ref", label: "Exact reference", unit: "matched", hint: "UTR, RRN or settlement id agree exactly.", start: 0.2, end: 0.34, row: 0 },
  { key: "fee_adjusted", label: "Fee adjusted", unit: "matched", hint: "Gross less MDR, GST and TDS equals the bank credit within tolerance.", start: 0.32, end: 0.46, row: 0 },
  { key: "date_shift", label: "Date shift", unit: "matched", hint: "Same amount and unique reference completion, T+1 to T+3.", start: 0.44, end: 0.54, row: 0 },
  { key: "many_to_one", label: "Batch", unit: "matched", hint: "Several settlements sum to one bank credit.", start: 0.52, end: 0.6, row: 0 },
  { key: "fuzzy", label: "Fuzzy", unit: "suggested", hint: "Weighted similarity, capped at 0.75. Never closes on its own.", start: 0.58, end: 0.66, row: 1 },
  { key: "rule", label: "Rules", unit: "explained", hint: "Deduction rules shrink the gap the books ask about.", start: 0.64, end: 0.74, row: 1 },
  { key: "classify", label: "Classify", unit: "exceptions", hint: "What is left is named, tiered and ranked.", start: 0.72, end: 0.84, row: 1 },
  { key: "cluster", label: "Cluster", unit: "clusters", hint: "Exceptions with one cause are grouped so one decision covers them.", start: 0.82, end: 0.9, row: 1 },
  { key: "results", label: "Results", unit: "decisions", hint: "Matches with evidence, and a ranked queue for a human.", start: 0.88, end: 1, row: 1 },
];

export const MATCH_STAGES: Stage[] = ["exact_ref", "fee_adjusted", "date_shift", "many_to_one", "fuzzy", "rule"];

export type SourceKey = "razorpay" | "bank" | "ledger";

export interface Targets {
  rows: number;
  bySource: Record<SourceKey, number>;
  byStage: Record<Stage, number>;
  matches: number;
  exceptions: number;
  clusters: number;
}

/** Pacing only. Used when no previous run exists; replaced by the real
 * summary the moment the POST returns. */
export const PACING_FALLBACK: Targets = {
  rows: 1575,
  bySource: { razorpay: 614, bank: 109, ledger: 852 },
  byStage: { exact_ref: 52, fee_adjusted: 24, date_shift: 9, many_to_one: 2, fuzzy: 3, rule: 5 },
  matches: 95,
  exceptions: 39,
  clusters: 8,
};

export function stageTarget(key: StageKey, t: Targets): number {
  switch (key) {
    case "ingest":
    case "block":
      return t.rows;
    case "classify":
    case "results":
      return t.exceptions;
    case "cluster":
      return t.clusters;
    default:
      return t.byStage[key];
  }
}

export type StageStatus = "idle" | "pending" | "active" | "done";

export interface LogEntry {
  id: string;
  text: string;
  tone?: "ok" | "model" | "warn" | "faint";
}

const ease = (x: number) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);

function windowProgress(def: StageDef, p: number): number {
  if (p <= def.start) return 0;
  if (p >= def.end) return 1;
  return ease((p - def.start) / (def.end - def.start));
}

function n(v: number): string {
  return new Intl.NumberFormat("en-IN").format(Math.round(v));
}

/** The storyboard's narration, in order. Every number is the previous run's. */
export function storyboard(t: Targets): { at: number; entry: LogEntry }[] {
  return [
    { at: 0.0, entry: { id: "s0", text: "Run opened. Rule set frozen by hash for this run." } },
    { at: 0.03, entry: { id: "s1", text: `Parsed ${n(t.bySource.razorpay)} Razorpay rows. Amounts already in paise.` } },
    { at: 0.07, entry: { id: "s2", text: `Bank: ${n(t.bySource.bank)} lines, balance continuity verified line by line.`, tone: "ok" } },
    { at: 0.1, entry: { id: "s3", text: `Tally: ${n(t.bySource.ledger)} vouchers, GUID de-duplication applied.` } },
    { at: 0.13, entry: { id: "s4", text: "Narrations scanned for injected instructions.", tone: "faint" } },
    { at: 0.15, entry: { id: "s5", text: "Blocking: amount bucket, date window, reference prefix." } },
    { at: 0.22, entry: { id: "s6", text: "Stage 1: exact UTR, RRN or settlement id. Truncated references excluded." } },
    { at: 0.3, entry: { id: "s7", text: `Stage 1 closed ${n(t.byStage.exact_ref)} groups with evidence.`, tone: "ok" } },
    { at: 0.34, entry: { id: "s8", text: "Stage 2: gross less MDR, GST on MDR, TDS 194-O, within tolerance." } },
    { at: 0.43, entry: { id: "s9", text: `Stage 2 closed ${n(t.byStage.fee_adjusted)} groups. Rounding drift absorbed per transaction.`, tone: "ok" } },
    { at: 0.46, entry: { id: "s10", text: "Stage 3: date shift T+1 to T+3, unique reference completion required." } },
    { at: 0.54, entry: { id: "s11", text: "Stage 4: subset-sum over batch credits. Multiple valid subsets return nothing." } },
    { at: 0.6, entry: { id: "s12", text: "Stage 5: fuzzy similarity, capped at 0.75. Suggests, never closes.", tone: "warn" } },
    { at: 0.66, entry: { id: "s13", text: "Rulebook applied to the gap the books ask about. Each rule shrinks it, none passes or fails." } },
    { at: 0.74, entry: { id: "s14", text: "Classifying what is left. Five categories never auto-close." } },
    { at: 0.8, entry: { id: "s15", text: `${n(t.exceptions)} exceptions named and tiered.` } },
    { at: 0.84, entry: { id: "s16", text: "Clustering by cause so one decision covers many." } },
    { at: 0.9, entry: { id: "s17", text: "Model: narrative and cluster labels requested. Never decides.", tone: "model" } },
    { at: 0.95, entry: { id: "s18", text: "Audit hash chain extended. Waiting for the run to commit.", tone: "faint" } },
  ];
}

export interface TimelineState {
  progress: number;
  status: Record<StageKey, StageStatus>;
  counters: Record<StageKey, number>;
  pool: number;
  log: LogEntry[];
}

export function useTimeline(running: boolean, durationMs: number, targets: Targets): TimelineState {
  const [elapsed, setElapsed] = useState(0);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (!running) {
      startRef.current = null;
      setElapsed(0);
      return;
    }
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      if (startRef.current === null) startRef.current = now;
      if (now - last >= 66) {
        last = now;
        setElapsed(now - startRef.current);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [running]);

  const lines = useMemo(() => storyboard(targets), [targets]);

  return useMemo(() => {
    const p = running ? Math.min(1, elapsed / Math.max(1000, durationMs)) : 0;
    const status = {} as Record<StageKey, StageStatus>;
    const counters = {} as Record<StageKey, number>;
    for (const def of STAGES) {
      const w = windowProgress(def, p);
      counters[def.key] = stageTarget(def.key, targets) * w;
      if (!running) status[def.key] = "idle";
      else if (def.key === "results") status[def.key] = p >= def.start ? "active" : "pending";
      else status[def.key] = w >= 1 ? "done" : w > 0 ? "active" : "pending";
    }
    const drainStart = 0.2;
    const drainEnd = 0.84;
    const drain = p <= drainStart ? 0 : ease((p - drainStart) / (drainEnd - drainStart));
    const pool = running ? targets.rows - (targets.rows - targets.exceptions) * drain : targets.exceptions;
    const log = running ? lines.filter((l) => l.at <= p).map((l) => l.entry) : [];
    return { progress: p, status, counters, pool, log };
  }, [running, elapsed, durationMs, targets, lines]);
}

export function clampDuration(runtimeMs: number | null | undefined): number {
  if (!runtimeMs) return 7000;
  return Math.min(15000, Math.max(5000, runtimeMs));
}
