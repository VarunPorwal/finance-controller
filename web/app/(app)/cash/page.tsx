"use client";

// Cash. The one question: where is my money, and will I have enough? Reskinned
// to the Finco design system (`finco-tokens.css`, `.fc` scope, applied by the
// shell). Every figure below reads an existing server field off the cash
// bridge — nothing here derives a financial number (CLAUDE.md hard rules 1, 5).
//
// Not on this page: a cash-flow projection (balance today / expected in or out
// over 7 days) — no field in CashBridgeOut backs it, so it is omitted rather
// than invented. TDS 194-O and TCS recoverable totals are omitted for the same
// reason; only GST input credit is a real field.

import type { CSSProperties } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { ErrorNote } from "../_components/ui";
import { WhyLabel, WhyWrap } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";
import { useCurrentRun, useCashBridge, useExceptions, errorMessage } from "../_lib/api";
import { money, shortId, formatDateTime } from "../_lib/format";
import { Waterfall, WaterfallTable } from "./waterfall";
import { Fees } from "./fees";
import { Lanes, Buckets } from "./stuck";
import { HeldAndAtRisk, UnidentifiedAndRecoverable } from "./risk";

function skel(className: string) {
  return <div className={`fc-card fc-card--flat animate-pulse ${className}`} style={{ background: "var(--fc-divider)" }} />;
}

function CashHeader({ run }: { run: ReturnType<typeof useCurrentRun>["run"] }) {
  return (
    <div className="mb-3">
      <h1 className="fc-title">
        Cash
        {run && (
          <span className="fc-faint" style={{ fontSize: 15, marginLeft: 10 }}>
            · Run #{shortId(run.run_id)} · {formatDateTime(run.started_at)}
          </span>
        )}
      </h1>
    </div>
  );
}

// The four headline figures as a single compact strip, not four separate
// cards: they set up the bridge chart directly below them, so they read as
// its summary line rather than as competing metrics. Each is a computed
// aggregate (sums and a subtraction over this run's events), so each carries
// a Why? that scrolls to the segment-by-segment breakdown beneath the chart.
function CompactStrip({ bridge }: { bridge: NonNullable<ReturnType<typeof useCashBridge>["data"]> }) {
  const goToBridge = () => document.getElementById("bridge-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
  const unexplainedSeg = bridge.segments.find((s) => s.label === "Unexplained");
  const gapHref = unexplainedSeg?.exception_ids[0] ? `/decisions?open=${unexplainedSeg.exception_ids[0]}` : undefined;

  const items: {
    key: string;
    label: string;
    paise: number;
    tone?: string;
    href?: string;
  }[] = [
    { key: "gross", label: "Collected", paise: bridge.gross_collected_paise },
    { key: "expected", label: "Expected net", paise: bridge.expected_net_paise },
    { key: "actual", label: "Actual bank", paise: bridge.actual_bank_paise, tone: "var(--fc-accent)" },
    {
      key: "gap",
      label: "Gap",
      paise: bridge.unexplained_paise,
      tone: bridge.unexplained_paise > 0 ? "var(--fc-bad)" : "var(--fc-ok)",
      href: gapHref,
    },
  ];

  return (
    <div className="fc-card mb-3" style={{ display: "flex", flexWrap: "wrap", rowGap: 12, padding: "12px 17px", minHeight: 52 }}>
      {items.map((it, i) => (
        <div
          key={it.key}
          className="flex min-w-0 flex-col justify-center"
          style={{
            flex: "1 1 150px",
            borderLeft: i > 0 ? "1px solid var(--fc-divider)" : undefined,
            paddingLeft: i > 0 ? 20 : 0,
            paddingRight: 20,
          }}
        >
          <span className="fc-label" style={{ fontSize: 11 }}>
            {it.label}
          </span>
          <WhyWrap>
            <span className="fc-why-figure fc-num font-mono" style={{ fontSize: 18, fontWeight: 500, color: it.tone ?? "var(--fc-text)" }}>
              <CountUp value={it.paise} format={(n) => money(Math.round(n), { whole: true })} duration={0.9} />
            </span>
            {it.href ? <WhyLabel href={it.href} /> : <WhyLabel onClick={goToBridge} />}
          </WhyWrap>
        </div>
      ))}
    </div>
  );
}

export default function CashPage() {
  const { run, runId, loading: runLoading, error: runError } = useCurrentRun();
  const bridge = useCashBridge(runId);
  const exceptions = useExceptions(runId);

  const error = runError ?? bridge.error ?? exceptions.error;
  const loading = runLoading || bridge.isLoading || exceptions.isLoading;
  const b = bridge.data;
  const xs = exceptions.data ?? [];
  const asOf = run?.finished_at ?? run?.started_at ?? new Date().toISOString();

  return (
    <div style={{ minHeight: "100%", padding: "20px 26px 40px", "--fc-warn": "#3b93ce" } as CSSProperties}>
      <CashHeader run={run} />

      {error && (
        <div className="mb-3">
          <ErrorNote message={errorMessage(error)} />
        </div>
      )}

      {!runId && !runLoading && !error && (
        <div className="fc-card">
          <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
            <div style={{ fontSize: 14 }}>No run to bridge</div>
            <div className="fc-faint" style={{ fontSize: 12.5, maxWidth: 380 }}>
              Ingest the three files and run a reconciliation. The bridge is built from that run&apos;s settlements and bank
              credits.
            </div>
            <Link href="/run" className="fc-btn mt-3 inline-flex items-center gap-1.5">
              Go to Run <ArrowRight size={13} />
            </Link>
          </div>
        </div>
      )}

      {runId && loading && !b && (
        <div className="flex flex-col gap-3">
          {skel("h-12 w-full")}
          {skel("h-80 w-full")}
          <div className="fc-split">
            {skel("h-64 w-full")}
            {skel("h-64 w-full")}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {skel("h-40 w-full")}
            {skel("h-40 w-full")}
          </div>
          {skel("h-32 w-full")}
        </div>
      )}

      {b && (
        <>
          <CompactStrip bridge={b} />

          {/* Plain card, not fc-card--hero: it holds WaterfallTable, and a
              gradient card must never contain a table (§18). */}
          <div id="bridge-detail" className="fc-card mb-3">
            <div className="fc-card-title mb-1">The bridge</div>
            <div className="fc-faint mb-2" style={{ fontSize: 12 }}>
              Gross collected, down to what the bank received. Hover a step for the figures; click one to open its decision.
            </div>
            <Waterfall bridge={b} />
            <div style={{ borderTop: "1px solid var(--fc-divider)", marginTop: 8 }}>
              <WaterfallTable bridge={b} />
            </div>
          </div>

          <div className="fc-split mb-3" style={{ alignItems: "stretch" }}>
            <Fees bridge={b} exceptions={xs} />
            <HeldAndAtRisk bridge={b} asOf={asOf} />
          </div>

          <div className="mb-2">
            <div className="fc-card-title" style={{ fontSize: 16 }}>
              Money stuck
            </div>
            <div className="fc-faint mt-0.5" style={{ fontSize: 12 }}>
              By the rail it moved on, and by what a person has to do about it.
            </div>
          </div>
          <div className="mb-3" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, alignItems: "stretch" }}>
            <Lanes bridge={b} />
            <Buckets exceptions={xs} />
          </div>

          <UnidentifiedAndRecoverable bridge={b} />
        </>
      )}
    </div>
  );
}
