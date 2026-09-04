"use client";

// Controller Activity. What did the engine do, and would it do it again?

import type { CSSProperties } from "react";
import Link from "next/link";
import { ArrowRight, Play } from "lucide-react";
import { FcCard, FcEmpty, FcErrorNote, FcHead, FcPage, FcSection, FcSkeleton } from "../_components/fc-ui";
import { useCurrentRun, useExceptions, useMatches } from "../_lib/api";
import { PolicyTable } from "./policy";
import { StageFunnel } from "./funnel";
import { DiffCard } from "./diff-card";
import { MoneyStats } from "./money-stats";

export default function ControllerActivityPage() {
  const { runId, loading, error } = useCurrentRun();
  const matches = useMatches(runId);
  const exceptions = useExceptions(runId);

  const openExceptions = (exceptions.data ?? []).filter((e) => e.tier !== "auto").length;
  const anyError = error ?? matches.error?.message ?? exceptions.error?.message;

  return (
    <FcPage>
      <FcHead title="Controller Activity" sub="What did the engine do, and would it do it again?" />

      {anyError ? (
        <FcErrorNote message={anyError} />
      ) : !runId && !loading ? (
        <FcCard>
          <FcEmpty
            title="No run yet"
            sub="Controller activity is computed from a run — what it matched, what it refused, and what a replay of it looks like."
          />
          <div className="flex justify-center pb-4">
            <Link href="/run" className="fc-btn">
              Go to Run <ArrowRight size={13} />
            </Link>
          </div>
        </FcCard>
      ) : loading ? (
        <div className="flex flex-col gap-3">
          <FcSkeleton className="h-24" />
          <FcSkeleton className="h-64" />
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {/* Everything except the funnel graph picks up the page's own warn
              color; the graph keeps the real amber, so this override wraps
              only the sections before and after it, never the graph itself. */}
          <div className="flex flex-col gap-6" style={{ "--fc-warn": "#3b93ce" } as CSSProperties}>
            <div className="grid gap-6 lg:grid-cols-2" style={{ alignItems: "start" }}>
              <FcSection title="This run in money" sub="Plain counts and sums of server figures — nothing derived.">
                <MoneyStats runId={runId} />
              </FcSection>

              <DiffCard runId={runId} />
            </div>
          </div>

          <FcSection title="Where items went" sub="Every row enters at the left. The amber band is the human queue.">
            <FcCard>
              {matches.data ? (
                <StageFunnel matches={matches.data} exceptions={openExceptions} />
              ) : (
                <FcSkeleton className="h-40" />
              )}
            </FcCard>
          </FcSection>

          <div className="flex flex-col gap-6" style={{ "--fc-warn": "#3b93ce" } as CSSProperties}>
            <FcSection title="What may close itself" sub="High confidence alone is never sufficient for the right-hand column.">
              <PolicyTable />
            </FcSection>

            <FcCard>
              <div className="flex flex-wrap gap-2">
                <Link href="/run" className="fc-btn">
                  <Play size={13} />
                  Run reconciliation
                </Link>
              </div>
            </FcCard>
          </div>
        </div>
      )}
    </FcPage>
  );
}
