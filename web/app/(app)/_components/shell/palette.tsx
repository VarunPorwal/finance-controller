"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { Search, ArrowRight, Sparkles } from "lucide-react";
import { ALL_NAV } from "./nav";
import { useShell } from "./shell-context";
import { Kbd } from "../ui";

export function CommandPalette() {
  const { paletteOpen, setPaletteOpen, openAssistant } = useShell();
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (paletteOpen) {
      setQ("");
      setIdx(0);
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [paletteOpen]);

  const items = useMemo(() => {
    const t = q.trim();
    const out: { label: string; hint: string; run: () => void; icon?: "ask" }[] = [];
    if (/^exc_/i.test(t)) out.push({ label: `Open decision ${t}`, hint: "Decisions", run: () => router.push(`/decisions?open=${t}`) });
    if (/^(mch|evt)_/i.test(t)) out.push({ label: `Find record ${t}`, hint: "Records", run: () => router.push(`/records?q=${t}`) });
    if (/^run_/i.test(t)) out.push({ label: `Open run ${t}`, hint: "Run", run: () => router.push(`/run`) });
    for (const n of ALL_NAV) {
      if (!t || n.label.toLowerCase().includes(t.toLowerCase()) || n.question.toLowerCase().includes(t.toLowerCase())) {
        out.push({ label: n.label, hint: n.question, run: () => router.push(n.href) });
      }
    }
    if (t.length > 3 && !/^(exc|mch|evt|run)_/i.test(t)) {
      out.push({ label: `Ask the books: “${t}”`, hint: "Answers cite their SQL", run: () => openAssistant(t), icon: "ask" });
    }
    return out;
  }, [q, router, openAssistant]);

  function go(i: number) {
    const it = items[i];
    if (!it) return;
    setPaletteOpen(false);
    it.run();
  }

  return (
    <AnimatePresence>
      {paletteOpen && (
        <>
          <motion.div
            className="fixed inset-0 z-[60]"
            style={{ background: "rgba(5,5,6,0.6)" }}
            initial={false}
            animate={{ opacity: 1 }}
            onClick={() => setPaletteOpen(false)}
          />
          <motion.div
            className="app-pop fixed left-1/2 top-[18vh] z-[70] w-[560px] max-w-[calc(100vw-32px)] -translate-x-1/2 overflow-hidden"
            initial={false}
            animate={{ opacity: 1 }}
            role="dialog"
            aria-modal
          >
            <div className="flex items-center gap-2.5 border-b px-4 py-3">
              <Search size={15} strokeWidth={1.6} className="app-faint" />
              <input
                ref={inputRef}
                className="flex-1 bg-transparent text-[14px] placeholder:text-[var(--app-ink-3)]"
                placeholder="Type an id, a page, or a question…"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setIdx(0);
                }}
                onKeyDown={(e) => {
                  if (e.key === "ArrowDown") {
                    e.preventDefault();
                    setIdx((i) => Math.min(i + 1, items.length - 1));
                  }
                  if (e.key === "ArrowUp") {
                    e.preventDefault();
                    setIdx((i) => Math.max(i - 1, 0));
                  }
                  if (e.key === "Enter") go(idx);
                  if (e.key === "Escape") setPaletteOpen(false);
                }}
              />
              <Kbd>esc</Kbd>
            </div>
            <ul className="max-h-[360px] overflow-auto p-1.5" role="listbox">
              {items.map((it, i) => (
                <li key={it.label} role="option" aria-selected={i === idx} ref={(el) => { if (i === idx) el?.scrollIntoView({ block: "nearest" }); }}>
                  <button
                    onMouseEnter={() => setIdx(i)}
                    onClick={() => go(i)}
                    className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left"
                    style={{ background: i === idx ? "var(--app-surface-3)" : "transparent" }}
                  >
                    {it.icon === "ask" ? (
                      <Sparkles size={13} strokeWidth={1.6} style={{ color: "var(--fc-accent)" }} />
                    ) : (
                      <ArrowRight size={13} strokeWidth={1.6} className="app-faint" />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px]">{it.label}</span>
                      <span className="app-faint block text-[11px]">{it.hint}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
