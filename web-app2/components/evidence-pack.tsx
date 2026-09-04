"use client";

import { Fragment } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { formatDecimalPercent, formatPaise, humanizeSnakeCase, shortId } from "@/lib/format";
import { TIER_LABEL, TIER_SHORT, TIER_TEXT, TIER_TONE } from "@/lib/tier";
import { InstructionBox } from "@/components/instruction-box";
import { Pill } from "@/components/ui/pill";
import { Skeleton } from "@/components/ui/skeleton";
import { SourceDot } from "@/components/ui/source-glyph";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";

type Evidence = components["schemas"]["ExceptionEvidenceOut"];

/**
 * The proof. Stages attempted, fields agreed and disagreed, the confidence
 * derivation, rules considered, the raw rows. Rendered as a monospace tree
 * because that is what a finance reviewer can read and re-derive by hand.
 */
export function EvidencePack({ exceptionId, onApplied }: { exceptionId: string; onApplied: () => void }) {
  const { data: evidence, error } = useQuery({
    queryKey: queryKeys.exceptionEvidence(exceptionId),
    queryFn: async () => {
      const { data, error: e } = await apiClient.GET("/api/v1/exceptions/{exception_id}/evidence", {
        params: { path: { exception_id: exceptionId } },
      });
      if (e || !data) throw new Error("could not load evidence");
      return data as Evidence;
    },
  });

  if (error) return <div className="panel p-4 text-[12.5px] text-warn">Could not load the evidence for this exception.</div>;
  if (!evidence) return <Skeleton className="h-[420px]" />;

  const { exception, events } = evidence;
  const tone = TIER_TONE[exception.tier];

  return (
    <section aria-label={`Evidence for ${exception.exception_id}`} className="flex flex-col gap-4">
      <div className="panel overflow-hidden">
        <div className="border-b border-line px-[18px] pt-4 pb-3.5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="num text-[10.5px] text-ink-3">EXC-{shortId(exception.exception_id, 8)}</div>
              <h2 className="mt-0.5 text-[15px] font-semibold text-ink">{humanizeSnakeCase(exception.category)}</h2>
            </div>
            <Pill tone={tone} dot>
              {TIER_SHORT[exception.tier]}
            </Pill>
          </div>
          <div className={cn("num mt-3 text-[28px] leading-none font-semibold", TIER_TEXT[exception.tier])}>{formatPaise(exception.residual_paise)}</div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-ink-3">
            <span>{TIER_LABEL[exception.tier]}</span>
            <span className="num">confidence {formatDecimalPercent(exception.confidence)}</span>
            {exception.deadline && <span className="text-warn">act by {exception.deadline}</span>}
            {exception.suspicious_narration && <span className="text-bad">suspicious narration</span>}
          </div>
        </div>

        <div className="px-[18px] py-3.5">
          {exception.consequence && <p className="text-[12.5px] text-ink-2">{exception.consequence}</p>}
          <p className="mt-2 text-[12.5px] font-medium text-ink">{exception.recommended_action}</p>
        </div>
      </div>

      <div className="panel px-[18px] py-4">
        <div className="label mb-2.5">Proof tree</div>
        <ProofTree evidence={evidence} />
      </div>

      <details className="panel group px-[18px] py-3.5">
        <summary className="label flex cursor-pointer items-center gap-1.5 list-none select-none">
          <ChevronRight width={12} height={12} className="transition-transform duration-150 group-open:rotate-90" />
          Raw source rows <span className="num text-ink-2">{events.length}</span>
        </summary>
        <ul className="mt-3 flex flex-col gap-2">
          {events.map((event) => (
            <li key={event.event_id} className="rounded-[8px] border border-line bg-bg p-2.5 text-[11.5px]">
              <div className="num flex flex-wrap items-center gap-x-3 text-ink-2">
                <span className="flex items-center gap-1.5 capitalize">
                  <SourceDot source={event.source} />
                  {event.source}
                </span>
                <span className="text-ink">{formatPaise(event.amount_paise)}</span>
                <span>{event.txn_date}</span>
                {event.utr && <span>UTR {event.utr}</span>}
                {event.settlement_id && <span>{event.settlement_id}</span>}
                {event.voucher_number && <span>vch {event.voucher_number}</span>}
              </div>
              {event.raw_narration && <p className="num mt-1.5 break-all text-ink-3">{event.raw_narration}</p>}
            </li>
          ))}
        </ul>
      </details>

      <InstructionBox exceptionId={exceptionId} onApplied={onApplied} />
    </section>
  );
}

/** The monospace proof tree, reusable wherever an exception's evidence is shown. */
export function ProofTree({ evidence, className }: { evidence: Evidence; className?: string }) {
  return (
    <pre className={cn("tree", className)}>
      {renderTree(evidence).map((node, i) =>
        node === "\n" ? (
          <Fragment key={i}>{node}</Fragment>
        ) : (
          <span key={i} className="tree-line" style={{ animationDelay: `${Math.floor(i / 2) * 25}ms` }}>
            {node}
          </span>
        ),
      )}
    </pre>
  );
}

function renderTree(evidence: Evidence) {
  const { exception, matches } = evidence;
  const nodes: React.ReactNode[] = [];
  const push = (node: React.ReactNode) => nodes.push(node, "\n");

  push(
    <>
      <b>{humanizeSnakeCase(exception.category)}</b> <span className="dim">·</span> {exception.event_ids.length} event
      {exception.event_ids.length === 1 ? "" : "s"} <span className="dim">·</span> residual <b>{formatPaise(exception.residual_paise)}</b>
    </>,
  );

  if (matches.length === 0) {
    push(
      <>
        └─ <span className="warn">no candidate group</span> <span className="dim">these events never entered a match</span>
      </>,
    );
  }

  matches.forEach((match, mi) => {
    const lastMatch = mi === matches.length - 1 && (exception.rules_applied?.length ?? 0) === 0;
    const branch = lastMatch ? "└─" : "├─";
    const cont = lastMatch ? "   " : "│  ";
    push(
      <>
        {branch} stage <b>{match.stage}</b>{" "}
        <span className={match.auto_closed ? "ok" : "warn"}>{match.auto_closed ? "auto-closed" : "held"}</span>{" "}
        <span className="dim">confidence</span> {formatDecimalPercent(match.confidence)}
      </>,
    );
    match.evidence.forEach((leg, li) => {
      const lastLeg = li === match.evidence.length - 1;
      const lb = lastLeg ? "└─" : "├─";
      const agreed = leg.fields_agreed ?? [];
      const disagreed = leg.fields_disagreed ?? [];
      push(
        <>
          {cont}
          {lb} agreed <span className="ok">{agreed.length ? agreed.join(", ") : "none"}</span>
          {disagreed.length > 0 && (
            <>
              {" "}
              <span className="dim">·</span> disagreed <span className="bad">{disagreed.join(", ")}</span>
            </>
          )}
          {leg.delta_paise !== 0 && (
            <>
              {" "}
              <span className="dim">·</span> delta {formatPaise(leg.delta_paise)}
            </>
          )}
        </>,
      );
      if (leg.confidence_derivation) {
        push(
          <>
            {cont}
            {lastLeg ? "   " : "│  "}
            <span className="dim">base</span> {formatDecimalPercent(leg.confidence_derivation.base_stage_confidence)}{" "}
            <span className="dim">→ result</span> <b>{formatDecimalPercent(leg.confidence_derivation.result)}</b>
          </>,
        );
      }
    });
  });

  const rules = exception.rules_applied ?? [];
  rules.forEach((rule, ri) => {
    const last = ri === rules.length - 1;
    push(
      <>
        {last ? "└─" : "├─"} rule <b>{rule.rule_id}</b> <span className="dim">v{rule.version}</span> explained{" "}
        <span className="ok">{formatPaise(rule.explained_paise)}</span>
      </>,
    );
  });

  return nodes;
}
