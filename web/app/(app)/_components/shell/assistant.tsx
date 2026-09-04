"use client";

// Ask the books. Every answer cites the SQL it ran; amounts come from the
// database, never from the model's own arithmetic; it can say it cannot
// answer, and that refusal is a designed state.

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Sparkles, CornerDownLeft, Code2, Ban, Database } from "lucide-react";
import { useCurrentRun, writes, errorMessage, type AskOut } from "../../_lib/api";
import { SlideOver } from "../motion";
import { Button, Pill, Spinner } from "../ui";
import { useShell } from "./shell-context";

/** A neutral or accent-tinted pill, styled with --fc-* tokens (Ask the books
 * is not part of the app "model" accent family — it uses the shell's own
 * accent color, never violet). */
function FcPill({ tone = "neutral", children }: { tone?: "neutral" | "accent"; children: React.ReactNode }) {
  return (
    <span
      className="app-pill"
      style={
        tone === "accent"
          ? { background: "var(--fc-accent-dim)", borderColor: "var(--fc-accent-dim)", color: "var(--fc-accent)" }
          : undefined
      }
    >
      {children}
    </span>
  );
}

interface Turn {
  id: number;
  question: string;
  answer?: AskOut;
  error?: string;
  pending?: boolean;
}

const SUGGESTED = [
  "How much did we pay in MDR this period, by payment method?",
  "Which settlements have not been credited to the bank yet?",
  "List the five largest open exceptions with their deadlines.",
  "What is the total GST on MDR we can claim as input credit?",
];

export function Assistant() {
  const { assistantOpen, closeAssistant, assistantPrefill } = useShell();
  const { runId } = useCurrentRun();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (assistantOpen) {
      setText(assistantPrefill);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [assistantOpen, assistantPrefill]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function ask(q: string) {
    const question = q.trim();
    if (!question) return;
    const id = Date.now();
    setTurns((t) => [...t, { id, question, pending: true }]);
    setText("");
    const res = await writes.ask({ question, run_id: runId ?? null, history: turns.filter((t) => t.answer?.answer).slice(-4).map((t) => ({ question: t.question, answer: t.answer!.answer! })) });
    setTurns((t) =>
      t.map((turn) =>
        turn.id === id
          ? res.error || !res.data
            ? { ...turn, pending: false, error: errorMessage(res.error) }
            : { ...turn, pending: false, answer: res.data }
          : turn,
      ),
    );
  }

  return (
    <SlideOver
      open={assistantOpen}
      onClose={closeAssistant}
      width={560}
      header={
        <div className="flex items-center justify-between border-b px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg" style={{ background: "var(--fc-accent-dim)", color: "var(--fc-accent)" }}>
              <Sparkles size={14} strokeWidth={1.6} />
            </span>
            <div>
              <div className="text-[13.5px] font-medium">Ask the books</div>
              <div className="app-faint text-[11px]">Read-only. The query behind each answer is shown.</div>
            </div>
          </div>
          <FcPill tone="accent">Read-only</FcPill>
        </div>
      }
      footer={
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void ask(text);
          }}
          className="flex items-end gap-2"
        >
          <textarea
            ref={inputRef}
            className="app-input"
            rows={2}
            placeholder="Ask about this period's money…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void ask(text);
              }
            }}
          />
          <Button variant="primary" type="submit" disabled={!text.trim()}>
            <CornerDownLeft size={13} /> Ask
          </Button>
        </form>
      }
    >
      <div className="flex flex-col gap-4 px-5 py-4">
        {turns.length === 0 && (
          <div className="flex flex-col gap-2">
            <div className="app-eyebrow">Try one</div>
            {SUGGESTED.map((s) => (
              <button
                key={s}
                onClick={() => void ask(s)}
                className="app-inset px-3 py-2 text-left text-[12.5px] text-[var(--app-ink-2)] transition-colors hover:border-[var(--app-line-2)] hover:text-[var(--app-ink)]"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        <AnimatePresence initial={false}>
          {turns.map((t) => (
            <motion.div key={t.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-2">
              <div className="self-end rounded-xl rounded-br-sm bg-[var(--app-surface-3)] px-3.5 py-2 text-[13px]">{t.question}</div>
              {t.pending && (
                <div className="app-faint flex items-center gap-2 text-[12px]">
                  <Spinner size={12} /> Writing the query…
                </div>
              )}
              {t.error && <div className="rounded-lg border border-[var(--app-bad-line)] bg-[var(--app-bad-soft)] px-3 py-2 text-[12.5px] text-[var(--app-bad)]">{t.error}</div>}
              {t.answer && <Answer a={t.answer} />}
            </motion.div>
          ))}
        </AnimatePresence>
        <div ref={bottomRef} />
      </div>
    </SlideOver>
  );
}

function Answer({ a }: { a: AskOut }) {
  const [showSql, setShowSql] = useState(false);
  if (!a.answerable) {
    return (
      <div
        className="px-4 py-3.5"
        style={{
          background: "var(--fc-accent-dim)",
          border: "1px solid var(--fc-accent-dim)",
          borderRadius: 12,
        }}
      >
        <div className="flex items-center gap-2 text-[13px] font-medium" style={{ color: "var(--fc-accent)" }}>
          <Ban size={14} strokeWidth={1.6} /> This cannot be answered from the books
        </div>
        <div className="app-muted mt-1 text-[12.5px]">{a.refusal_reason ?? "The question cannot be answered from the reconciliation state."}</div>
      </div>
    );
  }
  const cols = a.rows.length ? Object.keys(a.rows[0]) : [];
  return (
    <div className="app-card px-4 py-3.5">
      <div className="text-[13px] leading-relaxed">{a.answer}</div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {a.sql && (
          <button onClick={() => setShowSql((v) => !v)} className="app-btn app-btn-sm app-btn-ghost">
            <Code2 size={12} /> {showSql ? "Hide" : "Show"} SQL
          </button>
        )}
        <Pill tone="neutral">
          <Database size={10} strokeWidth={1.6} /> {a.row_count} row{a.row_count === 1 ? "" : "s"}
        </Pill>
        {a.tool && <Pill tone="neutral">via {a.tool}</Pill>}
        {a.cached && <Pill tone="neutral">cached</Pill>}
        {a.model_used && <FcPill tone="accent">{a.model_used}</FcPill>}
      </div>
      <AnimatePresence>
        {showSql && a.sql && (
          <motion.pre
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="app-inset mono mt-3 overflow-x-auto whitespace-pre-wrap px-3 py-2.5 text-[11.5px] leading-relaxed text-[var(--app-ink-2)]"
          >
            {a.sql}
          </motion.pre>
        )}
      </AnimatePresence>
      {a.show_table && cols.length > 0 && (
        <div className="app-inset mt-3 max-h-[260px] overflow-auto">
          <table className="app-table">
            <thead>
              <tr>
                {cols.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {a.rows.slice(0, 50).map((r, i) => (
                <tr key={i}>
                  {cols.map((c) => (
                    <td key={c} className="mono text-[11.5px]">
                      {String(r[c] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
