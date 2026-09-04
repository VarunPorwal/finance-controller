"use client";

import { Check, X } from "lucide-react";
import { clsx } from "clsx";
import type { EvalResult } from "../_lib/api";
import { pct } from "../_lib/format";
import { FcCard, WhyLabel, WhyWrap } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";
import { gateLabel, gatesOf, thresholdText, type Gate } from "./shape";

const MONO: React.CSSProperties = { fontFamily: "var(--font-geist-mono)" };

function numOrNull(v: string | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

function Stat({
  label,
  value,
  digits = 2,
  raw,
  sub,
  tone,
  why,
}: {
  label: string;
  value?: number | null;
  digits?: number;
  raw?: string;
  sub?: string;
  tone?: "ok";
  why?: string;
}) {
  const valueEl = (
    <span
      className={clsx("fc-metric-val fc-num", why && "fc-why-figure")}
      style={{ ...MONO, ...(tone === "ok" ? { color: "var(--fc-ok)" } : undefined) }}
    >
      {raw !== undefined ? raw : value === null || value === undefined ? "—" : <CountUp value={value} format={(n) => pct(n, digits)} />}
    </span>
  );
  return (
    <div className="flex flex-col gap-1">
      <div className="fc-label">{label}</div>
      {why ? (
        <WhyWrap>
          {valueEl}
          <WhyLabel href={why} />
        </WhyWrap>
      ) : (
        valueEl
      )}
      {sub && <div className="fc-label">{sub}</div>}
    </div>
  );
}

export function Headline({ ev }: { ev: EvalResult }) {
  const gates = gatesOf(ev);
  const recallGate = gates.find((g) => g.name === "recall");
  const clean = ev.false_auto_resolutions === 0;

  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(300px,2fr)_3fr]">
      <FcCard variant="hero" className="flex flex-col justify-between">
        <div className="fc-label">False auto-resolutions</div>
        <div style={{ margin: "16px 0" }}>
          <WhyWrap>
            <span className="fc-why-figure" style={{ color: clean ? "var(--fc-ok)" : "var(--fc-bad)" }}>
              <CountUp value={ev.false_auto_resolutions} className="fc-hero-num fc-num" format={(n) => String(Math.round(n))} />
            </span>
            <WhyLabel href="#fc-eval-failures" />
          </WhyWrap>
          <div className="fc-body mt-3" style={{ maxWidth: 320 }}>
            Items it closed on its own that ground truth says were wrong. This is the number that blocks a merge.
          </div>
        </div>
        <div className="fc-faint flex items-center justify-between" style={{ fontSize: 11.5 }}>
          <span>
            {ev.true_positive.toLocaleString("en-IN")} pairs right · {ev.false_positive} wrong ·{" "}
            {ev.false_negative} missed
          </span>
          <span className="fc-num" style={MONO}>threshold {thresholdText(ev.auto_threshold)}</span>
        </div>
      </FcCard>

      <div className="flex flex-col gap-3">
        <FcCard>
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <Stat
              label="Precision on auto-close"
              value={numOrNull(ev.precision_pct)}
              digits={2}
              tone="ok"
              sub="of what it closed itself"
              why="#fc-eval-confusion"
            />
            <Stat
              label="Recall"
              // The recall gate is the number that actually governs the merge
              // (see Release gates below) — show that one, not ev.recall_pct,
              // so the two never disagree on the same page.
              raw={recallGate?.actual}
              value={recallGate ? undefined : numOrNull(ev.recall_pct)}
              digits={2}
              sub={recallGate ? `needs ${recallGate.threshold}` : "of true pairs found"}
              why="#fc-eval-confusion"
            />
            <Stat label="Abstention rate" value={numOrNull(ev.abstention_pct)} digits={1} sub="by design" why="#fc-eval-confusion" />
            <Stat label="Auto threshold" raw={thresholdText(ev.auto_threshold)} sub="confidence to close alone" />
          </div>
        </FcCard>
        <FcCard>
          <div className="fc-label mb-3">Release gates</div>
          <ul className="flex flex-col gap-2">
            {gates.map((g) => (
              <GateRow key={g.name} gate={g} />
            ))}
            {gates.length === 0 && <li className="fc-faint" style={{ fontSize: 12.5 }}>No gates recorded for this run.</li>}
          </ul>
        </FcCard>
      </div>
    </div>
  );
}

function GateRow({ gate }: { gate: Gate }) {
  return (
    <li className="flex items-center gap-3" style={{ fontSize: 12.5 }}>
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
        style={{
          border: `1px solid color-mix(in srgb, ${gate.passed ? "var(--fc-ok)" : "var(--fc-bad)"} 40%, transparent)`,
          background: `color-mix(in srgb, ${gate.passed ? "var(--fc-ok)" : "var(--fc-bad)"} 14%, transparent)`,
          color: gate.passed ? "var(--fc-ok)" : "var(--fc-bad)",
        }}
      >
        {gate.passed ? <Check size={12} /> : <X size={12} />}
      </span>
      <span className="flex-1">{gateLabel(gate.name)}</span>
      <span className="fc-num" style={{ ...MONO, fontSize: 12, color: gate.passed ? "var(--fc-text-2)" : "var(--fc-bad)" }}>
        {gate.actual}
      </span>
      <span className="fc-faint fc-num" style={{ ...MONO, width: 112, textAlign: "right", fontSize: 11.5 }}>
        needs {gate.threshold}
      </span>
    </li>
  );
}

