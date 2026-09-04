"use client";

// One card per rule. The waterfall shows the shape; the evidence line says
// what the rule actually did in this run. Five things only: name, version +
// state, waterfall, evidence line, and (when it never fired) an amber flag.

import type { Rule } from "../_lib/api";
import { formatDateShort, money, plural } from "../_lib/format";
import { FcCard } from "../_components/fc-ui";
import { confidenceText, deductionShort, OriginPill, rateText, StatusPill, type RuleUsage } from "./shared";

const DEDUCTION_COLORS = [
  "var(--fc-accent)",
  "var(--fc-warn)",
  "var(--fc-ok)",
  "var(--fc-bad)",
  "var(--fc-text-2)",
];

function DeductionList({ deductions }: { deductions: Rule["deductions"] }) {
  if (!deductions || deductions.length === 0) {
    return <span className="fc-faint" style={{ fontSize: 12 }}>No deductions</span>;
  }
  return (
    <div className="flex flex-col gap-1">
      {deductions.map((d, i) => {
        const color = DEDUCTION_COLORS[i % DEDUCTION_COLORS.length];
        return (
          <div key={`${d.type}-${i}`} className="flex items-center gap-1.5" style={{ fontSize: 12 }}>
            <span className="fc-dot shrink-0" style={{ background: color }} />
            <span style={{ color }}>{deductionShort(d.type)}</span>
            <span className="fc-faint">{rateText(d.rate)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function RuleCard({ rule, usage, onOpen }: { rule: Rule; usage?: RuleUsage; onOpen: () => void }) {
  return (
    <FcCard className="fc-card-hover flex flex-col" style={{ padding: 0 }}>
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full flex-col gap-3 rounded-[inherit] p-4 text-left"
        aria-label={`Open ${rule.name}`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="fc-strong truncate" style={{ fontSize: 13.5, fontWeight: 500 }}>
              {rule.name}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <span className="fc-chip fc-num">v{rule.version}</span>
            <StatusPill status={rule.status} />
            <OriginPill origin={rule.origin} />
          </div>
        </div>

        <div className="fc-faint fc-num" style={{ fontSize: 12 }}>
          {formatDateShort(rule.effective_from)}
          <span className="mx-1.5">→</span>
          {rule.effective_to ? formatDateShort(rule.effective_to) : "open"}
        </div>

        <DeductionList deductions={rule.deductions} />

        <Evidence usage={usage} />

        <div
          className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t pt-3"
          style={{ fontSize: 12 }}
        >
          <span>
            <span className="fc-faint">Tolerance </span>
            <span className="fc-num fc-strong">
              ±{money(rule.tolerance.absolute_paise, { whole: true })} or {rateText(rule.tolerance.percent)}
            </span>
          </span>
          <span className="flex items-center gap-3">
            <span>
              <span className="fc-faint">Priority </span>
              <span className="fc-num fc-strong">{rule.priority}</span>
            </span>
            <span>
              <span className="fc-faint">Confidence </span>
              <span className="fc-num fc-strong">{confidenceText(rule.effective_confidence)}</span>
            </span>
          </span>
        </div>
      </button>
    </FcCard>
  );
}

export function Evidence({ usage }: { usage?: RuleUsage }) {
  if (!usage || usage.fired === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1" style={{ fontSize: 12 }}>
      <span className="fc-strong">
        Fired {plural(usage.fired, "time")} · explained{" "}
        <span className="fc-num" style={{ color: "var(--fc-ok)" }}>
          {money(usage.explained)}
        </span>
      </span>
      {usage.largestResidual > 0 && (
        <span>
          <span className="fc-faint">Largest residual </span>
          <span className="fc-num" style={{ color: "var(--fc-warn)" }}>
            {money(usage.largestResidual)}
          </span>
        </span>
      )}
    </div>
  );
}
