"use client";

// The back-test panel. Three rows, then the recommendation. Wrongly-closed
// items are flagged red and link to the decision they would have shut.

import Link from "next/link";
import { clsx } from "clsx";
import type { Backtest } from "../_lib/api";
import { pct, plural, shortId, hashShort } from "../_lib/format";
import { FcChip, FcMoney, type FcTone } from "../_components/fc-ui";

const RECO: Record<string, { label: string; tone: FcTone; blurb: string }> = {
  activate: { label: "Activate", tone: "ok", blurb: "Explains what it touches and closes nothing it should not." },
  adjust: { label: "Adjust", tone: "warn", blurb: "Explains some of what it touches. Tighten the scope or the rate first." },
  discard: { label: "Discard", tone: "bad", blurb: "Would close items it cannot explain, or touches nothing." },
};

export function BacktestResult({ result, className }: { result: Backtest; className?: string }) {
  const reco = RECO[result.net_recommendation] ?? {
    label: result.net_recommendation,
    tone: "neutral" as FcTone,
    blurb: "",
  };
  const wrong = result.would_wrongly_close;
  return (
    <div className={clsx("flex flex-col gap-4", className)}>
      <div className="fc-card fc-card--flat" style={{ padding: 0 }}>
        <Row
          label="Would have explained"
          count={plural(result.would_explain.count, "exception")}
          paise={result.would_explain.total_paise}
          tone={result.would_explain.count > 0 ? "ok" : "neutral"}
        />
        <Row
          label="Would have wrongly closed"
          count={plural(wrong.count, "item")}
          paise={wrong.total_paise}
          tone={wrong.count > 0 ? "bad" : "neutral"}
          chips={wrong.exception_ids}
        />
        <Row label="Would have partially explained" count={`${result.would_partially_explain.count} more`} last />
      </div>

      <div className="flex items-center gap-4">
        <FcChip tone={reco.tone} className="fc-strong">
          {reco.label}
        </FcChip>
        <span className="fc-muted" style={{ fontSize: 12.5 }}>
          {reco.blurb}
        </span>
      </div>

      <div className="fc-ev-rule">
        <KV label="Precision on what it touched" value={pct(result.precision_pct)} />
        <KV label="Coverage of cases considered" value={pct(result.coverage_pct)} />
        <KV label="Cases considered" value={String(result.cases_considered)} />
        <KV
          label="Explained but unverified"
          value={String(result.unverified)}
          tone={result.unverified > 0 ? "var(--fc-warn)" : undefined}
        />
        <KV label="Version hash" value={hashShort(result.version_hash, 12)} mono last />
      </div>
    </div>
  );
}

function KV({ label, value, tone, mono, last }: { label: string; value: string; tone?: string; mono?: boolean; last?: boolean }) {
  return (
    <div className={clsx("fc-kv", last && "fc-kv--total")}>
      <span>{label}</span>
      <span className={clsx("fc-num", mono && "fc-faint")} style={tone ? { color: tone } : undefined}>
        {value}
      </span>
    </div>
  );
}

function Row({
  label,
  count,
  paise,
  tone = "neutral",
  chips,
  last,
}: {
  label: string;
  count: string;
  paise?: number;
  tone?: FcTone;
  chips?: string[];
  last?: boolean;
}) {
  const color = tone === "ok" ? "var(--fc-ok)" : tone === "bad" ? "var(--fc-bad)" : "var(--fc-text)";
  return (
    <div className={clsx("px-4 py-3", !last && "border-b")}>
      <div className="grid grid-cols-[1fr_auto_auto] items-baseline gap-x-6">
        <span className="fc-muted" style={{ fontSize: 12.5 }}>
          {label}
        </span>
        <span className="fc-num" style={{ fontSize: 13, fontWeight: 500, color }}>
          {count}
        </span>
        <span className="fc-num" style={{ width: 96, textAlign: "right" }}>
          {paise !== undefined ? <FcMoney paise={paise} compact tone={tone === "bad" ? "bad" : "neutral"} /> : null}
        </span>
      </div>
      {chips && chips.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {chips.map((id) => (
            <Link key={id} href={`/decisions?open=${encodeURIComponent(id)}`} title={id}>
              <FcChip tone="bad" className="fc-num">
                {shortId(id)}
              </FcChip>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export function BacktestSkeleton() {
  return (
    <div className="fc-card fc-card--flat flex flex-col gap-3 p-4">
      <div className="animate-pulse" style={{ background: "var(--fc-divider)", borderRadius: 6, height: 14, width: "75%" }} />
      <div className="animate-pulse" style={{ background: "var(--fc-divider)", borderRadius: 6, height: 14, width: "65%" }} />
      <div className="animate-pulse" style={{ background: "var(--fc-divider)", borderRadius: 6, height: 14, width: "50%" }} />
    </div>
  );
}
