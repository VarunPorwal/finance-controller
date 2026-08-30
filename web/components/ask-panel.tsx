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
    <div className="flex h-[70vh] flex-col gap-3">
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <div className="border-rule bg-ink-800 rounded-lg border border-dashed p-6 text-center">
            <p className="text-paper-300 mb-3 text-sm">
              Ask about this reconciliation — aggregates, breakdowns, what changed, what-ifs.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {SUGGESTED_QUESTIONS.map((q) => (
                <button
                  key={q.label}
                  type="button"
                  onClick={() => void ask(q.question)}
                  className="border-rule text-paper-300 hover:bg-ink-700 rounded-full border px-3 py-1 text-xs"
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
          <div className="flex justify-start">
            <div className="border-rule bg-ink-800 flex items-center gap-1 rounded-lg border px-3 py-2">
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
              className="border-rule text-paper-500 hover:bg-ink-700 rounded-full border px-2.5 py-0.5 text-xs"
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
          placeholder="Ask a follow-up…"
          aria-label="Ask a question"
          disabled={asking}
          className="border-rule bg-ink-800 text-paper-100 placeholder:text-paper-500 flex-1 rounded-md border p-2.5 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rzp-blue disabled:opacity-60"
        />
        <button
          type="submit"
          disabled={!input.trim() || asking}
          className="bg-rzp-blue hover:bg-rzp-blue/90 rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          Ask
        </button>
      </form>
    </div>
  );
}

function TypingDot({ delay }: { delay: string }) {
  return (
    <span
      className="bg-paper-500 inline-block h-1.5 w-1.5 animate-bounce rounded-full"
      style={{ animationDelay: delay }}
    />
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const refused = message.result && !message.result.answerable;

  return (
    <div className={"flex " + (isUser ? "justify-end" : "justify-start")}>
      <div
        className={
          "max-w-[85%] rounded-lg border px-3 py-2 text-sm " +
          (isUser
            ? "bg-rzp-deep border-rzp-blue/40 text-paper-100"
            : refused
              ? "border-rule bg-ink-800 text-paper-300" // §13.7: a refusal is a correct outcome, no error styling
              : "border-rule bg-ink-800 text-paper-100")
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
    </div>
  );
}

function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  const columns = Object.keys(rows[0] ?? {});
  return (
    <div className="border-rule mt-2 max-h-64 overflow-auto rounded-md border">
      <table className="w-full text-xs">
        <thead className="bg-ink-900 text-paper-300 sticky top-0">
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
            <tr key={i} className="border-rule border-t">
              {columns.map((c) => (
                <td key={c} className="fc-numeric text-paper-100 whitespace-nowrap px-2 py-1">
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
      <summary className="text-paper-500 hover:text-paper-300 cursor-pointer select-none text-xs">
        How I got this
      </summary>
      <div className="mt-1 text-xs">
        {result.tool === "diff" ? (
          <p className="text-paper-500">
            Compared run{" "}
            <span className="fc-numeric">{result.compared_from_run_id}</span> to run{" "}
            <span className="fc-numeric">{result.compared_to_run_id}</span> via
            fc.audit.replay.diff_exceptions — a structural diff, not a SQL aggregate.
          </p>
        ) : (
          result.sql && (
            <pre className="fc-numeric border-rule bg-ink-900 text-paper-300 overflow-x-auto rounded-md border p-2">
              {result.sql}
            </pre>
          )
        )}
        <p className="text-paper-500 mt-1">
          {result.row_count} row{result.row_count === 1 ? "" : "s"}
          {result.cached ? " · cached" : ""}
          {result.model_used ? ` · ${result.model_used}` : ""}
          {result.truncated ? " · truncated at the row cap" : ""}
        </p>
      </div>
    </details>
  );
}
