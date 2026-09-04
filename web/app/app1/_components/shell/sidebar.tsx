"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sparkles, Sun, Moon } from "lucide-react";
import { clsx } from "clsx";
import { DAILY, EVIDENCE, SETTINGS, type NavItem } from "./nav";
import { useCashBridge, useCurrentRun, useSuggestions } from "../../_lib/api";
import { money } from "../../_lib/format";
import { useShell } from "./shell-context";
import { useTheme } from "./theme";

function Item({ item, active, badge }: { item: NavItem; active: boolean; badge?: React.ReactNode }) {
  const Icon = item.icon;
  return (
    <Link href={item.href} className={clsx("fc-nav", active && "is-on")} title={item.question}>
      <Icon size={15} strokeWidth={1.6} className={active ? "" : "fc-faint"} style={active ? { color: "var(--fc-accent)" } : undefined} />
      <span className="flex-1">{item.label}</span>
      {badge}
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { runId } = useCurrentRun();
  const { data: bridge } = useCashBridge(runId);
  const { data: suggestions } = useSuggestions();
  const { openAssistant } = useShell();
  const { theme, toggle } = useTheme();

  const isActive = (href: string) => (href === "/app1" ? pathname === "/app1" : pathname.startsWith(href));

  return (
    <aside className="fc-rail" style={{ width: 286, flexShrink: 0, borderRight: "1px solid var(--fc-border)" }}>
      <Link href="/landing" className="fc-brand">
        <span className="fc-mark">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden>
            <path d="M3.5 4.2 8 8m-4.5 3.8L8 8m5-0.2L8 8" stroke="var(--fc-text-3)" strokeWidth="1.2" strokeLinecap="round" opacity="0.7" />
            <circle cx="3.5" cy="4.2" r="1.7" fill="#6ea8ff" />
            <circle cx="3.5" cy="11.8" r="1.7" fill="#f49ac1" />
            <circle cx="13" cy="7.8" r="1.7" fill="#d6dce6" />
            <circle cx="8" cy="8" r="2" fill="#3ddc97" />
          </svg>
        </span>
        <span>
          <span className="fc-strong block" style={{ fontSize: 13.5, lineHeight: 1 }}>Finco</span>
          <span className="fc-faint block" style={{ fontSize: 10.5, lineHeight: 1, marginTop: 4 }}>Finance controller</span>
        </span>
      </Link>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div className="fc-label" style={{ padding: "0 10px", marginBottom: 4 }}>Daily work</div>
        <nav className="flex flex-col gap-0">
          {DAILY.map((item) => (
            <Item
              key={item.href}
              item={item}
              active={isActive(item.href)}
              badge={
                item.href === "/app1/decisions" && bridge ? (
                  <span className="fc-chip fc-num" style={{ color: "var(--fc-text-2)" }}>
                    {money(bridge.unexplained_paise, { compact: true, whole: true })}
                  </span>
                ) : item.href === "/app1/rules" && suggestions && suggestions.length > 0 ? (
                  <span className="fc-chip fc-num" style={{ color: "var(--fc-text-2)" }}>
                    {suggestions.length}
                  </span>
                ) : undefined
              }
            />
          ))}
        </nav>

        <div className="fc-divider" style={{ margin: "8px 0" }} />
        <div className="fc-label" style={{ padding: "0 10px", marginBottom: 4 }}>Evidence</div>
        <nav className="flex flex-col gap-0">
          {EVIDENCE.map((item) => (
            <Item key={item.href} item={item} active={isActive(item.href)} />
          ))}
        </nav>
      </div>

      <div className="mt-auto flex flex-shrink-0 flex-col gap-1.5 pt-2">
        <button
          onClick={() => openAssistant()}
          className="fc-card flex items-center gap-2.5 text-left"
          style={{ borderRadius: 11, padding: "8px 10px" }}
        >
          <span className="flex h-6 w-6 items-center justify-center rounded-md" style={{ background: "var(--fc-accent-dim)", color: "var(--fc-accent)" }}>
            <Sparkles size={13} strokeWidth={1.6} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="fc-strong block" style={{ fontSize: 12.5, fontWeight: 500 }}>Ask the books</span>
            <span className="fc-faint block" style={{ fontSize: 10.5 }}>Ask about this period&apos;s money</span>
          </span>
        </button>

        <button
          onClick={toggle}
          className="fc-nav w-full"
          style={{ background: "transparent", border: 0, cursor: "pointer" }}
          title="Switch theme"
        >
          {theme === "dark" ? <Moon size={15} strokeWidth={1.6} className="fc-faint" /> : <Sun size={15} strokeWidth={1.6} className="fc-faint" />}
          <span className="flex-1 text-left">{theme === "dark" ? "Dark" : "Light"}</span>
          <span
            aria-hidden
            style={{
              position: "relative",
              width: 30,
              height: 17,
              borderRadius: 999,
              background: theme === "dark" ? "var(--fc-divider)" : "var(--fc-accent)",
              transition: "background 140ms ease",
            }}
          >
            <span
              style={{
                position: "absolute",
                top: 2,
                left: theme === "dark" ? 2 : 15,
                width: 13,
                height: 13,
                borderRadius: "50%",
                background: "#fff",
                transition: "left 140ms ease",
              }}
            />
          </span>
        </button>

        <Item item={SETTINGS} active={isActive(SETTINGS.href)} />
      </div>
    </aside>
  );
}
