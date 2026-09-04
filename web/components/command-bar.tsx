"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeftRight, CornerDownLeft, Search, Sparkles } from "lucide-react";
import { NAV_PRIMARY, NAV_SECONDARY, NAV_HIDDEN } from "@/lib/nav";
import { cn } from "@/lib/utils";

interface Item {
  id: string;
  label: string;
  hint?: string;
  group: "Go to" | "Actions" | "Ask";
  icon?: React.ReactNode;
  run: () => void;
}

/**
 * The command dock: one box that goes anywhere and asks anything. A typed
 * sentence that matches no screen becomes a question for the books, routed
 * to /ask where the model answers over deterministic SQL.
 */
export function CommandBar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      const opener = document.activeElement as HTMLElement | null;
      setQuery("");
      setIndex(0);
      const t = setTimeout(() => inputRef.current?.focus(), 10);
      return () => {
        clearTimeout(t);
        opener?.focus?.();
      };
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const go = (href: string) => () => {
      router.push(href);
      onClose();
    };
    const nav: Item[] = [...NAV_PRIMARY, ...NAV_SECONDARY].map((n) => ({
      id: n.href,
      label: n.label,
      hint: n.hint,
      group: "Go to",
      icon: <n.icon width={14} height={14} />,
      run: go(n.href),
    }));
    const hidden: Item[] = NAV_HIDDEN.map((n) => ({
      id: n.href,
      label: n.label,
      hint: n.hint,
      group: "Go to",
      icon: <Search width={14} height={14} />,
      run: go(n.href),
    }));
    const actions: Item[] = [
      {
        id: "act:reconcile",
        label: "Run reconciliation",
        hint: "Replay this run under the current rule book",
        group: "Actions",
        icon: <ArrowLeftRight width={14} height={14} />,
        run: go("/reconcile"),
      },
    ];
    const q = query.trim().toLowerCase();
    const all = [...nav, ...hidden, ...actions];
    const matched = q
      ? all.filter((i) => i.label.toLowerCase().includes(q) || (i.hint ?? "").toLowerCase().includes(q))
      : all;
    const ask: Item[] = q
      ? [
          {
            id: "ask",
            label: `Ask the books: “${query.trim()}”`,
            hint: "Answered over deterministic SQL, then narrated",
            group: "Ask",
            icon: <Sparkles width={14} height={14} />,
            run: () => {
              router.push(`/ask?q=${encodeURIComponent(query.trim())}`);
              onClose();
            },
          },
        ]
      : [];
    return [...matched, ...ask];
  }, [query, router, onClose]);

  useEffect(() => {
    setIndex(0);
  }, [query]);

  if (!open) return null;

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setIndex((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      items[index]?.run();
    } else if (e.key === "Escape") {
      onClose();
    }
  }

  let lastGroup: string | null = null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 pt-[14vh] backdrop-blur-[2px]" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command bar"
        className="w-full max-w-[600px] overflow-hidden rounded-[14px] border border-line-strong bg-surface shadow-[var(--shadow-pop)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search width={15} height={15} className="text-ink-3" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Go to a screen, or ask a question of the books…"
            aria-label="Command"
            className="h-[50px] flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-3"
          />
          <span className="kbd">esc</span>
        </div>
        <ul className="max-h-[52vh] overflow-y-auto py-2">
          {items.length === 0 && <li className="px-4 py-6 text-center text-[12.5px] text-ink-3">Nothing matches.</li>}
          {items.map((item, i) => {
            const showGroup = item.group !== lastGroup;
            lastGroup = item.group;
            const active = i === index;
            const isAsk = item.group === "Ask";
            return (
              <li key={item.id}>
                {showGroup && <div className="label px-4 pt-2 pb-1">{item.group}</div>}
                <button
                  type="button"
                  onMouseEnter={() => setIndex(i)}
                  onClick={item.run}
                  className={cn(
                    "flex w-full items-center gap-3 px-4 py-2 text-left transition-colors",
                    active ? (isAsk ? "bg-model-soft" : "bg-surface-2") : "",
                  )}
                >
                  <span
                    className={cn(
                      "flex h-7 w-7 items-center justify-center rounded-[7px] border",
                      isAsk ? "border-model-line bg-model-soft text-model" : "border-line bg-bg text-ink-3",
                    )}
                  >
                    {item.icon}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate text-[13px]", isAsk ? "text-model" : "text-ink")}>{item.label}</span>
                    {item.hint && <span className="block truncate text-[11px] text-ink-3">{item.hint}</span>}
                  </span>
                  {active && <CornerDownLeft width={13} height={13} className="text-ink-3" />}
                </button>
              </li>
            );
          })}
        </ul>
        <div className="flex items-center gap-3 border-t border-line px-4 py-2 text-[10.5px] text-ink-3">
          <span>
            <span className="kbd">↑↓</span> move
          </span>
          <span>
            <span className="kbd">↵</span> open
          </span>
          <span className="ml-auto text-model">A violet row is answered by a model, over deterministic data.</span>
        </div>
      </div>
    </div>
  );
}
