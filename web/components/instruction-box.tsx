"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Pill } from "@/components/ui/pill";

type ParseOut = components["schemas"]["ParseOut"];
type ExecuteOut = components["schemas"]["ExecuteOut"];
type Refusal = { code: string; message: string; candidates: string[] };

/**
 * The loop the product is for: a person says what an exception is, the
 * agent shows what it would do, and nothing happens until they agree.
 * Each push-back case has its own state rather than being flattened into
 * one message: refusal, warnings, typed confirmation over ₹50,000,
 * acknowledgement, the cluster offer, and parse-unavailable.
 *
 * Confirm is a second request. /agent/execute re-derives the effects
 * against fresh state and refuses if they differ from the preview shown.
 */
export function InstructionBox({ exceptionId, onApplied }: { exceptionId: string; onApplied: () => void }) {
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parsed, setParsed] = useState<ParseOut | null>(null);
  const [typedConfirmation, setTypedConfirmation] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [result, setResult] = useState<ExecuteOut | null>(null);
  const [error, setError] = useState<Refusal | null>(null);

  function reset() {
    setParsed(null);
    setTypedConfirmation("");
    setAcknowledged(false);
    setResult(null);
    setError(null);
  }

  function refusalFromError(err: unknown, status: number): Refusal {
    if (err && typeof err === "object") {
      const body = err as { title?: unknown; detail?: unknown; candidates?: unknown };
      const candidates = Array.isArray(body.candidates) ? body.candidates.map((c) => String(c)) : [];
      if (body.detail !== undefined) {
        return { code: String(body.title ?? "refused"), message: String(body.detail), candidates };
      }
    }
    return { code: "error", message: `request failed (${status})`, candidates: [] };
  }

  async function parse() {
    const trimmed = text.trim();
    if (!trimmed) return;
    setParsing(true);
    reset();
    try {
      const { data, error: parseError, response } = await apiClient.POST("/api/v1/agent/parse", {
        body: { text: trimmed, context: { exception_id: exceptionId } },
      });
      if (parseError || !data) {
        setError(refusalFromError(parseError, response.status));
        return;
      }
      setParsed(data);
    } catch {
      setError({ code: "network", message: "Could not reach the API.", candidates: [] });
    } finally {
      setParsing(false);
    }
  }

  const queryClient = useQueryClient();

  const executeMutation = useMutation({
    mutationFn: async (applyToCluster: boolean) => {
      if (!parsed) throw new Error("nothing parsed");
      const { data, error: execError, response } = await apiClient.POST("/api/v1/agent/execute", {
        body: {
          command_id: parsed.command_id,
          confirmed: true,
          apply_to_cluster: applyToCluster,
          acknowledged,
          typed_confirmation: typedConfirmation.trim() || null,
        },
      });
      if (execError || !data) {
        throw Object.assign(new Error("execute failed"), { refusal: refusalFromError(execError, response.status) });
      }
      return data;
    },
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ["exceptions"] });
      const snapshots = queryClient.getQueriesData<unknown>({ queryKey: ["exceptions"] });
      queryClient.setQueriesData<Array<{ exception: { exception_id: string } }>>({ queryKey: ["exceptions"] }, (old) =>
        Array.isArray(old) ? old.filter((r) => r.exception?.exception_id !== exceptionId) : old,
      );
      return { snapshots };
    },
    onError: (err, _vars, context) => {
      context?.snapshots.forEach(([key, value]) => queryClient.setQueryData(key, value));
      const withRefusal = err as unknown as { refusal?: Refusal };
      setError(withRefusal.refusal ?? { code: "network", message: "Could not reach the API.", candidates: [] });
    },
    onSuccess: (data) => {
      setResult(data);
      setText("");
      setParsed(null);
      onApplied();
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["exceptions"] });
      void queryClient.invalidateQueries({ queryKey: ["exception", exceptionId] });
      void queryClient.invalidateQueries({ queryKey: ["runs", "default"] });
    },
  });

  const executing = executeMutation.isPending;
  const preview = parsed?.preview;
  const refusal = preview?.refusal ?? null;
  const typedOk = !preview?.requires_typed_confirmation || typedConfirmation.trim().length > 0;
  const ackOk = !preview?.requires_acknowledgement || acknowledged;
  const canConfirm = !!preview && !refusal && typedOk && ackOk && !executing;

  return (
    <div className="panel-model px-[18px] py-4">
      <div className="mb-2.5 flex items-center justify-between">
        <label htmlFor="instruction" className="text-[12.5px] font-semibold text-model">
          Tell the agent what this is
        </label>
        <Pill tone="model">Model parses · you confirm</Pill>
      </div>
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
          className="input flex-1"
          rows={2}
        />
        <Button variant="model" className="self-start" onClick={() => void parse()} disabled={!text.trim() || parsing || executing}>
          {parsing ? "Reading…" : "Preview"}
        </Button>
      </div>

      {error && <RefusalBlock refusal={error} />}

      {parsed?.parse_unavailable && (
        <div className="mt-3 rounded-[8px] border border-line bg-bg p-3 text-[12.5px]">
          <p className="text-ink-2">No model could parse that sentence. The same actions are available directly:</p>
          <p className="num mt-1 text-ink-3">{parsed.form_verbs.join(" · ")}</p>
        </div>
      )}

      {refusal && <RefusalBlock refusal={refusal} />}

      {preview && !refusal && (
        <div className="mt-3 space-y-3 rounded-[8px] border border-line bg-bg p-3">
          <p className="text-[12.5px] text-ink">{preview.summary}</p>
          {preview.effects.length > 0 && (
            <ul className="space-y-1">
              {preview.effects.map((e, i) => (
                <li key={i} className="text-[11.5px] text-ink-2">
                  <span className="font-semibold text-ink">{e.action}</span> {e.subject}: {e.summary}
                </li>
              ))}
            </ul>
          )}
          {preview.warnings.map((w) => (
            <p key={w.code} className="text-[11.5px] text-warn">
              {w.message}
            </p>
          ))}
          {preview.requires_typed_confirmation && (
            <div>
              <label htmlFor="typed" className="block text-[11.5px] text-ink-2">
                Over {formatPaise(preview.typed_confirmation_paise ?? 0)}. Type the amount in paise to confirm.
              </label>
              <input id="typed" value={typedConfirmation} onChange={(e) => setTypedConfirmation(e.target.value)} className="input num mt-1.5 w-48" />
            </div>
          )}
          {preview.requires_acknowledgement && (
            <label className="flex items-start gap-2 text-[11.5px] text-ink-2">
              <input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} className="mt-0.5" />
              <span>I understand and accept this consequence.</span>
            </label>
          )}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button variant="primary" onClick={() => executeMutation.mutate(false)} disabled={!canConfirm}>
              {executing ? "Applying…" : preview.cluster_offer ? "Just this one" : "Confirm"}
            </Button>
            {preview.cluster_offer && (
              <Button onClick={() => executeMutation.mutate(true)} disabled={!canConfirm}>
                Apply to all {preview.cluster_offer.member_count + 1}
              </Button>
            )}
            <Button variant="ghost" onClick={reset} disabled={executing}>
              Cancel
            </Button>
          </div>
          {preview.cluster_offer && (
            <p className="text-[11px] text-ink-3">
              {preview.cluster_offer.member_count} other exception{preview.cluster_offer.member_count === 1 ? "" : "s"} share this root
              cause. Any that fail validation are excluded and named, never silently skipped.
            </p>
          )}
        </div>
      )}

      {result && (
        <div className="mt-3 rounded-[8px] border border-line bg-bg p-3 text-[12.5px]">
          <p className="text-ok">
            Applied to {result.applied.filter((a) => a.ok).length} exception{result.applied.filter((a) => a.ok).length === 1 ? "" : "s"}
            {result.audit_seq != null && <span className="num text-ink-3"> · audit #{result.audit_seq}</span>}
          </p>
          {result.excluded.length > 0 && (
            <>
              <p className="mt-2 text-[11.5px] text-warn">Excluded {result.excluded.length}, by name:</p>
              <ul className="num mt-1 space-y-0.5 text-[11.5px] text-ink-2">
                {result.excluded.map((e) => (
                  <li key={e.exception_id}>
                    {e.exception_id.slice(-8)}: {e.detail ?? "validation failed"}
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
    <div role="alert" className="mt-3 rounded-[8px] border border-[rgba(255,107,107,0.35)] bg-bad-soft p-3 text-[12.5px]">
      <p className="font-semibold text-bad">Not doing that</p>
      <p className="mt-1 text-ink">{refusal.message}</p>
      {refusal.candidates.length > 0 && (
        <>
          <p className="mt-2 text-[11.5px] text-ink-2">Closest matches. None has been chosen for you:</p>
          <ul className="num mt-1 space-y-0.5 text-[11.5px] text-ink-2">
            {refusal.candidates.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
