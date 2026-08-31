"use client";

import { useQuery } from "@tanstack/react-query";
import { apiClient, type components } from "@/lib/client";
import {
  formatDecimalPercent,
  formatPaise,
  humanizeSnakeCase,
} from "@/lib/format";
import { TIER_COLOR, TIER_LABEL } from "@/lib/tier";
import { InstructionBox } from "@/components/instruction-box";
import { queryKeys } from "@/lib/query-keys";

type Evidence = components["schemas"]["ExceptionEvidenceOut"];

/**
 * PRD §13.5/§13.6/§7's evidence pack: stages attempted, rules considered,
 * confidence derivation, the raw source row, and the consequence/deadline —
 * everything a human needs to decide without re-deriving it themselves. The
 * instruction box sits at the bottom, in context (§13.5: "the human reads
 * the evidence, then says what they know" — not built yet in this
 * checkpoint; the parse/preview/confirm flow is separate work).
 */
export function EvidencePack({
  exceptionId,
  onApplied,
}: {
  exceptionId: string | null;
  onApplied: () => void;
}) {
  const { data: evidence, error: queryError } = useQuery({
    queryKey: queryKeys.exceptionEvidence(exceptionId),
    queryFn: async () => {
      const { data, error: fetchError } = await apiClient.GET(
        "/api/v1/exceptions/{exception_id}/evidence",
        { params: { path: { exception_id: exceptionId as string } } },
      );
      if (fetchError || !data) throw new Error("could not load evidence");
      return data;
    },
    enabled: !!exceptionId,
  });
  const error = queryError ? "could not load evidence" : null;

  if (!exceptionId) {
    return (
      <section className="border-border bg-card rounded-lg border border-dashed p-8 text-center">
        <p className="text-text-muted text-sm">
          Select an item from the queue to see its evidence.
        </p>
      </section>
    );
  }
  if (error) {
    return (
      <div className="text-amber-text border-border bg-card rounded-lg border p-4 text-sm">
        {error}
      </div>
    );
  }
  if (!evidence) {
    return (
      <div
        className="border-border bg-card h-64 animate-pulse rounded-lg border"
        aria-hidden
      />
    );
  }

  const { exception, events, matches } = evidence;

  return (
    <section
      aria-label={`Evidence for ${exception.exception_id}`}
      className="flex flex-col gap-4"
    >
      <header className="border-border bg-card rounded-lg border p-4">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-base font-semibold text-text-heading">
            {humanizeSnakeCase(exception.category)}
          </h2>
          <span
            className={
              "fc-numeric text-lg font-bold " + TIER_COLOR[exception.tier]
            }
          >
            {formatPaise(exception.residual_paise)}
          </span>
        </div>
        <div className="text-text-body mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span className={TIER_COLOR[exception.tier]}>
            {TIER_LABEL[exception.tier]}
          </span>
          <span className="fc-numeric">
            confidence {formatDecimalPercent(exception.confidence)}
          </span>
          {exception.deadline && <span>act by {exception.deadline}</span>}
          {exception.suspicious_narration && (
            <span className="text-error">⚠ suspicious narration</span>
          )}
        </div>
        {exception.consequence && (
          <p className="text-text-body mt-2 text-sm">{exception.consequence}</p>
        )}
        <p className="text-text-heading mt-2 text-sm font-medium">
          {exception.recommended_action}
        </p>
      </header>

      <div className="border-border bg-card rounded-lg border p-4">
        <h3 className="text-text-body mb-2 text-xs font-semibold uppercase tracking-wide">
          Matching evidence
        </h3>
        {matches.length === 0 && (
          <p className="text-text-muted text-sm">
            No matching evidence — these events never entered a candidate group.
          </p>
        )}
        {matches.map((match) => (
          <div
            key={match.match_id}
            className="border-border mb-2 border-b pb-2 last:border-b-0 last:pb-0"
          >
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-heading font-medium">
                {humanizeSnakeCase(match.stage)}{" "}
                {match.auto_closed ? "✓ auto-closed" : ""}
              </span>
              <span className="fc-numeric text-text-body">
                {formatDecimalPercent(match.confidence)}
              </span>
            </div>
            {match.evidence.map((leg, i) => (
              <div key={i} className="text-text-muted mt-1 text-xs">
                {leg.fields_agreed && leg.fields_agreed.length > 0 && (
                  <span>agreed: {leg.fields_agreed.join(", ")} · </span>
                )}
                {leg.fields_disagreed && leg.fields_disagreed.length > 0 && (
                  <span className="text-amber-text">
                    disagreed: {leg.fields_disagreed.join(", ")} ·{" "}
                  </span>
                )}
                {leg.delta_paise !== 0 && (
                  <span>delta {formatPaise(leg.delta_paise)} · </span>
                )}
                {leg.confidence_derivation && (
                  <span className="fc-numeric">
                    base{" "}
                    {formatDecimalPercent(
                      leg.confidence_derivation.base_stage_confidence,
                    )}{" "}
                    → result{" "}
                    {formatDecimalPercent(leg.confidence_derivation.result)}
                  </span>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      {(exception.rules_applied?.length ?? 0) > 0 && (
        <div className="border-border bg-card rounded-lg border p-4">
          <h3 className="text-text-body mb-2 text-xs font-semibold uppercase tracking-wide">
            Rules considered
          </h3>
          <ul className="flex flex-col gap-1 text-sm">
            {exception.rules_applied?.map((rule) => (
              <li
                key={rule.rule_id}
                className="flex items-center justify-between gap-2"
              >
                <span className="fc-numeric text-text-body">
                  {rule.rule_id} v{rule.version}
                </span>
                <span className="fc-numeric text-text-heading">
                  {formatPaise(rule.explained_paise)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="border-border bg-card rounded-lg border p-4">
        <summary className="text-text-body cursor-pointer select-none text-xs font-semibold uppercase tracking-wide">
          Raw source row ({events.length})
        </summary>
        <ul className="mt-2 flex flex-col gap-2">
          {events.map((event) => (
            <li
              key={event.event_id}
              className="border-border border-t pt-2 text-xs"
            >
              <div className="fc-numeric flex flex-wrap gap-x-3 text-text-body">
                <span>{event.source}</span>
                <span>{formatPaise(event.amount_paise)}</span>
                <span>{event.txn_date}</span>
                {event.utr && <span>UTR {event.utr}</span>}
              </div>
              {event.raw_narration && (
                <p className="fc-numeric text-text-muted mt-1 break-all">
                  {event.raw_narration}
                </p>
              )}
            </li>
          ))}
        </ul>
      </details>

      <InstructionBox
        exceptionId={exceptionId as string}
        onApplied={onApplied}
      />
    </section>
  );
}
