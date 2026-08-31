"use client";

import { useEffect, useRef, useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { useRun } from "@/lib/run-context";

type AskOut = components["schemas"]["AskOut"];
type AskTurnIn = components["schemas"]["AskTurnIn"];

// PRD §13.7: the four question shapes retrieval (a single-vector search)
// cannot answer — illustrative chip text only, nothing computed here.
const SUGGESTED_QUESTIONS = [
  { label: "Aggregate", question: "How much is at risk right now?" },
  { label: "Group-by", question: "Break down open exceptions by category." },
  { label: "Run diff", question: "What changed since the last run?" },
  {
    label: "Counterfactual",
    question: "How many matches would have auto-closed at a 0.90 threshold instead?",
  },
];

//: How many prior turns travel with each request — the server caps here too,
//: this just keeps the payload from growing unbounded in a long chat.
const HISTORY_TURNS = 5;

interface Message {
  id: number;
  role: "user" | "assistant";
  text: string;
  result?: AskOut;
}

/**
 * PRD §13.7, reworked into a conversational assistant (not a query box):
 * message thread, prose answers, the SQL/diff mechanism collapsed behind a
 * "how I got this" disclosure rather than shown as the primary output, and
 * the last 5 turns carried along so a follow-up can resolve "those"/"it"
 * without the user ever noticing they triggered a fresh query to do it.
 */
export function AskPanel() {
  const { summary } = useRun();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [asking, setAsking] = useState(false);
  const nextId = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, asking]);

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed || asking) return;
    setInput("");

    // Messages come in user/assistant pairs, in order — walk them as pairs
    // rather than re-deriving pairing from array position each time.
    const history: AskTurnIn[] = [];
    for (let i = 0; i < messages.length - 1; i++) {
      const userMsg = messages[i];
      const assistantMsg = messages[i + 1];
      if (userMsg.role === "user" && assistantMsg.role === "assistant" && assistantMsg.result) {
        history.push({
          question: userMsg.text,
          answer: assistantMsg.result.answer ?? assistantMsg.result.refusal_reason ?? "",
        });
        i++;
      }
    }
    const recentHistory = history.slice(-HISTORY_TURNS);

    setMessages((prev) => [...prev, { id: nextId.current++, role: "user", text: trimmed }]);
    setAsking(true);
    try {
      const { data, error } = await apiClient.POST("/api/v1/agent/ask", {
        body: { question: trimmed, run_id: summary?.run.run_id ?? null, history: recentHistory },
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
          text: result.answerable
            ? (result.answer ?? "")
            : (result.refusal_reason ?? "I can't answer that from your reconciliation data."),
          result,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: nextId.current++, role: "assistant", text: "Could not reach the API." },
      ]);
    } finally {
      setAsking(false);
    }
  }

  return (
    // Whole surface violet — the one screen where that's structural, not an
    // accent, because everything on it is model output (design/README.md).
    <div className="flex h-full flex-col gap-3 rounded-[var(--radius-card)] border border-model-border bg-model-bg p-4">
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <div className="rounded-[var(--radius-card)] border border-dashed border-model-border p-6 text-center">
            <div className="mx-auto mb-3 h-10 w-10 rounded-full" style={{ background: "radial-gradient(circle at 35% 30%, #C4B5FD, #7C3AED)" }} />
            <p className="mb-3 text-sm text-model-text">
              Ask about this reconciliation — aggregates, breakdowns, what changed, what-ifs.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTED_QUESTIONS.map((q) => (
                <button
                  key={q.label}
                  type="button"
                  onClick={() => void ask(q.question)}
                  className="rounded-full border border-model-border bg-white/60 px-3 py-1 text-xs text-model-text hover:bg-white"
                >
                  {q.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}

        {asking && (
          <div className="flex items-end justify-start gap-2">
            <Avatar role="assistant" />
            <div className="flex items-center gap-1 rounded-lg border border-model-border bg-white px-3 py-2">
              <TypingDot delay="0ms" />
              <TypingDot delay="150ms" />
              <TypingDot delay="300ms" />
            </div>
          </div>
        )}
      </div>

      {messages.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {SUGGESTED_QUESTIONS.map((q) => (
            <button
              key={q.label}
              type="button"
              onClick={() => void ask(q.question)}
              className="rounded-full border border-model-border px-2.5 py-0.5 text-xs text-model-text hover:bg-white/60"
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
          placeholder="Ask about your reconciliation…"
          aria-label="Ask a question"
          disabled={asking}
          className="flex-1 rounded-[9px] border border-model-border bg-white p-2.5 text-sm text-text-heading placeholder:text-text-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-model-text disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!input.trim() || asking}
          className="rounded-[9px] px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          style={{ background: "var(--model-text)" }}
        >
          Ask
        </button>
      </form>
    </div>
  );
}

function Avatar({ role }: { role: "user" | "assistant" }) {
  if (role === "assistant") {
    return (
      <div
        className="h-6 w-6 flex-none rounded-full"
        style={{ background: "radial-gradient(circle at 35% 30%, #C4B5FD, #7C3AED)" }}
        aria-hidden
      />
    );
  }
  return (
    <div className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-primary-tint text-[10px] font-semibold text-primary-active-text">
      VP
    </div>
  );
}

function TypingDot({ delay }: { delay: string }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 animate-bounce rounded-full bg-model-text/60"
      style={{ animationDelay: delay }}
    />
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const refused = message.result && !message.result.answerable;

  return (
    <div className={"flex items-end gap-2 " + (isUser ? "justify-end" : "justify-start")}>
      {!isUser && <Avatar role="assistant" />}
      <div
        className={
          "max-w-[80%] rounded-lg border px-3 py-2 text-sm " +
          (isUser
            ? "border-model-border bg-white text-text-heading"
            : refused
              ? "border-model-border bg-white/70 text-text-body" // a refusal is a correct outcome, no error styling
              : "border-model-border bg-white text-text-heading")
        }
      >
        <p>{message.text}</p>

        {message.result?.answerable && message.result.show_table && message.result.rows.length > 0 && (
          <ResultTable rows={message.result.rows} />
        )}

        {message.result?.answerable && (message.result.sql || message.result.tool === "diff") && (
          <HowIGotThis result={message.result} />
        )}
      </div>
      {isUser && <Avatar role="user" />}
    </div>
  );
}

function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Object.keys(rows[0] ?? {});
  return (
    <div className="border-border mt-2 max-h-64 overflow-auto rounded-md border">
      <table className="w-full text-xs">
        <thead className="bg-background text-text-body sticky top-0">
          <tr>
            {columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-2 py-1 text-left font-medium">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-border border-t">
              {columns.map((c) => (
                <td key={c} className="fc-numeric text-text-heading whitespace-nowrap px-2 py-1">
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
      <summary className="text-text-muted hover:text-text-body cursor-pointer select-none text-xs">
        How I got this
      </summary>
      <div className="mt-1 text-xs">
        {result.tool === "diff" ? (
          <p className="text-text-muted">
            Compared run{" "}
            <span className="fc-numeric">{result.compared_from_run_id}</span> to run{" "}
            <span className="fc-numeric">{result.compared_to_run_id}</span> via
            fc.audit.replay.diff_exceptions — a structural diff, not a SQL aggregate.
          </p>
        ) : (
          result.sql && (
            <pre className="fc-numeric border-border bg-background text-text-body overflow-x-auto rounded-md border p-2">
              {result.sql}
            </pre>
          )
        )}
        <p className="text-text-muted mt-1">
          {result.row_count} row{result.row_count === 1 ? "" : "s"}
          {result.cached ? " · cached" : ""}
          {result.model_used ? ` · ${result.model_used}` : ""}
          {result.truncated ? " · truncated at the row cap" : ""}
        </p>
      </div>
    </details>
  );
}
