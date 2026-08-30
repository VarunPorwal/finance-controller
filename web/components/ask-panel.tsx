"use client";

import { useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { useRun } from "@/lib/run-context";

type AskOut = components["schemas"]["AskOut"];

// PRD §13.7: the four question shapes RAG cannot do — a single-vector search
// answers "what is X", not these. Illustrative prompt text only; nothing
// here is computed, they're just chips that fill the input.
const SUGGESTED_QUESTIONS = [
  { label: "Aggregate", question: "What is the total cash at risk across all open exceptions?" },
  { label: "Group-by", question: "Break down open exceptions by category and count." },
  { label: "Run diff", question: "How many more exceptions does this run have than the previous run?" },
  {
    label: "Counterfactual",
    question: "How many matches would have auto-closed if the auto threshold were 0.90 instead?",
  },
];

interface Turn {
  question: string;
  result: AskOut | null;
  loading: boolean;
}

/**
 * PRD §13.7: command input, answer with SQL collapsible beneath, suggested
 * question chips for the four shapes RAG can't do, refusals rendered
 * plainly — not as errors. Every number in an answer comes from the query
 * the model wrote, guarded and executed server-side (§7.8); this panel only
 * renders what `/agent/ask` returns.
 */
export function AskPanel() {
  const { summary } = useRun();
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed) return;
    setInput("");
    setTurns((prev) => [{ question: trimmed, result: null, loading: true }, ...prev]);
    const { data, error } = await apiClient.POST("/api/v1/agent/ask", {
      body: { question: trimmed, run_id: summary?.run.run_id ?? null },
    });
    setTurns((prev) =>
      prev.map((t, i) =>
        i === 0
          ? {
              ...t,
              loading: false,
              result: data ?? {
                answerable: false,
                refusal_reason: error ? "The Ask tab could not reach the API." : "No answer.",
                rows: [],
                row_count: 0,
                cached: false,
                truncated: false,
              },
            }
          : t,
      ),
    );
  }

  return (
    <div className="flex flex-col gap-4">
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
          placeholder="Ask about this run — aggregates, breakdowns, run diffs, counterfactuals…"
          aria-label="Ask a question"
          className="border-rule bg-ink-800 text-paper-100 placeholder:text-paper-500 flex-1 rounded-md border p-2.5 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rzp-blue"
        />
        <button
          type="submit"
          disabled={!input.trim()}
          className="bg-rzp-blue hover:bg-rzp-blue/90 rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          Ask
        </button>
      </form>

      <div className="flex flex-wrap gap-2">
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

      <ul className="flex flex-col gap-3">
        {turns.map((turn, i) => (
          <li key={i} className="border-rule bg-ink-800 rounded-lg border p-4">
            <p className="text-paper-300 mb-2 text-sm font-medium">{turn.question}</p>
            {turn.loading && (
              <div className="border-rule bg-ink-900 h-8 animate-pulse rounded-md border" aria-hidden />
            )}
            {turn.result && <AskAnswer result={turn.result} />}
          </li>
        ))}
        {turns.length === 0 && (
          <li className="text-paper-500 border-rule bg-ink-800 rounded-lg border border-dashed p-6 text-center text-sm">
            Ask a question, or try one of the shapes above.
          </li>
        )}
      </ul>
    </div>
  );
}

function AskAnswer({ result }: { result: AskOut }) {
  if (!result.answerable) {
    // §13.7: rendered plainly, not as an error — no red/amber, no icon.
    return <p className="text-paper-300 text-sm">{result.refusal_reason}</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="text-paper-100 text-sm">{result.answer}</p>
      {result.truncated && (
        <p className="text-paper-500 text-xs">Results truncated at the row cap.</p>
      )}
      {result.sql && (
        <details>
          <summary className="text-paper-500 hover:text-paper-300 cursor-pointer select-none text-xs">
            SQL ({result.row_count} row{result.row_count === 1 ? "" : "s"}
            {result.cached ? ", cached" : ""})
          </summary>
          <pre className="fc-numeric border-rule bg-ink-900 text-paper-300 mt-2 overflow-x-auto rounded-md border p-2 text-xs">
            {result.sql}
          </pre>
        </details>
      )}
    </div>
  );
}
