"use client";

import { useEffect, useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";

type BacktestOut = components["schemas"]["BacktestOut"];

/**
 * PRD §13.6/§2.6 D4: the back-test dialog, shown before any activation —
 * never optional, never skippable. A rule is born `draft` (§8.8: "never
 * auto-activates") and this is the only screen that can turn it `active`.
 */
export function BacktestDialog({
  ruleId,
  version,
  ruleName,
  onActivated,
  onClose,
}: {
  ruleId: string;
  version: number;
  ruleName: string;
  onActivated: () => void;
  onClose: () => void;
}) {
  const [result, setResult] = useState<BacktestOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [activating, setActivating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const { data, error: fetchError } = await apiClient.POST(
        "/api/v1/rules/{rule_id}/backtest",
        { params: { path: { rule_id: ruleId }, query: { version } } },
      );
      if (cancelled) return;
      if (fetchError || !data) {
        setError("back-test failed to run");
        return;
      }
      setResult(data);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [ruleId, version]);

  async function activate() {
    if (!reason.trim()) return;
    setActivating(true);
    const { error: activateError } = await apiClient.POST("/api/v1/rules/{rule_id}/activate", {
      params: { path: { rule_id: ruleId }, query: { version } },
      body: { reason: reason.trim() },
    });
    setActivating(false);
    if (!activateError) onActivated();
  }

  return (
    <div
      role="dialog"
      aria-label={`Back-test for ${ruleName}`}
      className="border-primary bg-card fixed inset-0 z-50 m-auto flex h-fit max-h-[85vh] w-[min(560px,92vw)] flex-col gap-4 overflow-y-auto rounded-lg border p-5 shadow-2xl"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-text-heading">
            Back-test: {ruleName}
          </h2>
          <p className="text-text-muted text-xs">
            {ruleId} v{version} — run against resolved/written-off exceptions before this rule can
            activate.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-text-muted hover:text-text-heading text-sm"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      {error && <p className="text-amber-text text-sm">{error}</p>}
      {!result && !error && (
        <div className="border-border bg-background h-32 animate-pulse rounded-lg border" aria-hidden />
      )}

      {result && (
        <>
          <p className="text-text-body text-sm">
            {result.cases_considered} historical cases considered, {result.unverified} unverified.
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Bucket
              label="Would explain"
              tone="text-success"
              count={result.would_explain.count}
              totalPaise={result.would_explain.total_paise}
            />
            <Bucket
              label="Would wrongly close"
              tone="text-error"
              count={result.would_wrongly_close.count}
              totalPaise={result.would_wrongly_close.total_paise}
            />
            <Bucket
              label="Would partially explain"
              tone="text-amber-text"
              count={result.would_partially_explain.count}
              totalPaise={result.would_partially_explain.total_paise}
            />
          </div>
          <p className="text-text-heading text-sm font-medium">{result.net_recommendation}</p>

          <div className="border-border border-t pt-3">
            <label htmlFor="activate-reason" className="text-text-body mb-1 block text-xs font-medium">
              Reason to activate (required)
            </label>
            <textarea
              id="activate-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={2}
              placeholder="Back-test shows zero wrongly-closed cases against 30 days of history."
              className="border-border bg-background text-text-heading placeholder:text-text-muted w-full resize-none rounded-md border p-2 text-sm"
            />
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                disabled={!reason.trim() || activating}
                onClick={activate}
                className="bg-primary hover:bg-primary/90 rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                {activating ? "Activating…" : "Activate rule"}
              </button>
              <button
                type="button"
                onClick={onClose}
                className="border-border text-text-body hover:bg-neutral-bg rounded-md border px-4 py-2 text-sm"
              >
                Leave as draft
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Bucket({
  label,
  tone,
  count,
  totalPaise,
}: {
  label: string;
  tone: string;
  count: number;
  totalPaise: number;
}) {
  return (
    <div className="border-border bg-background rounded-md border p-2">
      <p className="text-text-muted text-xs">{label}</p>
      <p className={"fc-numeric text-sm font-semibold " + tone}>{count}</p>
      <p className="fc-numeric text-text-body text-xs">{formatPaise(totalPaise)}</p>
    </div>
  );
}
