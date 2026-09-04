"use client";

// The learner's inbox. Each card is a rule drafted from a pattern in human
// resolutions. It is never active until a person back-tests and accepts it.
// Collapsed to the top 3 by occurrence count; the rest are a click away.

import { useState } from "react";
import { Sparkles, Check, X, FlaskConical } from "lucide-react";
import { writes, useWrite, errorMessage, type Suggestion } from "../_lib/api";
import { categoryLabel } from "../_lib/labels";
import { plural } from "../_lib/format";
import { FcCard, FcErrorNote, StatusDot } from "../_components/fc-ui";
import { BacktestResult, BacktestSkeleton } from "./backtest";
import { MiniWaterfall } from "./waterfall";
import { rateText } from "./shared";

export function SuggestionsInbox({ suggestions }: { suggestions: Suggestion[] }) {
  const [expanded, setExpanded] = useState(false);
  const ranked = [...suggestions].sort((a, b) => b.occurrences - a.occurrences);
  const shown = expanded ? ranked : ranked.slice(0, 3);
  const rest = ranked.length - shown.length;

  return (
    <section className="mb-6">
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 fc-strong" style={{ fontSize: 14 }}>
            <Sparkles size={14} style={{ color: "var(--fc-accent)" }} />
            Learned suggestions
          </div>
          <div className="fc-faint mt-0.5" style={{ fontSize: 12 }}>
            {plural(suggestions.length, "draft")} drafted from patterns in human resolutions. Nothing activates on its own.
          </div>
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {shown.map((s) => (
          <SuggestionCard key={s.signature} s={s} />
        ))}
      </div>
      {rest > 0 && !expanded && (
        <button className="fc-link mt-3" onClick={() => setExpanded(true)}>
          {plural(rest, "more")} →
        </button>
      )}
      {expanded && ranked.length > 3 && (
        <button className="fc-link mt-3" onClick={() => setExpanded(false)}>
          Show fewer
        </button>
      )}
    </section>
  );
}

function SuggestionCard({ s }: { s: Suggestion }) {
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState("");
  const backtest = useWrite((a: { ruleId: string; version: number }) =>
    writes.backtest(a.ruleId, a.version, undefined as never),
  );
  const accept = useWrite((sig: string) => writes.acceptSuggestion(sig));
  const dismiss = useWrite((a: { sig: string; reason: string }) =>
    writes.dismissSuggestion(a.sig, { reason: a.reason }),
  );
  const rule = s.rule;
  const err = backtest.error ?? accept.error ?? dismiss.error;

  return (
    <FcCard variant="hero" className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="fc-label" style={{ color: "var(--fc-accent)" }}>
            Learned from {plural(s.occurrences, "human resolution")}
          </div>
          <div className="mt-1 fc-strong" style={{ fontSize: 14 }}>
            {rule.name}
          </div>
        </div>
        <StatusDot tone="neutral">Draft</StatusDot>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1" style={{ fontSize: 12.5 }}>
        <span>
          <span className="fc-faint">Resolved as </span>
          {categoryLabel(s.resolution_category)}
        </span>
        <span>
          <span className="fc-faint">Observed rate </span>
          <span className="fc-num">{rateText(s.observed_rate_percent)}</span>
        </span>
        <span>
          <span className="fc-faint">Across </span>
          <span className="fc-num">{plural(s.exception_ids.length, "exception")}</span>
        </span>
      </div>

      <div className="flex items-end justify-between gap-4">
        <MiniWaterfall deductions={rule.deductions ?? []} />
        <div className="fc-faint" style={{ fontSize: 11 }}>
          illustration on ₹10,000
        </div>
      </div>

      {backtest.isPending && <BacktestSkeleton />}
      {backtest.data && <BacktestResult result={backtest.data} />}
      {accept.isSuccess && (
        <div
          className="rounded-lg px-3 py-2"
          style={{ border: "1px solid rgba(62,168,43,0.35)", background: "rgba(62,168,43,0.1)", fontSize: 12.5, color: "var(--fc-ok)" }}
        >
          Draft saved to the Rule Book. Back-test and activate it from its card.
        </div>
      )}
      {err && <FcErrorNote message={errorMessage(err)} />}

      {dismissing ? (
        <div className="flex flex-col gap-2">
          <input
            style={{
              width: "100%",
              borderRadius: 8,
              border: "1px solid var(--fc-border)",
              background: "var(--fc-hover)",
              color: "var(--fc-text)",
              padding: "8px 10px",
              fontSize: 12.5,
              outline: "none",
            }}
            placeholder="Why this pattern should not become a rule"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
          />
          <div className="flex justify-end gap-2">
            <button className="fc-btn fc-btn--ghost" style={{ padding: "6px 12px", fontSize: 12.5 }} onClick={() => setDismissing(false)}>
              Keep
            </button>
            <button
              className="fc-btn"
              style={{ padding: "6px 12px", fontSize: 12.5, background: "var(--fc-bad)" }}
              disabled={!reason.trim() || dismiss.isPending}
              onClick={() => dismiss.mutate({ sig: s.signature, reason: reason.trim() })}
            >
              {dismiss.isPending ? "Working…" : "Dismiss"}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-end gap-2">
          <button
            className="fc-btn fc-btn--ghost"
            style={{ padding: "6px 12px", fontSize: 12.5 }}
            onClick={() => setDismissing(true)}
            disabled={accept.isSuccess}
          >
            <X size={13} />
            Dismiss
          </button>
          <button
            className="fc-btn fc-btn--ghost"
            style={{ padding: "6px 12px", fontSize: 12.5 }}
            disabled={backtest.isPending}
            onClick={() => backtest.mutate({ ruleId: rule.rule_id, version: rule.version })}
          >
            <FlaskConical size={13} />
            {backtest.isPending ? "Testing…" : "Back-test"}
          </button>
          <button
            className="fc-btn"
            style={{ padding: "6px 12px", fontSize: 12.5 }}
            disabled={accept.isSuccess || accept.isPending}
            onClick={() => accept.mutate(s.signature)}
          >
            <Check size={13} />
            {accept.isPending ? "Saving…" : "Accept"}
          </button>
        </div>
      )}
    </FcCard>
  );
}
