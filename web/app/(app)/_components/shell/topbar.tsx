"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Search, Play, ChevronDown, Menu } from "lucide-react";
import { activeNav } from "./nav";
import { useAgentHealth, useCurrentRun } from "../../_lib/api";
import { formatDurationMs, formatDateTime, formatCount, shortId } from "../../_lib/format";
import { useShell } from "./shell-context";

export function Topbar() {
  const pathname = usePathname();
  const nav = activeNav(pathname);
  const { run, summary, loading } = useCurrentRun();
  const { data: health } = useAgentHealth();
  const { setPaletteOpen, setSidebarOpen } = useShell();

  return (
    <header
      className="flex h-[52px] shrink-0 items-center gap-3 px-3 sm:px-5"
      style={{ borderBottom: "1px solid var(--fc-border)", background: "color-mix(in srgb, var(--fc-bg) 80%, transparent)", backdropFilter: "blur(6px)" }}
    >
      <button
        onClick={() => setSidebarOpen(true)}
        className="fc-btn app-nav-toggle shrink-0 md:hidden"
        style={{ padding: "6px 8px" }}
        aria-label="Open navigation"
      >
        <Menu size={16} strokeWidth={1.6} />
      </button>

      <div className="min-w-0 flex-1 overflow-hidden">
        <div className="flex items-baseline gap-2 whitespace-nowrap">
          <span className="fc-strong shrink-0" style={{ fontSize: 13.5, fontWeight: 500 }}>{nav?.label ?? "Finco"}</span>
        </div>
      </div>

      {run ? (
        <Link
          href="/run"
          className="fc-card flex items-center gap-2.5 whitespace-nowrap"
          style={{ borderRadius: 10, padding: "6px 12px", fontSize: 12 }}
          title="This run. Click to see how it read the evidence."
        >
          <span className="fc-dot" style={{ background: "var(--fc-ok)" }} />
          <span className="fc-num fc-muted hidden sm:inline">run·{shortId(run.run_id)}</span>
          <span className="fc-faint hidden xl:inline">{formatDateTime(run.started_at)}</span>
          <span className="fc-faint hidden xl:inline">·</span>
          <span className="fc-num hidden xl:inline">{formatCount(summary?.event_count ?? run.record_count ?? 0)} rows</span>
          {run.runtime_ms != null && (
            <span className="fc-num hidden sm:inline">{formatDurationMs(run.runtime_ms)}</span>
          )}
          <ChevronDown size={12} strokeWidth={1.6} className="fc-faint" />
        </Link>
      ) : (
        <span className="fc-faint hidden shrink-0 whitespace-nowrap sm:inline" style={{ fontSize: 12 }}>{loading ? "Loading run…" : "No run yet"}</span>
      )}

      {health && (
        <span
          className="fc-chip hidden 2xl:inline-flex items-center gap-1.5"
          style={{ color: health.degraded ? "var(--fc-warn)" : "var(--fc-accent)" }}
        >
          <span className="fc-dot" style={{ background: health.degraded ? "var(--fc-warn)" : "var(--fc-accent)" }} />
          {health.degraded ? "Model degraded" : health.mode === "off" ? "Model off" : health.mode === "cache_only" ? "Model cached" : "Model live"}
        </span>
      )}

      <button
        onClick={() => setPaletteOpen(true)}
        className="hidden h-8 w-[210px] shrink-0 items-center gap-2 text-left transition-colors 2xl:flex hover:bg-[var(--fc-divider)]"
        style={{
          borderRadius: 9,
          border: "1px solid var(--fc-border)",
          background: "var(--fc-hover)",
          color: "var(--fc-text-3)",
          fontSize: 12,
          padding: "0 10px",
        }}
      >
        <Search size={13} strokeWidth={1.6} />
        <span className="flex-1">Jump to id</span>
        <kbd
          style={{
            display: "inline-flex",
            alignItems: "center",
            height: 18,
            padding: "0 5px",
            borderRadius: 4,
            border: "1px solid var(--fc-border)",
            background: "var(--fc-divider)",
            fontSize: 10.5,
            color: "var(--fc-text-3)",
          }}
        >
          ⌘K
        </kbd>
      </button>

      <Link href="/run" className="fc-btn shrink-0" style={{ fontSize: 13 }} title="Run reconciliation">
        <Play size={13} strokeWidth={1.6} />
        <span className="hidden sm:inline">Run reconciliation</span>
      </Link>
    </header>
  );
}
