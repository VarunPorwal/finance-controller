"use client";

// This run, in money. Every figure here is a plain filter or sum of server
// integers (CLAUDE.md: never derive a new financial figure client-side) —
// nothing here is computed, only counted and added.

import { useMemo, type ReactNode } from "react";
import { useEval, useExceptions, useMatches, useRules } from "../_lib/api";
import { money, plural, sumPaise } from "../_lib/format";
import { FcSkeleton, WhyLabel, WhyWrap } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";

/** One figure in the compact header strip: label above, value below, a 1px
 * divider rule between items instead of separate cards. */
function Stat({
  label,
  children,
  sub,
  tone,
  first,
}: {
  label: string;
  children: ReactNode;
  sub?: string;
  tone?: "ok" | "bad" | "warn";
  first?: boolean;
}) {
  const color = tone === "ok" ? "var(--fc-ok)" : tone === "bad" ? "var(--fc-bad)" : tone === "warn" ? "var(--fc-warn)" : undefined;
  return (
    <div
      className="flex flex-col justify-center"
      title={sub}
      style={{ padding: `0 20px 0 ${first ? 0 : 20}px`, borderLeft: first ? undefined : "1px solid var(--fc-divider)" }}
    >
      <div style={{ fontSize: 11, color: "var(--fc-text-3)" }}>{label}</div>
      <div className="fc-num" style={{ fontSize: 18, fontWeight: 500, marginTop: 2, color: color ?? "var(--fc-text)" }}>
        {children}
      </div>
    </div>
  );
}

export function MoneyStats({ runId }: { runId: string | undefined }) {
  const matches = useMatches(runId);
  const evalQ = useEval(runId);
  const exceptions = useExceptions(runId);
  const activeRules = useRules("active");

  const rulesFired = useMemo(() => {
    if (!matches.data) return undefined;
    const hashes = new Set(
      matches.data.filter((m) => m.stage === "rule" && m.rule_version_hash).map((m) => m.rule_version_hash as string),
    );
    return hashes.size;
  }, [matches.data]);

  const activeRuleCount = !activeRules.isLoading && !activeRules.error ? activeRules.data?.length : undefined;

  const declined = useMemo(() => {
    if (!exceptions.data) return undefined;
    const rows = exceptions.data.filter((e) => e.action_group === "cannot_resolve" && e.status === "open");
    return { count: rows.length, amountPaise: sumPaise(rows.map((e) => e.amount_paise)) };
  }, [exceptions.data]);

  const loading = matches.isLoading || exceptions.isLoading;

  if (loading) {
    return <FcSkeleton className="h-[52px]" />;
  }

  return (
    <div className="flex items-stretch" style={{ height: 52 }}>
      <Stat
        first
        label="Rules fired this run"
        sub={activeRuleCount !== undefined ? `of ${activeRuleCount} active` : "distinct rule versions applied"}
      >
        {rulesFired === undefined ? "—" : <CountUp value={rulesFired} />}
      </Stat>
      <Stat
        label="False auto-resolutions"
        sub={evalQ.data ? "against ground truth" : "no evaluation for this run"}
        tone={evalQ.data && evalQ.data.false_auto_resolutions === 0 ? "ok" : evalQ.data ? "bad" : undefined}
      >
        {evalQ.data ? (
          <>
            <CountUp value={evalQ.data.false_auto_resolutions} /> wrong
          </>
        ) : (
          "—"
        )}
      </Stat>
      <Stat
        label="Declined to decide"
        sub={declined !== undefined ? plural(declined.count, "item") : undefined}
        tone={declined && declined.count > 0 ? "warn" : undefined}
      >
        {declined === undefined ? (
          "—"
        ) : (
          <WhyWrap>
            <span className="fc-why-figure">
              <CountUp value={declined.amountPaise} format={(n) => money(Math.round(n))} />
            </span>
            <WhyLabel href="/decisions" />
          </WhyWrap>
        )}
      </Stat>
    </div>
  );
}
