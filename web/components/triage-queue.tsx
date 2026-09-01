"use client";

import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiClient, type components } from "@/lib/client";
import { formatPaise, humanizeSnakeCase } from "@/lib/format";
import { TIER_COLOR, TIER_DOT } from "@/lib/tier";
import { queryKeys } from "@/lib/query-keys";

type ExceptionOut = components["schemas"]["Exception_"];
type ClusterOut = components["schemas"]["Cluster"];

// Mirrors api/routers/exceptions.py's `_RESOLVABLE_FROM`: a resolved,
// written-off or superseded exception is done — PRD §13.8's "row leaving
// the queue on resolve" means gone, not moved to "already handled" (that
// section is for tier=auto, a pipeline decision, not a human one).
const AWAITING_DECISION = new Set<ExceptionOut["status"]>([
  "open",
  "monitoring",
  "snoozed",
  "escalated",
]);

type ActionGroup = ExceptionOut["action_group"];

// What to do, not what went wrong. A category tells you the shape of a
// discrepancy; it does not tell you whether somebody has to act this morning,
// whether the right move is to wait, whether the fix belongs in the daybook,
// or whether nothing in the files can settle it. Those are four different
// working days, and a queue sorted by category interleaves them. Order here is
// the order of the day. Server-computed (`fc/exceptions/action.py`); this
// component renders the grouping it is given and does not invent one.
const ACTION_SECTIONS: { group: ActionGroup; label: string; note: string }[] = [
  { group: "act_today", label: "Act today", note: "a window is closing" },
  { group: "waiting", label: "Waiting", note: "the system will look again" },
  { group: "books_fix", label: "Books fix", note: "the daybook is what changes" },
  {
    group: "cannot_resolve",
    label: "Cannot resolve",
    note: "no file here can settle it",
  },
  // Beside the four, not inside them. Money that arrived and nobody can
  // attribute is not exposure, and putting it under "cannot resolve" makes
  // that section's total read as money at stake when it is sitting in the
  // account.
  {
    group: "unidentified_inflow",
    label: "Unidentified inflows",
    note: "money arrived · nothing at stake",
  },
];

interface QueueRow {
  key: string;
  tier: "auto" | "monitor" | "escalate";
  actionGroup: ActionGroup;
  amountPaise: number;
  title: string;
  subtitle: string;
  exceptionId: string; // the item opened in the evidence pack on click
  eventIds: string[]; // for hover-highlight matching against the bridge
  memberExceptionIds: string[]; // every exception this row represents (cluster or single)
}

/**
 * PRD §13.5's most important layout decision: auto-resolved items collapse
 * below the fold, out of the queue entirely, so a judge sees the queue the
 * human actually works, not every exception the pipeline raised. Needs-you
 * items that share a `cluster_id` collapse into one row — server-side
 * clustering, this component only renders the grouping it's given, and does
 * not tune or filter that grouping to make the collapse look bigger.
 */
export interface QueueSummary {
  /** Raw escalate/monitor exceptions — the actual human-facing count before
   * clustering, never mixed with the auto-resolved population. */
  needsYouTotal: number;
  clusterRows: number;
  standaloneRows: number;
  autoCount: number;
}

export function TriageQueue({
  runId,
  highlightedEventIds,
  gapFilterExceptionIds,
  onClearGapFilter,
  reloadKey,
  selectedExceptionId,
  onSelect,
  onSummary,
}: {
  runId: string;
  highlightedEventIds: string[] | null;
  gapFilterExceptionIds: string[] | null;
  onClearGapFilter: () => void;
  selectedExceptionId: string | null;
  onSelect: (exceptionId: string) => void;
  onSummary?: (summary: QueueSummary) => void;
  /** Bumped after an instruction applies, so the queue re-reads rather than
   * showing rows the database has already resolved. */
  reloadKey?: number;
}) {
  const { data, error: queryError } = useQuery({
    queryKey: [...queryKeys.exceptions(runId, { scope: "triage" }), reloadKey ?? 0],
    queryFn: async () => {
      const [exceptionsRes, clustersRes] = await Promise.all([
        apiClient.GET("/api/v1/exceptions", { params: { query: { run_id: runId, limit: 200 } } }),
        apiClient.GET("/api/v1/clusters", { params: { query: { run_id: runId, limit: 100 } } }),
      ]);
      if (exceptionsRes.error || !exceptionsRes.data) {
        throw new Error("could not load exceptions");
      }
      return {
        exceptions: exceptionsRes.data.items.filter((e) => AWAITING_DECISION.has(e.status)),
        clusters: clustersRes.data?.items ?? [],
      };
    },
  });
  const exceptions = data?.exceptions ?? null;
  const clusters = useMemo(() => data?.clusters ?? [], [data]);
  const error = queryError ? "could not load exceptions" : null;

  const clusterById = useMemo(
    () => new Map(clusters.map((c) => [c.cluster_id, c])),
    [clusters],
  );
  const highlightSet = useMemo(
    () => (highlightedEventIds ? new Set(highlightedEventIds) : null),
    [highlightedEventIds],
  );

  // The true grouping — computed unconditionally, never gated by the gap
  // filter, so `onSummary` always reports the real needs-you/cluster/auto
  // split rather than whatever subset happens to be on screen.
  const { trueNeedsYouRows, handledCount, needsYouTotal } = useMemo(() => {
    if (!exceptions) {
      return {
        trueNeedsYouRows: [] as QueueRow[],
        handledCount: 0,
        needsYouTotal: 0,
      };
    }
    const needsYou = exceptions.filter((e) => e.tier !== "auto");
    const handled = exceptions.filter((e) => e.tier === "auto");
    const seenClusters = new Set<string>();
    const rows: QueueRow[] = [];
    for (const exc of needsYou) {
      if (exc.cluster_id) {
        if (seenClusters.has(exc.cluster_id)) continue;
        seenClusters.add(exc.cluster_id);
        const members = needsYou.filter((e) => e.cluster_id === exc.cluster_id);
        rows.push(
          rowForCluster(clusterById.get(exc.cluster_id) ?? null, members),
        );
      } else {
        rows.push(rowForException(exc));
      }
    }
    return {
      trueNeedsYouRows: rows,
      handledCount: handled.length,
      needsYouTotal: needsYou.length,
    };
  }, [exceptions, clusterById]);

  useEffect(() => {
    if (!exceptions) return;
    const clusterRows = trueNeedsYouRows.filter(
      (r) => r.memberExceptionIds.length > 1,
    ).length;
    onSummary?.({
      needsYouTotal,
      clusterRows,
      standaloneRows: trueNeedsYouRows.length - clusterRows,
      autoCount: handledCount,
    });
    // onSummary is expected to be a stable callback (useState setter or
    // useCallback); omitting it from deps avoids a render loop for callers
    // that pass an inline arrow function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exceptions, trueNeedsYouRows, handledCount, needsYouTotal]);

  const needsYouRows = gapFilterExceptionIds
    ? (exceptions ?? [])
        .filter((e) => gapFilterExceptionIds.includes(e.exception_id))
        .map(rowForException)
    : trueNeedsYouRows;

  if (error) {
    return (
      <div className="text-amber-text border-border bg-card rounded-lg border p-4 text-sm">
        {error}
      </div>
    );
  }
  if (!exceptions) {
    return (
      <div
        className="border-border bg-card h-64 animate-pulse rounded-lg border"
        aria-hidden
      />
    );
  }

  return (
    <section aria-label="Triage queue" className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-text-body text-xs font-semibold uppercase tracking-wide">
          {gapFilterExceptionIds
            ? `Filtered to unexplained gap · ${needsYouRows.length}`
            : `Needs you · ${needsYouRows.length}`}
        </h2>
        {gapFilterExceptionIds && (
          <button
            type="button"
            onClick={onClearGapFilter}
            className="text-primary text-xs font-medium hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            Clear filter
          </button>
        )}
      </div>

      {needsYouRows.length === 0 && (
        <p className="text-text-muted border-border bg-card rounded-lg border border-dashed p-4 text-center text-sm">
          Nothing needs you right now.
        </p>
      )}
      {ACTION_SECTIONS.map((section) => {
        const rows = needsYouRows.filter((r) => r.actionGroup === section.group);
        if (rows.length === 0) return null;
        return (
          <div key={section.group} className="flex flex-col gap-1">
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-text-heading text-[11.5px] font-semibold uppercase tracking-wide">
                {section.label} · {rows.length}
              </span>
              <span className="text-text-muted text-[11px]">{section.note}</span>
            </div>
            <ul className="flex flex-col gap-1">
              {rows.map((row) => (
                <QueueRowItem
                  key={row.key}
                  row={row}
                  selected={row.memberExceptionIds.includes(
                    selectedExceptionId ?? "",
                  )}
                  highlighted={Boolean(
                    highlightSet &&
                    row.eventIds.some((id) => highlightSet.has(id)),
                  )}
                  onSelect={() => onSelect(row.exceptionId)}
                />
              ))}
            </ul>
          </div>
        );
      })}

      {!gapFilterExceptionIds && (
        <details className="mt-2">
          <summary className="text-text-muted hover:text-text-body cursor-pointer select-none text-xs font-medium">
            Already handled · {handledCount}
          </summary>
          <ul className="mt-2 flex flex-col gap-1">
            {exceptions
              .filter((e) => e.tier === "auto")
              .map((e) => {
                const row = rowForException(e);
                return (
                  <QueueRowItem
                    key={row.key}
                    row={row}
                    selected={selectedExceptionId === e.exception_id}
                    highlighted={Boolean(
                      highlightSet &&
                      row.eventIds.some((id) => highlightSet.has(id)),
                    )}
                    onSelect={() => onSelect(row.exceptionId)}
                    muted
                  />
                );
              })}
          </ul>
        </details>
      )}
    </section>
  );
}

function rowForException(exc: ExceptionOut): QueueRow {
  return {
    key: exc.exception_id,
    tier: exc.tier,
    actionGroup: exc.action_group,
    amountPaise: exc.residual_paise,
    title: humanizeSnakeCase(exc.category),
    subtitle: exc.deadline ? `act by ${exc.deadline}` : "no deadline",
    exceptionId: exc.exception_id,
    eventIds: exc.event_ids,
    memberExceptionIds: [exc.exception_id],
  };
}

function rowForCluster(
  cluster: ClusterOut | null,
  members: ExceptionOut[],
): QueueRow {
  const worstTier = members.some((m) => m.tier === "escalate")
    ? "escalate"
    : members.some((m) => m.tier === "monitor")
      ? "monitor"
      : "auto";
  const totalPaise =
    cluster?.total_paise ??
    members.reduce((sum, m) => sum + m.residual_paise, 0);
  const first = members[0];
  // A cluster is as urgent as its most urgent member: burying a closing
  // deadline under "books fix" because the other four members are data entry
  // is exactly the interleaving these sections exist to undo.
  const group =
    ACTION_SECTIONS.map((s) => s.group).find((g) =>
      members.some((m) => m.action_group === g),
    ) ?? "cannot_resolve";
  return {
    key: cluster?.cluster_id ?? first.exception_id,
    tier: worstTier,
    actionGroup: group,
    amountPaise: totalPaise,
    title:
      cluster?.label ||
      `${members.length}× ${humanizeSnakeCase(first.category)}`,
    subtitle: `[CLUSTER] one root cause · ${members.length} items`,
    exceptionId: first.exception_id,
    eventIds: members.flatMap((m) => m.event_ids),
    memberExceptionIds: members.map((m) => m.exception_id),
  };
}

function QueueRowItem({
  row,
  selected,
  highlighted,
  onSelect,
  muted,
}: {
  row: QueueRow;
  selected: boolean;
  highlighted: boolean;
  onSelect: () => void;
  muted?: boolean;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={
          "border-border flex w-full items-start gap-2 rounded-md border px-3 py-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary " +
          (selected
            ? "bg-primary border-primary"
            : highlighted
              ? "bg-neutral-bg border-primary/60"
              : "bg-card hover:bg-neutral-bg")
        }
      >
        <span aria-hidden>{TIER_DOT[row.tier]}</span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span
              className={
                "truncate text-sm font-medium " +
                (muted ? "text-text-body" : "text-text-heading")
              }
            >
              {row.title}
            </span>
            <span
              className={
                "fc-numeric shrink-0 text-sm font-semibold " +
                TIER_COLOR[row.tier]
              }
            >
              {formatPaise(row.amountPaise)}
            </span>
          </span>
          <span className="text-text-muted block text-xs">{row.subtitle}</span>
        </span>
      </button>
    </li>
  );
}
