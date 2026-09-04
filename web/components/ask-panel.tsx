"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Sparkles } from "lucide-react";
import { motion } from "framer-motion";
import { apiClient, type components } from "@/lib/client";
import { useRun } from "@/lib/run-context";
import { cn } from "@/lib/utils";

type AskOut = components["schemas"]["AskOut"];
type AskTurnIn = components["schemas"]["AskTurnIn"];

// The four question shapes a single-vector retrieval cannot answer.
const SUGGESTED_QUESTIONS = [
  { label: "Aggregate", question: "How much is at risk right now?" },
  { label: "Group-by", question: "Break down open exceptions by category." },
  { label: "Run diff", question: "What changed since the last run?" },
  { label: "Counterfactual", question: "How many matches would have auto-closed at a 0.90 threshold instead?" },
];

const HISTORY_TURNS = 5;

interface Message {
  id: number;
  role: "user" | "assistant";
  text: string;
  result?: AskOut;
}

/**
 * A conversation, with the SQL or diff mechanism folded behind "how I got
 * this". The last five turns travel with each request so a follow-up can
 * resolve "those" without the user noticing a fresh query ran.
 */
export function AskPanel({ initialQuestion }: { initialQuestion?: string | null }) {
  const { summary } = useRun();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [asking, setAsking] = useState(false);
  const nextId = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const askedInitial = useRef<string | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, asking]);

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed || asking) return;
    setInput("");

    const history: AskTurnIn[] = [];
    for (let i = 0; i < messages.length - 1; i++) {
      const userMsg = messages[i];
      const assistantMsg = messages[i + 1];
      if (userMsg.role === "user" && assistantMsg.role === "assistant" && assistantMsg.result) {
        history.push({ question: userMsg.text, answer: assistantMsg.result.answer ?? assistantMsg.result.refusal_reason ?? "" });
        i++;
      }
    }

    setMessages((prev) => [...prev, { id: nextId.current++, role: "user", text: trimmed }]);
    setAsking(true);
    try {
      const { data, error } = await apiClient.POST("/api/v1/agent/ask", {
        body: { question: trimmed, run_id: summary?.run.run_id ?? null, history: history.slice(-HISTORY_TURNS) },
      });
      const result: AskOut =
        data ??
        ({
          answerable: false,
          refusal_reason: error ? "Could not reach the API." : "No answer.",
          rows: [],
          row_count: 0,
          show_table: false,
          cached: false,
          truncated: false,
        } as AskOut);
      setMessages((prev) => [
        ...prev,
        {
          id: nextId.current++,
          role: "assistant",
          text: result.answerable ? (result.answer ?? "") : (result.refusal_reason ?? "I can't answer that from your reconciliation data."),
          result,
        },
      ]);
    } catch {
      setMessages((prev) => [...prev, { id: nextId.current++, role: "assistant", text: "Could not reach the API." }]);
    } finally {
      setAsking(false);
    }
  }

  // A question handed over from the command bar or the Overview teaser.
  useEffect(() => {
    if (initialQuestion && askedInitial.current !== initialQuestion) {
      askedInitial.current = initialQuestion;
      void ask(initialQuestion);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  return (
    <div className="panel-model flex h-full flex-col overflow-hidden">
      <div ref={scrollRef} className="flex-1 space-y-4 overflow-y-auto px-5 py-5">
        {messages.length === 0 && !asking && (
          <div className="mx-auto max-w-[560px] pt-10 text-center">
            <p className="text-[15px] font-semibold text-ink">Ask anything the books can answer.</p>
            <p className="mt-1 text-[12px] text-ink-3">Aggregates, breakdowns, what changed between runs, and what-ifs. A refusal is a correct answer, not an error.</p>
            <div className="mt-5 grid grid-cols-2 gap-2">
              {SUGGESTED_QUESTIONS.map((q) => (
                <button
                  key={q.label}
                  type="button"
                  onClick={() => void ask(q.question)}
                  className="rounded-[10px] border border-model-line bg-bg/60 px-3 py-2.5 text-left transition-colors hover:bg-model-soft"
                >
                  <div className="label text-model">{q.label}</div>
                  <div className="mt-1 text-[12px] text-ink-2">{q.question}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}

        {asking && (
          <div className="flex items-end gap-2">
            <Avatar role="assistant" />
            <div className="flex items-center gap-1 rounded-[10px] border border-model-line bg-bg px-3 py-2.5">
              <TypingDot delay="0ms" />
              <TypingDot delay="150ms" />
              <TypingDot delay="300ms" />
            </div>
          </div>
        )}
      </div>

      <div className="border-t border-model-line bg-bg/40 px-4 py-3">
        {messages.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {SUGGESTED_QUESTIONS.map((q) => (
              <button
                key={q.label}
                type="button"
                onClick={() => void ask(q.question)}
                className="rounded-full border border-model-line px-2.5 py-0.5 text-[11px] text-model transition-colors hover:bg-model-soft"
              >
                {q.label}
              </button>
            ))}
          </div>
        )}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void ask(input);
          }}
          className="flex gap-2"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this reconciliation…"
            aria-label="Ask a question"
            disabled={asking}
            className="input h-[38px] flex-1 border-model-line focus:border-model"
          />
          <button
            type="submit"
            disabled={!input.trim() || asking}
            aria-label="Ask"
            className="flex h-[38px] w-[38px] items-center justify-center rounded-[8px] bg-model text-[#1a1030] transition-opacity disabled:opacity-40"
          >
            <ArrowUp width={16} height={16} />
          </button>
        </form>
      </div>
    </div>
  );
}

function Avatar({ role }: { role: "user" | "assistant" }) {
  if (role === "assistant") {
    return (
      <div className="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-model-line bg-model-soft text-model" aria-hidden>
        <Sparkles width={12} height={12} />
      </div>
    );
  }
  return (
    <div className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-accent-soft text-[10px] font-semibold text-accent">VP</div>
  );
}

function TypingDot({ delay }: { delay: string }) {
  return <span className="pulse-dot inline-block h-1.5 w-1.5 rounded-full bg-model/70" style={{ animationDelay: delay }} />;
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const refused = message.result && !message.result.answerable;

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
      className={cn("flex items-end gap-2", isUser ? "justify-end" : "justify-start")}
    >
      {!isUser && <Avatar role="assistant" />}
      <div
        className={cn(
          "max-w-[78%] rounded-[12px] border px-3.5 py-2.5 text-[13px] leading-relaxed",
          isUser ? "border-line-strong bg-surface-2 text-ink" : refused ? "border-model-line bg-bg/70 text-ink-2" : "border-model-line bg-bg text-ink",
        )}
      >
        <p>{message.text}</p>
        {message.result?.answerable && message.result.show_table && message.result.rows.length > 0 && <ResultTable rows={message.result.rows} />}
        {message.result?.answerable && (message.result.sql || message.result.tool === "diff") && <HowIGotThis result={message.result} />}
      </div>
      {isUser && <Avatar role="user" />}
    </motion.div>
  );
}

function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Object.keys(rows[0] ?? {});
  return (
    <div className="mt-2.5 max-h-64 overflow-auto rounded-[8px] border border-line">
      <table className="w-full text-[11.5px]">
        <thead className="sticky top-0 bg-surface-2">
          <tr>
            {columns.map((c) => (
              <th key={c} className="th">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c} className="td num whitespace-nowrap text-ink">
                  {String(row[c] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HowIGotThis({ result }: { result: AskOut }) {
  return (
    <details className="mt-2">
      <summary className="cursor-pointer text-[11px] text-ink-3 select-none hover:text-ink-2">How I got this</summary>
      <div className="mt-1.5 text-[11.5px]">
        {result.tool === "diff" ? (
          <p className="text-ink-3">
            Compared run <span className="num">{result.compared_from_run_id}</span> to run <span className="num">{result.compared_to_run_id}</span> via
            fc.audit.replay.diff_exceptions, a structural diff, not a SQL aggregate.
          </p>
        ) : (
          result.sql && <pre className="num overflow-x-auto rounded-[8px] border border-line bg-surface p-2.5 text-[11px] text-ink-2">{result.sql}</pre>
        )}
        <p className="num mt-1 text-ink-3">
          {result.row_count} row{result.row_count === 1 ? "" : "s"}
          {result.cached ? " · cached" : ""}
          {result.model_used ? ` · ${result.model_used}` : ""}
          {result.truncated ? " · truncated at the row cap" : ""}
        </p>
      </div>
    </details>
  );
}
