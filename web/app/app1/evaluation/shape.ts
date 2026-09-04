// The eval endpoints ship gates, failures, curve points and confusion cells
// as loosely typed JSON. These narrow them once so the screens stay typed.

import type { EvalResult } from "../_lib/api";

export type Rec = Record<string, unknown>;

export function isRec(v: unknown): v is Rec {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function num(v: unknown): number | null {
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export function str(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  return typeof v === "string" ? v : String(v);
}

export interface Gate {
  name: string;
  passed: boolean;
  actual: string;
  threshold: string;
}

export function gatesOf(ev: EvalResult | null | undefined): Gate[] {
  return (ev?.gates ?? []).filter(isRec).map((g) => ({
    name: str(g.name) ?? "",
    passed: g.passed === true,
    actual: str(g.actual) ?? "—",
    threshold: str(g.threshold) ?? "",
  }));
}

export const GATE_LABEL: Record<string, string> = {
  false_auto_resolutions: "False auto-resolutions",
  never_auto_after_pipeline: "Never-auto categories kept out of auto-close",
  recall: "Recall",
  "determinism (same seed, same output)": "Determinism, same seed twice",
};

export function gateLabel(name: string): string {
  return GATE_LABEL[name] ?? name.replace(/_/g, " ");
}

export interface Failure {
  kind: string;
  event_ids: string[];
  amount_paise: number;
  gt_label: string | null;
  our_label: string;
  why: string;
}

export function failuresOf(ev: EvalResult | null | undefined): Failure[] {
  return (ev?.failures ?? []).filter(isRec).map((f) => ({
    kind: str(f.kind) ?? "unknown",
    event_ids: Array.isArray(f.event_ids) ? f.event_ids.map((x) => String(x)) : [],
    amount_paise: num(f.amount_paise) ?? 0,
    gt_label: str(f.gt_label),
    our_label: str(f.our_label) ?? "",
    why: str(f.why) ?? "",
  }));
}

export interface CurvePoint {
  threshold: number;
  label: string;
  coverage: number;
  precision: number;
  abstentions: number;
  false_positives: number;
}

export function curveOf(points: Rec[] | undefined | null): CurvePoint[] {
  return (points ?? [])
    .filter(isRec)
    .map((p) => {
      const t = num(p.threshold);
      return t === null
        ? null
        : {
            threshold: t,
            label: thresholdText(t),
            coverage: num(p.coverage) ?? 0,
            precision: num(p.precision) ?? 0,
            abstentions: num(p.abstentions) ?? 0,
            false_positives: num(p.false_positives) ?? 0,
          };
    })
    .filter((p): p is CurvePoint => p !== null)
    .sort((a, b) => a.threshold - b.threshold);
}

export function thresholdText(t: string | number): string {
  const n = typeof t === "number" ? t : Number(t);
  return Number.isNaN(n) ? String(t) : n.toFixed(2);
}

export function nearest(points: CurvePoint[], threshold: number): CurvePoint | null {
  let best: CurvePoint | null = null;
  for (const p of points) {
    if (!best || Math.abs(p.threshold - threshold) < Math.abs(best.threshold - threshold)) best = p;
  }
  return best;
}
