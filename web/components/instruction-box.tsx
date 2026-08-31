"use client";

import { useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";

type ParseOut = components["schemas"]["ParseOut"];
type ExecuteOut = components["schemas"]["ExecuteOut"];
type Refusal = { code: string; message: string; candidates: string[] };

/**
 * PRD §8.3–§8.6. The loop the whole product is for: a person says what an
 * exception is, the agent shows what it would do, and nothing happens until
 * they agree.
 *
 * The push-back cases in §8.5 are the point, not error handling bolted on —
 * "a judge watching an agent question a human command remembers it more than
 * any successful action" — so each has its own state here rather than being
 * flattened into one message:
 *
 *   refusal                      the agent will not act; candidates are listed
 *                                and never chosen for the user
 *   warnings                     it will act, but says what it noticed first
 *   requires_typed_confirmation  over ₹50,000: type the amount to proceed
 *   requires_acknowledgement     e.g. closing a chargeback with no dispute ref
 *   cluster_offer                §8.6's "apply to the other N"
 *   parse_unavailable            no model could parse it; offer the verbs
 *
 * Confirm is deliberately a second request rather than a flag on the first.
 * /agent/execute re-derives the effects against fresh state and refuses if
 * they differ from the preview shown, so the preview cannot go stale between
 * the two.
 */
export function InstructionBox({
  exceptionId,
  onApplied,
}: {
  exceptionId: string;
  onApplied: () => void;
}) {
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parsed, setParsed] = useState<ParseOut | null>(null);
  const [typedConfirmation, setTypedConfirmation] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<ExecuteOut | null>(null);
  const [error, setError] = useState<Refusal | null>(null);

  function reset() {
    setParsed(null);
    setTypedConfirmation("");
    setAcknowledged(false);
    setResult(null);
    setError(null);
  }

  /** A push-back the API returned as a 4xx rather than inside the preview.
   *
   * §8.5's "referenced order/voucher not found" arrives as a 422 whose body
   * carries `title`, `detail` and `candidates` — the same shape as a
   * `RefusalOut`, just delivered as an error. Rendering only `detail` would
   * drop the candidate list, which is the half that matters: the agent is
   * supposed to show the near matches and decline to pick one.
   */
  function refusalFromError(err: unknown, status: number): Refusal {
    if (err && typeof err === "object") {
      const body = err as {
        title?: unknown;
        detail?: unknown;
        candidates?: unknown;
      };
      const candidates = Array.isArray(body.candidates)
        ? body.candidates.map((c) => String(c))
        : [];
      if (body.detail !== undefined) {
        return {
          code: String(body.title ?? "refused"),
          message: String(body.detail),
          candidates,
        };
      }
    }
    return {
      code: "error",
      message: `request failed (${status})`,
      candidates: [],
    };
  }

  async function parse() {
    const trimmed = text.trim();
    if (!trimmed) return;
    setParsing(true);
    reset();
    try {
      const {
        data,
        error: parseError,
        response,
      } = await apiClient.POST("/api/v1/agent/parse", {
        body: { text: trimmed, context: { exception_id: exceptionId } },
      });
      if (parseError || !data) {
        setError(refusalFromError(parseError, response.status));
        return;
      }
      setParsed(data);
    } catch {
      setError({
        code: "network",
        message: "Could not reach the API.",
        candidates: [],
      });
    } finally {
      setParsing(false);
    }
  }

  async function execute(applyToCluster: boolean) {
    if (!parsed) return;
    setExecuting(true);
    setError(null);
    try {
      const {
        data,
        error: execError,
        response,
      } = await apiClient.POST("/api/v1/agent/execute", {
        body: {
          command_id: parsed.command_id,
          confirmed: true,
          apply_to_cluster: applyToCluster,
          acknowledged,
          typed_confirmation: typedConfirmation.trim() || null,
        },
      });
      if (execError || !data) {
        setError(refusalFromError(execError, response.status));
        return;
      }
      setResult(data);
      setText("");
      setParsed(null);
      onApplied();
    } catch {
      setError({
        code: "network",
        message: "Could not reach the API.",
        candidates: [],
      });
    } finally {
      setExecuting(false);
    }
  }

  const preview = parsed?.preview;
  const refusal = preview?.refusal ?? null;
  // A refusal is terminal for this instruction; everything else is a gate the
  // person can satisfy.
  const typedOk =
    !preview?.requires_typed_confirmation ||
    typedConfirmation.trim().length > 0;
  const ackOk = !preview?.requires_acknowledgement || acknowledged;
  const canConfirm = !!preview && !refusal && typedOk && ackOk && !executing;

  return (
    <div className="border-rule bg-ink-800 rounded-lg border p-4">
      <label
        htmlFor="instruction"
        className="text-paper-300 mb-2 block text-xs font-medium"
      >
        Tell the agent what this is…
      </label>
      <div className="flex gap-2">
        <textarea
          id="instruction"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void parse();
            }
          }}
          disabled={parsing || executing}
          placeholder="e.g. This is a bank credit that landed after the statement cut-off"
          className="border-rule bg-ink-900 text-paper-100 placeholder:text-paper-500 flex-1 resize-none rounded-md border p-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rzp-blue disabled:opacity-60"
          rows={2}
        />
        <button
          type="button"
          onClick={() => void parse()}
          disabled={!text.trim() || parsing || executing}
          className="bg-rzp-blue hover:bg-rzp-blue/90 self-start rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {parsing ? "Reading…" : "Preview"}
        </button>
      </div>

      {error && <RefusalBlock refusal={error} />}

      {parsed?.parse_unavailable && (
        <div className="border-rule bg-ink-900 mt-3 rounded-md border p-3 text-sm">
          <p className="text-paper-300">
            No model could parse that sentence. The same actions are available
            directly:
          </p>
          <p className="fc-numeric text-paper-500 mt-1">
            {parsed.form_verbs.join(" · ")}
          </p>
        </div>
      )}

      {refusal && <RefusalBlock refusal={refusal} />}

      {preview && !refusal && (
        <div className="border-rule bg-ink-900 mt-3 space-y-3 rounded-md border p-3">
          <p className="text-paper-100 text-sm">{preview.summary}</p>

          {preview.effects.length > 0 && (
            <ul className="space-y-1">
              {preview.effects.map((e, i) => (
                <li key={i} className="text-paper-300 text-xs">
                  <span className="text-paper-100 font-medium">{e.action}</span>{" "}
                  {e.subject} — {e.summary}
                </li>
              ))}
            </ul>
          )}

          {preview.warnings.map((w) => (
            <p key={w.code} className="text-sig-amber text-xs">
              {w.message}
            </p>
          ))}

          {preview.requires_typed_confirmation && (
            <div>
              <label htmlFor="typed" className="text-paper-300 block text-xs">
                Over {formatPaise(preview.typed_confirmation_paise ?? 0)} — type
                the amount in paise to confirm
              </label>
              <input
                id="typed"
                value={typedConfirmation}
                onChange={(e) => setTypedConfirmation(e.target.value)}
                className="border-rule bg-ink-800 text-paper-100 fc-numeric mt-1 w-48 rounded-md border p-1.5 text-sm"
              />
            </div>
          )}

          {preview.requires_acknowledgement && (
            <label className="text-paper-300 flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
                className="mt-0.5"
              />
              <span>I understand and accept this consequence.</span>
            </label>
          )}

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              onClick={() => void execute(false)}
              disabled={!canConfirm}
              className="bg-rzp-blue hover:bg-rzp-blue/90 rounded-md px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {executing
                ? "Applying…"
                : preview.cluster_offer
                  ? "Just this one"
                  : "Confirm"}
            </button>
            {preview.cluster_offer && (
              <button
                type="button"
                onClick={() => void execute(true)}
                disabled={!canConfirm}
                className="border-rule bg-ink-800 hover:bg-ink-700 text-paper-100 rounded-md border px-3 py-1.5 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
              >
                Apply to all {preview.cluster_offer.member_count + 1}
              </button>
            )}
            <button
              type="button"
              onClick={reset}
              disabled={executing}
              className="text-paper-300 hover:text-paper-100 px-2 py-1.5 text-sm"
            >
              Cancel
            </button>
          </div>

          {preview.cluster_offer && (
            <p className="text-paper-500 text-xs">
              {preview.cluster_offer.member_count} other exception
              {preview.cluster_offer.member_count === 1 ? "" : "s"} share this
              root cause. Any that fail validation are excluded and named, never
              silently skipped.
            </p>
          )}
        </div>
      )}

      {result && (
        <div className="border-rule bg-ink-900 mt-3 rounded-md border p-3 text-sm">
          <p className="text-sig-green">
            Applied to {result.applied.filter((a) => a.ok).length} exception
            {result.applied.filter((a) => a.ok).length === 1 ? "" : "s"}
            {result.audit_seq != null && (
              <span className="text-paper-500">
                {" "}
                · audit #{result.audit_seq}
              </span>
            )}
          </p>
          {result.excluded.length > 0 && (
            <>
              <p className="text-sig-amber mt-2 text-xs">
                Excluded {result.excluded.length}, by name:
              </p>
              <ul className="fc-numeric text-paper-300 mt-1 space-y-0.5 text-xs">
                {result.excluded.map((e) => (
                  <li key={e.exception_id}>
                    {e.exception_id.slice(-8)} —{" "}
                    {e.detail ?? "validation failed"}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function RefusalBlock({ refusal }: { refusal: Refusal }) {
  return (
    <div
      role="alert"
      className="border-sig-red/40 bg-sig-red/10 mt-3 rounded-md border p-3 text-sm"
    >
      <p className="text-sig-red font-heading font-semibold">Not doing that</p>
      <p className="text-paper-100 mt-1">{refusal.message}</p>
      {refusal.candidates.length > 0 && (
        <>
          <p className="text-paper-300 mt-2 text-xs">
            Closest matches — none has been chosen for you:
          </p>
          <ul className="fc-numeric text-paper-300 mt-1 space-y-0.5 text-xs">
            {refusal.candidates.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
