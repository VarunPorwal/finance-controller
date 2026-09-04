"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Search } from "lucide-react";
import { motion } from "framer-motion";
import { AnimatedNumber } from "@/components/ui/animated-number";
import { useRun } from "@/lib/run-context";
import { NAV_PRIMARY, NAV_SECONDARY, NAV_HIDDEN, isActive, type NavItem } from "@/lib/nav";
import { formatDurationMs, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";
import { queryKeys } from "@/lib/query-keys";
import { fetchSourcesBundle } from "@/app/(app)/ingest/loader";
import { fetchRecordsBundle } from "@/app/(app)/records/loader";
import { fetchRulesAndSuggestions } from "@/app/(app)/rules/loader";
import { fetchActivityBundle, fetchHomeBundle } from "@/lib/page-data";
import { fetchAuditBundle } from "@/app/(app)/audit/loader";
import { fetchEvalBundle } from "@/app/(app)/eval/loader";
import { fetchCashBridge } from "@/app/(app)/cash/loader";
import { StatusStrip } from "@/components/status-strip";
import { CommandBar } from "@/components/command-bar";

// A prefetch per nav item, keyed the same as the screen's own useQuery so a
// hover primes the exact cache entry the click will read.
const PREFETCH: Record<string, (runId: string) => { queryKey: readonly unknown[]; queryFn: () => Promise<unknown> } | null> = {
  "/": (runId) => ({ queryKey: queryKeys.homeHistory(runId), queryFn: () => fetchHomeBundle(runId) }),
  "/exceptions": () => null,
  "/reconcile": (runId) => ({ queryKey: queryKeys.cashBridge(runId), queryFn: () => fetchCashBridge(runId) }),
  "/rules": () => ({ queryKey: queryKeys.rules({}), queryFn: fetchRulesAndSuggestions }),
  "/activity": (runId) => ({ queryKey: queryKeys.activityPage(runId), queryFn: () => fetchActivityBundle(runId) }),
  "/eval": (runId) => ({ queryKey: queryKeys.evalBundle(runId), queryFn: () => fetchEvalBundle(runId) }),
  "/cash": (runId) => ({ queryKey: queryKeys.cashBridge(runId), queryFn: () => fetchCashBridge(runId) }),
  "/audit": (runId) => ({ queryKey: queryKeys.auditPage(runId), queryFn: () => fetchAuditBundle(runId) }),
  "/ingest": (runId) => ({ queryKey: queryKeys.sources(runId), queryFn: () => fetchSourcesBundle(runId) }),
  "/records": (runId) => ({ queryKey: queryKeys.records(runId), queryFn: () => fetchRecordsBundle(runId) }),
};

function BrandMark() {
  return (
    <span className="relative flex h-[26px] w-[26px] items-center justify-center rounded-[8px] border border-line-strong bg-surface-2">
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
        <path d="M3.5 4.2 8 8m-4.5 3.8L8 8m5-0.2L8 8" stroke="var(--ink-3)" strokeWidth="1.2" strokeLinecap="round" />
        <circle cx="3.5" cy="4.2" r="1.7" fill="var(--src-razorpay)" />
        <circle cx="3.5" cy="11.8" r="1.7" fill="var(--src-ledger)" />
        <circle cx="13" cy="7.8" r="1.7" fill="var(--src-bank)" />
        <circle cx="8" cy="8" r="2" fill="var(--ok)" />
      </svg>
    </span>
  );
}

function NavLink({
  item,
  active,
  badge,
  onHover,
}: {
  item: NavItem;
  active: boolean;
  badge?: number;
  onHover?: () => void;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onMouseEnter={onHover}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex h-[32px] items-center gap-2.5 rounded-[7px] px-2.5 text-[12.5px] transition-colors",
        active ? "bg-surface-3 font-medium text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
      )}
    >
      {active && (
        <motion.span
          layoutId="nav-active"
          transition={{ type: "tween", ease: [0.23, 1, 0.32, 1], duration: 0.2 }}
          className="absolute top-2 bottom-2 -left-3 w-[2px] rounded-full bg-accent"
          aria-hidden
        />
      )}
      <Icon width={15} height={15} className={cn("transition-colors duration-150", active ? "text-accent" : "text-ink-3 group-hover:text-ink-2")} />
      <span className="flex-1 truncate">{item.label}</span>
      {typeof badge === "number" && badge > 0 && (
        <span className="num rounded-[5px] border border-[rgba(255,107,107,0.3)] bg-bad-soft px-1.5 text-[10.5px] font-semibold text-bad">
          <AnimatedNumber value={badge} />
        </span>
      )}
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { summary, loading, error } = useRun();
  const queryClient = useQueryClient();
  const runId = summary?.run.run_id;
  const [commandOpen, setCommandOpen] = useState(false);

  function prefetch(href: string) {
    if (!runId) return;
    const entry = PREFETCH[href]?.(runId);
    if (entry) void queryClient.prefetchQuery(entry);
  }

  // Warm every tab's cache once a run_id is known, so the first click on any
  // screen is instant instead of waiting on a fetch that has not started.
  const warmedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!runId || warmedFor.current === runId) return;
    warmedFor.current = runId;
    for (const href of Object.keys(PREFETCH)) {
      const entry = PREFETCH[href]?.(runId);
      if (entry) void queryClient.prefetchQuery(entry);
    }
  }, [runId, queryClient]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const current =
    [...NAV_PRIMARY, ...NAV_SECONDARY].find((n) => isActive(pathname, n.href)) ??
    NAV_HIDDEN.find((n) => isActive(pathname, n.href)) ??
    null;
  const needsYou = summary ? summary.escalated_count + summary.monitor_count : undefined;

  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-20 flex w-[232px] flex-col border-r border-line bg-surface px-3 py-4">
        <Link href="/" className="flex items-center gap-2.5 px-1.5">
          <BrandMark />
          <div className="leading-tight">
            <div className="text-[13.5px] font-semibold tracking-[-0.01em]">Finco</div>
            <div className="text-[10.5px] text-ink-3">AI finance controller</div>
          </div>
        </Link>

        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          className="mt-4 flex h-[32px] w-full items-center gap-2 rounded-[8px] border border-line-strong bg-bg px-2.5 text-[12px] text-ink-3 transition-colors hover:border-[#353c4a] hover:text-ink-2"
        >
          <Search width={13} height={13} />
          <span className="flex-1 truncate text-left">Search or ask</span>
          <span className="kbd">⌘K</span>
        </button>

        <nav className="mt-4 flex flex-col gap-px">
          {NAV_PRIMARY.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              active={isActive(pathname, item.href)}
              badge={item.badge === "needs_you" ? needsYou : undefined}
              onHover={() => prefetch(item.href)}
            />
          ))}
        </nav>

        <div className="my-3 h-px bg-line" />

        <nav className="flex flex-col gap-px">
          {NAV_SECONDARY.map((item) => (
            <NavLink key={item.href} item={item} active={isActive(pathname, item.href)} onHover={() => prefetch(item.href)} />
          ))}
        </nav>

        <div className="mt-auto flex flex-col gap-2">
          <Link
            href="/landing"
            className="flex items-center justify-between rounded-[7px] px-2.5 py-1.5 text-[11.5px] text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink-2"
          >
            Product page
            <ArrowUpRight width={12} height={12} />
          </Link>
          <div className="flex items-center gap-2.5 rounded-[8px] border border-line bg-bg px-2.5 py-2">
            <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent-soft text-[10.5px] font-semibold text-accent">
              VP
            </span>
            <div className="min-w-0 leading-tight">
              <div className="truncate text-[12px] font-medium text-ink">Varun Porwal</div>
              <div className="truncate text-[10.5px] text-ink-3">Demo tenant · controller</div>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col pl-[232px]">
        <header className="sticky top-0 z-10 flex h-[52px] items-center gap-4 border-b border-line bg-bg/85 px-7 backdrop-blur-md">
          <div className="min-w-0">
            <div className="text-[13px] font-semibold">{current?.label ?? "Finco"}</div>
            {current?.hint && <div className="text-[11px] text-ink-3">{current.hint}</div>}
          </div>
          <div className="flex-1" />
          <StatusStrip />
          <div className="h-5 w-px bg-line-strong" />
          <Link
            href="/reconcile"
            className="num flex items-center gap-2 rounded-[7px] border border-line bg-surface px-2.5 py-1.5 text-[11.5px] text-ink-2 transition-colors hover:border-line-strong"
            title="Open the reconciliation for this run"
          >
            {loading && <span className="text-ink-3">loading run</span>}
            {!loading && error && <span className="text-warn">{error}</span>}
            {!loading && summary && (
              <>
                <span className={cn("h-1.5 w-1.5 rounded-full", summary.run.status === "complete" ? "bg-ok" : "bg-warn pulse-dot")} />
                <span className="text-ink">Run {shortId(summary.run.run_id)}</span>
                <span className="text-ink-3">{formatDateTime(summary.run.started_at)}</span>
                {summary.run.runtime_ms != null && <span className="text-ink-3">{formatDurationMs(summary.run.runtime_ms)}</span>}
              </>
            )}
          </Link>
        </header>

        <main className="ground flex-1 px-7 pt-6 pb-16">
          <div className="mx-auto w-full max-w-[1440px]">{children}</div>
        </main>
      </div>

      <CommandBar open={commandOpen} onClose={() => setCommandOpen(false)} />
    </div>
  );
}
