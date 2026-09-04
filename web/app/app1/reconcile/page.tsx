"use client";

// Reconcile. Do bank and books actually agree? Owns the reconciliation
// statement, coverage ratios, lanes and the sign-off — the cash bridge and
// the settlement register are owned by Cash and Settlements respectively.

import type { CSSProperties } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { FcCard, FcEmpty, FcErrorNote, FcHead, FcPage, FcSkeleton } from "../_components/fc-ui";
import { useCashBridge, useCurrentRun, useEvents, useExceptions, useMatches } from "../_lib/api";
import { buildRegister } from "../settlements/register";
import { useMemo } from "react";
import { Statement } from "./statement";
import { ReconcileCoverage } from "./coverage";
import { Lanes } from "./lanes";
import { SignOff } from "./signoff";

export default function ReconcilePage() {
  const { runId, loading: runLoading, error: runError } = useCurrentRun();
  const bridge = useCashBridge(runId);
  const events = useEvents(runId);
  const matches = useMatches(runId);
  const exceptions = useExceptions(runId);

  const register = useMemo(
    () => (events.data && matches.data && exceptions.data ? buildRegister(events.data, matches.data, exceptions.data) : null),
    [events.data, matches.data, exceptions.data],
  );

  const loading = runLoading || bridge.isPending || events.isPending || matches.isPending || exceptions.isPending;
  const error = runError ?? bridge.error?.message ?? events.error?.message ?? matches.error?.message ?? exceptions.error?.message;

  return (
    <div style={{ "--fc-warn": "#3b93ce" } as CSSProperties}>
      <FcPage>
        <FcHead title="Reconcile" sub="Do bank and books actually agree?" />

        {error ? (
          <FcErrorNote message={error} />
        ) : !runId && !runLoading ? (
          <FcCard>
            <FcEmpty
              title="No run to reconcile"
              sub="Run a reconciliation first — the statement, coverage and lanes are computed from it."
            />
            <div className="flex justify-center pb-4">
              <Link href="/app1/run" className="fc-btn">
                Go to Run <ArrowRight size={13} />
              </Link>
            </div>
          </FcCard>
        ) : loading || !bridge.data || !register ? (
          <div className="flex flex-col gap-3">
            <FcSkeleton className="h-64" />
            <FcSkeleton className="h-40" />
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="grid items-stretch gap-3 lg:grid-cols-[7fr_5fr]">
              <Statement b={bridge.data.books_vs_bank} />
              <ReconcileCoverage register={register} events={events.data ?? []} />
            </div>

            <Lanes lanes={bridge.data.lanes} />

            <SignOff rows={register.rows} exceptions={exceptions.data ?? []} runId={runId ?? ""} />
          </div>
        )}
      </FcPage>
    </div>
  );
}
