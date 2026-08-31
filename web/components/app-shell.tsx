"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ArrowLeftRight,
  TriangleAlert,
  BookOpen,
  Sparkles,
  Target,
  Database,
  Table as TableIcon,
  Settings,
  CircleHelp,
  Search,
  Bell,
} from "lucide-react";
import { useRun } from "@/lib/run-context";
import { formatDurationMs, formatRunTimestamp } from "@/lib/format";
import { cn } from "@/lib/utils";

const WORKSPACE_NAV = [
  { href: "/", label: "Reconcile", icon: ArrowLeftRight },
  { href: "/exceptions", label: "Exceptions", icon: TriangleAlert, badgeKey: "escalated_count" as const },
  { href: "/rules", label: "Rule Book", icon: BookOpen },
  { href: "/activity", label: "Controller Activity", icon: Sparkles },
  { href: "/eval", label: "Evaluation", icon: Target },
];

const DATA_NAV = [
  { href: "/sources", label: "Data Sources", icon: Database },
  { href: "/records", label: "Records", icon: TableIcon },
];

function NavItem({
  href,
  label,
  icon: Icon,
  active,
  badge,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ width: number; height: number }>;
  active: boolean;
  badge?: number;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-[9px] rounded-lg px-2 py-[7px] text-[13px]",
        active ? "bg-primary-tint font-semibold text-primary-active-text" : "font-medium text-nav-inactive-text hover:bg-neutral-bg",
      )}
    >
      <Icon width={16} height={16} />
      <span className="flex-1">{label}</span>
      {typeof badge === "number" && badge > 0 && (
        <span className="rounded-[10px] bg-neutral-bg px-[7px] py-[1px] text-[10.5px] font-semibold text-neutral-text">
          {badge}
        </span>
      )}
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { summary, loading, error } = useRun();

  return (
    <div className="flex min-h-screen bg-background text-text-heading">
      {/* SIDEBAR */}
      <div className="flex w-[212px] flex-none flex-col border-r border-border bg-card px-3 py-4">
        <div className="flex items-center gap-2 px-1.5 pb-5">
          <div className="flex h-6 w-6 items-center justify-center rounded-[7px] bg-primary text-[13px] font-semibold text-white">
            F
          </div>
          <div className="text-[14.5px] font-semibold tracking-[-0.01em]">Finco</div>
        </div>

        <div className="px-2 pb-1.5 text-[10.5px] font-semibold tracking-[0.06em] text-text-muted">
          WORKSPACE
        </div>
        <div className="mb-3.5 flex flex-col gap-px">
          {WORKSPACE_NAV.map((item) => (
            <NavItem
              key={item.href}
              href={item.href}
              label={item.label}
              icon={item.icon}
              active={pathname === item.href}
              badge={
                item.badgeKey && summary ? summary.escalated_count + summary.monitor_count : undefined
              }
            />
          ))}
        </div>

        <div className="px-2 pb-1.5 text-[10.5px] font-semibold tracking-[0.06em] text-text-muted">
          DATA
        </div>
        <div className="flex flex-col gap-px">
          {DATA_NAV.map((item) => (
            <NavItem
              key={item.href}
              href={item.href}
              label={item.label}
              icon={item.icon}
              active={pathname === item.href || pathname.startsWith(item.href + "/")}
            />
          ))}
        </div>

        <div className="mt-auto" />
        <div className="flex flex-col gap-px border-t border-border pt-3">
          <div className="flex cursor-pointer items-center gap-[9px] rounded-lg px-2 py-[7px] text-[13px] font-medium text-nav-inactive-text">
            <Settings width={16} height={16} />
            Settings
          </div>
          <div className="flex cursor-pointer items-center gap-[9px] rounded-lg px-2 py-[7px] text-[13px] font-medium text-nav-inactive-text">
            <CircleHelp width={16} height={16} />
            Help &amp; Support
          </div>
        </div>
      </div>

      {/* MAIN */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="sticky top-0 z-10 flex h-[60px] flex-none items-center gap-4 border-b border-border bg-white/85 px-7 backdrop-blur-sm">
          <div className="flex w-[280px] items-center gap-2 rounded-lg border border-border bg-neutral-bg px-2.5 py-[7px] text-[13px] text-text-muted">
            <Search width={15} height={15} />
            <span className="flex-1">Search anything…</span>
            <span className="text-[11px] text-text-faint">⌘K</span>
          </div>
          <div className="flex-1" />
          <span className="fc-numeric text-xs text-text-muted">
            {loading && "loading run…"}
            {!loading && error && <span className="text-amber-text">{error}</span>}
            {!loading && summary && (
              <>
                Run #{summary.run.run_id.slice(-6)} · {formatRunTimestamp(summary.run.started_at)}
                {summary.run.runtime_ms != null && ` · ${formatDurationMs(summary.run.runtime_ms)}`}
              </>
            )}
          </span>
          <div className="flex h-8 w-8 items-center justify-center rounded-[9px] bg-neutral-bg text-text-body">
            <Bell width={16} height={16} />
          </div>
          <div className="h-5 w-px bg-border" />
          <div className="flex h-[30px] w-[30px] items-center justify-center rounded-full bg-primary-tint text-[11.5px] font-semibold text-primary-active-text">
            VP
          </div>
        </div>

        <main className="max-w-[1400px] px-7 pt-6 pb-12">{children}</main>
      </div>
    </div>
  );
}
