"use client";

import { useEffect, useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { formatDecimalPercent, formatPaise, humanizeSnakeCase } from "@/lib/format";
import { TIER_COLOR, TIER_LABEL } from "@/lib/tier";

type Evidence = components["schemas"]["ExceptionEvidenceOut"];

/**
 * PRD §13.5/§13.6/§7's evidence pack: stages attempted, rules considered,
 * confidence derivation, the raw source row, and the consequence/deadline —
 * everything a human needs to decide without re-deriving it themselves. The
 * instruction box sits at the bottom, in context (§13.5: "the human reads
 * the evidence, then says what they know" — not built yet in this
 * checkpoint; the parse/preview/confirm flow is separate work).
 */
export function EvidencePack({ exceptionId }: { exceptionId: string | null }) {
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!exceptionId) {
      setEvidence(null);
      return;
    }
    let cancelled = false;
    async function load() {
      const { data, error: fetchError } = await apiClient.GET(
        "/api/v1/exceptions/{exception_id}/evidence",
        { params: { path: { exception_id: exceptionId as string } } },
      );
      if (cancelled) return;
      if (fetchError || !data) {
        setError("could not load evidence");
        return;
      }
      setEvidence(data);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [exceptionId]);

  if (!exceptionId) {
    return (
      <section className="border-rule bg-ink-800 rounded-lg border border-dashed p-8 text-center">
        <p className="text-paper-500 text-sm">Select an item from the queue to see its evidence.</p>
      </section>
    );
  }
  if (error) {
    return <div className="text-sig-amber border-rule bg-ink-800 rounded-lg border p-4 text-sm">{error}</div>;
  }
  if (!evidence) {
    return (
      <div className="border-rule bg-ink-800 h-64 animate-pulse rounded-lg border" aria-hidden />
    );
  }

  const { exception, events, matches } = evidence;

  return (
    <section aria-label={`Evidence for ${exception.exception_id}`} className="flex flex-col gap-4">
      <header className="border-rule bg-ink-800 rounded-lg border p-4">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="font-heading text-base font-semibold text-paper-100">
            {humanizeSnakeCase(exception.category)}
          </h2>
          <span className={"fc-numeric text-lg font-bold " + TIER_COLOR[exception.tier]}>
            {formatPaise(exception.residual_paise)}
          </span>
        </div>
        <div className="text-paper-300 mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          <span className={TIER_COLOR[exception.tier]}>{TIER_LABEL[exception.tier]}</span>
          <span className="fc-numeric">confidence {formatDecimalPercent(exception.confidence)}</span>
          {exception.deadline && <span>act by {exception.deadline}</span>}
          {exception.suspicious_narration && (
            <span className="text-sig-red">⚠ suspicious narration</span>
          )}
        </div>
        {exception.consequence && (
          <p className="text-paper-300 mt-2 text-sm">{exception.consequence}</p>
        )}
        <p className="text-paper-100 mt-2 text-sm font-medium">{exception.recommended_action}</p>
      </header>

      <div className="border-rule bg-ink-800 rounded-lg border p-4">
        <h3 className="font-heading text-paper-300 mb-2 text-xs font-semibold uppercase tracking-wide">
          Matching evidence
        </h3>
        {matches.length === 0 && (
          <p className="text-paper-500 text-sm">
            No matching evidence — these events never entered a candidate group.
          </p>
        )}
        {matches.map((match) => (
          <div key={match.match_id} className="border-rule mb-2 border-b pb-2 last:border-b-0 last:pb-0">
            <div className="flex items-center justify-between text-sm">
              <span className="text-paper-100 font-medium">
                {humanizeSnakeCase(match.stage)} {match.auto_closed ? "✓ auto-closed" : ""}
              </span>
              <span className="fc-numeric text-paper-300">
                {formatDecimalPercent(match.confidence)}
              </span>
            </div>
            {match.evidence.map((leg, i) => (
              <div key={i} className="text-paper-500 mt-1 text-xs">
                {leg.fields_agreed && leg.fields_agreed.length > 0 && (
                  <span>agreed: {leg.fields_agreed.join(", ")} · </span>
                )}
                {leg.fields_disagreed && leg.fields_disagreed.length > 0 && (
                  <span className="text-sig-amber">disagreed: {leg.fields_disagreed.join(", ")} · </span>
                )}
                {leg.delta_paise !== 0 && <span>delta {formatPaise(leg.delta_paise)} · </span>}
                {leg.confidence_derivation && (
                  <span className="fc-numeric">
                    base {formatDecimalPercent(leg.confidence_derivation.base_stage_confidence)} →
                    result {formatDecimalPercent(leg.confidence_derivation.result)}
                  </span>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      {(exception.rules_applied?.length ?? 0) > 0 && (
        <div className="border-rule bg-ink-800 rounded-lg border p-4">
          <h3 className="font-heading text-paper-300 mb-2 text-xs font-semibold uppercase tracking-wide">
            Rules considered
          </h3>
          <ul className="flex flex-col gap-1 text-sm">
            {exception.rules_applied?.map((rule) => (
              <li key={rule.rule_id} className="flex items-center justify-between gap-2">
                <span className="fc-numeric text-paper-300">
                  {rule.rule_id} v{rule.version}
                </span>
                <span className="fc-numeric text-paper-100">{formatPaise(rule.explained_paise)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="border-rule bg-ink-800 rounded-lg border p-4">
        <summary className="font-heading text-paper-300 cursor-pointer select-none text-xs font-semibold uppercase tracking-wide">
          Raw source row ({events.length})
        </summary>
        <ul className="mt-2 flex flex-col gap-2">
          {events.map((event) => (
            <li key={event.event_id} className="border-rule border-t pt-2 text-xs">
              <div className="fc-numeric flex flex-wrap gap-x-3 text-paper-300">
                <span>{event.source}</span>
                <span>{formatPaise(event.amount_paise)}</span>
                <span>{event.txn_date}</span>
                {event.utr && <span>UTR {event.utr}</span>}
              </div>
              {event.raw_narration && (
                <p className="fc-numeric text-paper-500 mt-1 break-all">{event.raw_narration}</p>
              )}
            </li>
          ))}
        </ul>
      </details>

      <div className="border-rule bg-ink-800 rounded-lg border p-4">
        <label htmlFor="instruction" className="text-paper-300 mb-2 block text-xs font-medium">
          Tell the agent what this is…
        </label>
        <textarea
          id="instruction"
          disabled
          placeholder="Coming next: preview → confirm → cluster offer → rule suggestion."
          className="border-rule bg-ink-900 text-paper-100 placeholder:text-paper-500 w-full resize-none rounded-md border p-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
          rows={2}
        />
      </div>
    </section>
  );
}
