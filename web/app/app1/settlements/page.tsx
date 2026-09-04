"use client";

// Settlements. What did each settlement actually do? Owns the register.
// The reconciliation statement and sign-off live on Reconcile instead.

import { useMemo } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { FcCard, FcCardHeader, FcEmpty, FcErrorNote, FcHead, FcPage, FcSkeleton } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";
import { useCurrentRun, useEvents, useMatches, useExceptions, errorMessage } from "../_lib/api";
import { plural } from "../_lib/format";
import { buildRegister, type Register } from "./register";
import { RegisterTable } from "./register-table";
import { Coverage } from "./coverage";

/** One compact row of header stats, separated by hairlines. The register is
 * the point of this page — these are a strip, not four cards competing with it. */
function HeaderStrip({ register }: { register: Register }) {
  const items: { label: string; paise?: number; count?: number }[] = [
    { label: "Razorpay", paise: register.totals.razorpay },
    { label: "Bank received", paise: register.totals.bank },
    { label: "Tally booked", paise: register.totals.ledger },
    { label: "Settlements", count: register.counts.settlements },
  ];
  return (
    <div
      className="mb-3 flex items-stretch"
      style={{ background: "var(--fc-card-grad)", border: "1px solid var(--fc-border)", borderRadius: "var(--fc-r)", minHeight: 52 }}
    >
      {items.map((it, i) => (
        <div
          key={it.label}
          className="flex flex-1 flex-col justify-center"
          style={{ padding: "8px 18px", borderLeft: i > 0 ? "1px solid var(--fc-divider)" : undefined }}
        >
          <div className="fc-label" style={{ fontSize: 11 }}>{it.label}</div>
          <div className="fc-num mt-0.5" style={{ fontSize: 18, fontWeight: 500, letterSpacing: "-0.01em" }}>
            {it.paise !== undefined ? (
              <CountUp value={it.paise / 100} format={(n) => `₹${Math.round(n).toLocaleString("en-IN")}`} />
            ) : (
              <CountUp value={it.count ?? 0} />
            )}
          </div>
          {it.count !== undefined && (
            <div className="fc-faint mt-0.5" style={{ fontSize: 11 }}>
              {register.counts.proven} proven · {register.counts.rule} by rule · {register.counts.open} open
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function SettlementsPage() {
  const { runId, loading: runLoading, error: runError } = useCurrentRun();
  const events = useEvents(runId);
  const matches = useMatches(runId);
  const exceptions = useExceptions(runId);

  const register = useMemo(
    () => (events.data && matches.data && exceptions.data ? buildRegister(events.data, matches.data, exceptions.data) : null),
    [events.data, matches.data, exceptions.data],
  );

  const loading = runLoading || events.isLoading || matches.isLoading || exceptions.isLoading;
  const error = runError ?? (events.error && errorMessage(events.error)) ?? (matches.error && errorMessage(matches.error)) ?? (exceptions.error && errorMessage(exceptions.error));

  return (
    <FcPage>
      <FcHead title="Settlements" sub="One row per settlement, cross-checked against the bank and Tally." />

      {error && (
        <div className="mb-3">
          <FcErrorNote message={error} />
        </div>
      )}

      {!runId && !runLoading && !error && (
        <FcCard>
          <FcEmpty
            title="No run to read"
            sub="Ingest a Razorpay export, a bank statement and a Tally day book, then run a reconciliation. The register fills from that."
          />
          <div className="flex justify-center pb-4">
            <Link href="/app1/run" className="fc-btn">
              Go to Run <ArrowRight size={13} />
            </Link>
          </div>
        </FcCard>
      )}

      {runId && loading && (
        <div className="flex flex-col gap-3">
          <FcSkeleton className="h-24" />
          <FcSkeleton className="h-96" />
        </div>
      )}

      {register && (
        <>
          <HeaderStrip register={register} />

          <div className="mb-3">
            <Coverage register={register} />
          </div>

          <FcCard style={{ padding: 0 }}>
            <FcCardHeader title="Settlement register" sub="One row per settlement. Click a row for the underlying rows and the decision that sits on it." />
            {register.rows.length === 0 ? (
              <FcEmpty title="No settlements in this run" sub="Razorpay rows carrying a settlement id would appear here." />
            ) : (
              <RegisterTable rows={register.rows} />
            )}
            <div className="fc-faint flex flex-wrap items-center gap-x-1" style={{ borderTop: "1px solid var(--fc-divider)", padding: "10px 16px", fontSize: 11.5 }}>
              <span>Not in the register:</span>
              <span className="fc-num">{plural(register.other.bankUnattached, "bank row")}</span>
              <span>and</span>
              <span className="fc-num">{plural(register.other.ledgerUnattached, "Tally row")}</span>
              <span>attached to no settlement</span>
              {register.other.razorpayWithoutSettlement > 0 && (
                <span>
                  , <span className="fc-num">{plural(register.other.razorpayWithoutSettlement, "Razorpay row")}</span> with no settlement id
                </span>
              )}
              <span>.</span>
              <Link href="/app1/records" className="fc-link ml-1 inline-flex items-center gap-1">
                See them in Records <ArrowRight size={11} />
              </Link>
            </div>
          </FcCard>
        </>
      )}
    </FcPage>
  );
}
