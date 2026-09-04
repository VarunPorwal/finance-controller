"use client";

// The bank reconciliation statement in the shape an accountant reads it.
// Every figure is the server's; the caption underneath shows the five
// components adding to the difference, which the engine asserts.

import { useRef } from "react";
import { clsx } from "clsx";
import { FcCard, FcCardHeader, FcDivider, FcMoney, WhyLabel, WhyWrap, type FcTone } from "../_components/fc-ui";
import { money } from "../_lib/format";
import type { CashBridge } from "../_lib/api";

type Books = CashBridge["books_vs_bank"];

function Line({
  label,
  paise,
  bold,
  indent,
  tone,
  onWhy,
}: {
  label: string;
  paise: number;
  bold?: boolean;
  indent?: boolean;
  tone?: FcTone;
  onWhy?: () => void;
}) {
  const figure = <FcMoney paise={paise} tone={tone ?? "neutral"} className={clsx(bold ? "font-medium" : undefined, onWhy && "fc-why-figure")} />;
  return (
    <div className={clsx("flex items-baseline justify-between gap-4 py-1.5", indent && "pl-4")}>
      <span style={{ fontSize: 12.5, fontWeight: bold ? 500 : 400, color: "var(--fc-text-2)" }}>{label}</span>
      {onWhy ? (
        <WhyWrap>
          {figure}
          <WhyLabel onClick={onWhy} />
        </WhyWrap>
      ) : (
        figure
      )}
    </div>
  );
}

export function Statement({ b }: { b: Books }) {
  const explainedRef = useRef<HTMLDivElement>(null);
  const scrollToExplained = () => explainedRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  const parts = [
    b.timing_paise,
    b.unrecorded_in_books_paise,
    b.under_investigation_paise,
    b.unidentified_inflow_paise,
    b.matched_residual_paise,
  ];
  let sum = 0;
  for (const p of parts) sum += p;
  const balances = sum === b.difference_paise;
  const fmt = (p: number) => (p < 0 ? `(${money(-p, { whole: true })})` : money(p, { whole: true }));

  return (
    <FcCard className="flex h-full flex-col" style={{ padding: 0 }}>
      <FcCardHeader title="Reconciliation statement" sub="Books against bank, in the format the auditor expects." />
      <div className="flex flex-1 flex-col" style={{ padding: "0 16px 16px" }}>
        <div className="grid grid-cols-2 gap-x-6">
          <div>
            <div className="fc-label mb-1">Per the books</div>
            <Line label="Opening balance" paise={b.opening_balance_paise} />
            <Line label="Movement in the day book" paise={b.books_movement_paise} />
            <FcDivider className="my-1" />
            <Line label="Books balance" paise={b.books_balance_paise} bold onWhy={scrollToExplained} />
          </div>
          <div>
            <div className="fc-label mb-1">Per the bank</div>
            <Line label="Opening balance" paise={b.opening_balance_paise} />
            <Line label="Movement on the statement" paise={b.bank_movement_paise} tone="accent" />
            <FcDivider className="my-1" />
            <Line label="Bank balance" paise={b.bank_balance_paise} bold tone="accent" onWhy={scrollToExplained} />
          </div>
        </div>

        <FcDivider className="my-3" />

        <div ref={explainedRef} className="fc-label mb-1">Explained by</div>
        <Line label="Timing, expected to land" paise={b.timing_paise} indent />
        <Line label="Unrecorded in the books" paise={b.unrecorded_in_books_paise} indent />
        <Line label="Under investigation" paise={b.under_investigation_paise} indent />
        <Line label="Unidentified inflow" paise={b.unidentified_inflow_paise} indent />
        <Line label="Residual inside matched groups" paise={b.matched_residual_paise} indent />
        <FcDivider className="my-1" />
        <div className="flex items-baseline justify-between gap-4 py-2">
          <span style={{ fontSize: 13, fontWeight: 500 }}>Difference, books less bank</span>
          <WhyWrap>
            <FcMoney paise={b.difference_paise} size="lg" tone={b.difference_paise === 0 ? "ok" : "neutral"} className="fc-why-figure" />
            <WhyLabel onClick={scrollToExplained} />
          </WhyWrap>
        </div>
        <p className="fc-faint mt-1" style={{ fontSize: 11.5, lineHeight: 1.4 }}>
          A negative line pulls the books below the bank. Each line is a signed part of the difference, not a sum of
          exceptions.
        </p>
        <p className={clsx("fc-num mt-2", balances ? "fc-faint" : undefined)} style={{ fontSize: 11, lineHeight: 1.6, color: balances ? undefined : "var(--fc-bad)" }}>
          {fmt(b.timing_paise)} + {fmt(b.unrecorded_in_books_paise)} + {fmt(b.under_investigation_paise)} +{" "}
          {fmt(b.unidentified_inflow_paise)} + {fmt(b.matched_residual_paise)} = {fmt(b.difference_paise)}
          {balances ? "" : ` (server figures sum to ${fmt(sum)})`}
        </p>
        <div className="mt-auto pt-3">
          <div className="flex items-baseline justify-between gap-4" style={{ fontSize: 12 }}>
            <span className="fc-muted">Unexplained on the gateway bridge</span>
            <FcMoney paise={b.unexplained_paise} tone={b.unexplained_paise > 0 ? "bad" : "ok"} />
          </div>
          <p className="fc-faint mt-0.5" style={{ fontSize: 11 }}>Expected net less actual bank. The figure this period cannot close on.</p>
        </div>
      </div>
    </FcCard>
  );
}
