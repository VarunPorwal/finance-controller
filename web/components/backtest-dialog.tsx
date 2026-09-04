"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { apiClient } from "@/lib/client";
import { formatPaise } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Shown before any activation, never optional. A rule is born `draft` and
 * this is the only screen that can turn it `active`.
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
  const [reason, setReason] = useState("");
  const [activating, setActivating] = useState(false);
  const reasonRef = useRef<HTMLTextAreaElement>(null);

  // Escape closes; focus goes to the reason field on open and back to the
  // opener on close.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    reasonRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { data: result, error } = useQuery({
    queryKey: queryKeys.ruleBacktest(ruleId, version),
    queryFn: async () => {
      const { data, error: e } = await apiClient.POST("/api/v1/rules/{rule_id}/backtest", { params: { path: { rule_id: ruleId }, query: { version } } });
      if (e || !data) throw new Error("back-test failed to run");
      return data;
    },
  });

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4 backdrop-blur-[2px]" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Back-test for ${ruleName}`}
        onClick={(e) => e.stopPropagation()}
        className="fade-up w-full max-w-[600px] overflow-hidden rounded-[14px] border border-line-strong bg-surface shadow-[var(--shadow-pop)]"
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <div className="label">Back-test before activation</div>
            <h2 className="mt-1 text-[15px] font-semibold text-ink">{ruleName}</h2>
            <p className="num mt-0.5 text-[11.5px] text-ink-3">
              {ruleId} v{version} · run against exceptions a human already resolved or wrote off
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-ink-3 hover:text-ink" aria-label="Close">
            <X width={16} height={16} />
          </button>
        </div>

        <div className="px-5 py-4">
          {error && <p className="text-[12.5px] text-warn">The back-test failed to run.</p>}
          {!result && !error && <Skeleton className="h-32" />}
          {result && (
            <>
              <p className="num text-[12.5px] text-ink-2">
                {result.cases_considered} historical cases considered · {result.unverified} unverified
              </p>
              <div className="mt-3 grid grid-cols-3 gap-3">
                <Bucket label="Would explain" tone="text-ok" count={result.would_explain.count} totalPaise={result.would_explain.total_paise} />
                <Bucket
                  label="Would wrongly close"
                  tone={result.would_wrongly_close.count > 0 ? "text-bad" : "text-ok"}
                  count={result.would_wrongly_close.count}
                  totalPaise={result.would_wrongly_close.total_paise}
                />
                <Bucket label="Partially" tone="text-warn" count={result.would_partially_explain.count} totalPaise={result.would_partially_explain.total_paise} />
              </div>
              <p className="mt-3 rounded-[8px] border border-line bg-bg px-3 py-2.5 text-[12.5px] text-ink">{result.net_recommendation}</p>

              <div className="mt-4 border-t border-line pt-4">
                <label htmlFor="activate-reason" className="text-[11.5px] text-ink-2">
                  Reason to activate, recorded in the audit trail
                </label>
                <textarea
                  id="activate-reason"
                  ref={reasonRef}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={2}
                  placeholder="Back-test shows zero wrongly-closed cases against 30 days of history."
                  className="input mt-1.5"
                />
                <div className="mt-3 flex items-center gap-2">
                  <Button variant="ok" disabled={!reason.trim() || activating} onClick={activate}>
                    {activating ? "Activating…" : "Activate rule"}
                  </Button>
                  <Button variant="ghost" onClick={onClose}>
                    Leave as draft
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Bucket({ label, tone, count, totalPaise }: { label: string; tone: string; count: number; totalPaise: number }) {
  return (
    <div className="rounded-[8px] border border-line bg-bg px-3 py-2.5">
      <div className="label">{label}</div>
      <div className={cn("num mt-1.5 text-[22px] leading-none font-semibold", tone)}>{count}</div>
      <div className="num mt-1 text-[10.5px] text-ink-3">{formatPaise(totalPaise)}</div>
    </div>
  );
}
