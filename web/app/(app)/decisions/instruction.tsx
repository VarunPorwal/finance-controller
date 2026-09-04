"use client";

// The loop the product is for. A person says what an exception is, the model
// parses it into a command, deterministic code previews the effects, and
// nothing happens until the person confirms. Push-back is a first-class
// state, not an error toast. Finco-skinned: no framer-motion AnimatePresence
// choreography here (the old app panel used it); plain conditional renders
// keep the same states with fc-* styling.

import { useEffect, useState, type KeyboardEvent } from "react";
import { Check, X } from "lucide-react";
import {
  errorMessage,
  useInvalidateAll,
  writes,
  type Cluster,
  type Exception,
  type ExecuteOut,
  type ParseOut,
} from "../_lib/api";
import { money } from "../_lib/format";
import { QuickActions } from "./quick-actions";
import { typedMatches, type ClusterMode } from "./helpers";

const EXAMPLES = [
  "Manual refund done over phone on the 14th, book against the original order",
  "This is the Blinkit July payout, close it",
  "Write off, below threshold",
];

type Pushback = { message: string; candidates: string[] };

function pushbackFrom(err: unknown): Pushback {
  let candidates: string[] = [];
  if (typeof err === "object" && err && "candidates" in err) {
    const c = (err as { candidates?: unknown }).candidates;
    if (Array.isArray(c)) candidates = c.map(String);
  }
  return { message: errorMessage(err), candidates };
}

const inputCls =
  "rounded-[8px] border bg-[var(--fc-hover)] px-3 py-2 text-[12.5px] text-[var(--fc-text)] placeholder:text-[var(--fc-text-3)] outline-none w-full";

export function InstructionBox({
  exception,
  runId,
  clusterMode,
  cluster,
  onApplied,
  seedText,
  seedNonce,
}: {
  exception: Exception;
  runId: string | undefined;
  clusterMode: ClusterMode;
  cluster?: Cluster;
  onApplied: () => void;
  /** Set by the refusal card (section 11): a candidate pick or "neither"
   * writes a sentence here and this box previews it immediately, same as if
   * the person had typed it — there is no per-candidate assignment endpoint,
   * so the free-text instruction path is the real mutation being reused. */
  seedText?: string;
  seedNonce?: number;
}) {
  const [text, setText] = useState("");
  const [parsing, setParsing] = useState(false);
  const [parsed, setParsed] = useState<ParseOut | null>(null);
  const [pushback, setPushback] = useState<Pushback | null>(null);
  const [typed, setTyped] = useState("");
  const [ack, setAck] = useState(false);
  const [applyCluster, setApplyCluster] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<ExecuteOut | null>(null);
  const invalidate = useInvalidateAll();

  function reset() {
    setParsed(null);
    setPushback(null);
    setTyped("");
    setAck(false);
    setApplyCluster(false);
    setResult(null);
  }

  async function parse(explicit?: string) {
    const t = (explicit ?? text).trim();
    if (!t || parsing || executing) return;
    setParsing(true);
    reset();
    try {
      const res = await writes.parse({
        text: t,
        context: { exception_id: exception.exception_id, run_id: runId ?? null },
      });
      if (res.error || !res.data) {
        setPushback(pushbackFrom(res.error));
        return;
      }
      setParsed(res.data);
      setApplyCluster(!!res.data.preview.cluster_offer && !!clusterMode);
    } catch {
      setPushback({ message: "Could not reach the API.", candidates: [] });
    } finally {
      setParsing(false);
    }
  }

  useEffect(() => {
    if (!seedText) return;
    setText(seedText);
    void parse(seedText);
    // Re-fires only when seedNonce changes (a fresh pick from the refusal
    // card); parse is stable enough for this and seedText is read via the
    // nonce, not tracked directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seedNonce]);

  async function execute() {
    if (!parsed || executing) return;
    setExecuting(true);
    setPushback(null);
    try {
      const res = await writes.execute({
        command_id: parsed.command_id,
        confirmed: true,
        typed_confirmation: typed.trim() || null,
        acknowledged: ack,
        apply_to_cluster: applyCluster,
      });
      if (res.error || !res.data) {
        setPushback(pushbackFrom(res.error));
        return;
      }
      setResult(res.data);
      setParsed(null);
      setText("");
      void invalidate();
      onApplied();
    } catch {
      setPushback({ message: "Could not reach the API.", candidates: [] });
    } finally {
      setExecuting(false);
    }
  }

  function onKey(ev: KeyboardEvent<HTMLTextAreaElement>) {
    if (ev.key === "Enter" && !ev.shiftKey) {
      ev.preventDefault();
      void parse();
    }
  }

  const preview = parsed && !parsed.parse_unavailable ? parsed.preview : null;
  const refusal = preview?.refusal ?? null;
  const typedOk = !preview?.requires_typed_confirmation || typedMatches(typed, preview.typed_confirmation_paise ?? 0);
  const ackOk = !preview?.requires_acknowledgement || ack;
  const canConfirm = !!preview && !refusal && typedOk && ackOk && !executing;
  const otherCount = preview?.cluster_offer?.member_count ?? 0;

  return (
    <div
      id="instruction-box"
      className="rounded-[14px] border p-4"
      style={{ background: "linear-gradient(180deg, color-mix(in srgb, var(--fc-accent) 8%, transparent), transparent 60%), var(--fc-card)" }}
    >
      <div className="flex items-center justify-between gap-3">
        <div style={{ fontSize: 13, fontWeight: 500 }}>Tell it what you know</div>
        <span className="fc-chip" style={{ background: "var(--fc-divider)", color: "var(--fc-text-3)" }}>
          Model reads, you confirm
        </span>
      </div>
      {clusterMode && (
        <p className="fc-faint mt-1 text-[12px]">
          You chose one decision for {clusterMode.count}
          {cluster ? ` in "${cluster.label}"` : ""}. After the preview it is offered to the rest of the pattern.
        </p>
      )}

      <textarea
        className={`${inputCls} mt-3`}
        rows={2}
        placeholder="Tell it what you know…"
        value={text}
        onChange={(ev) => setText(ev.target.value)}
        onKeyDown={onKey}
        disabled={parsing || executing}
        aria-label="Instruction"
      />
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {EXAMPLES.map((x) => (
          <button
            key={x}
            className="fc-chip truncate max-w-[260px] cursor-pointer text-left"
            title={x}
            onClick={() => setText(x)}
            disabled={parsing || executing}
          >
            {x}
          </button>
        ))}
        <button
          className="fc-btn ml-auto"
          style={{ padding: "6px 14px", fontSize: 12 }}
          disabled={!text.trim() || executing || parsing}
          onClick={() => void parse()}
        >
          {parsing ? "Reading…" : "Preview"}
        </button>
      </div>

      {pushback && <PushbackBlock message={pushback.message} candidates={pushback.candidates} />}

      {parsed?.parse_unavailable && (
        <div className="mt-3">
          <QuickActions exception={exception} onApplied={onApplied} note="Model unavailable; the same actions, typed in" />
        </div>
      )}

      {refusal && <PushbackBlock message={refusal.message} candidates={refusal.candidates} code={refusal.code} />}

      {preview && !refusal && (
        <div className="mt-3 rounded-[10px] border p-4" style={{ background: "var(--fc-hover)" }}>
          <p className="text-[13px] leading-relaxed">{preview.summary}</p>

          {preview.effects.length > 0 && (
            <ul className="mt-3 flex flex-col gap-1.5">
              {preview.effects.map((ef, i) => (
                <li key={i} className="flex flex-wrap items-baseline gap-2 text-[12px]">
                  <span className="fc-chip">{ef.action}</span>
                  <span className="fc-faint font-mono">{ef.subject}</span>
                  <span>{ef.summary}</span>
                </li>
              ))}
            </ul>
          )}

          {preview.warnings.length > 0 && (
            <ul className="mt-3 flex flex-col gap-1">
              {preview.warnings.map((w, i) => (
                <li key={`${w.code}-${i}`} className="text-[12px]" style={{ color: "var(--fc-warn)" }}>
                  {w.message}
                </li>
              ))}
            </ul>
          )}

          {preview.requires_typed_confirmation && (
            <div className="mt-3">
              <label htmlFor="typed-confirm" className="fc-faint block text-[12px]">
                Type {money(preview.typed_confirmation_paise ?? 0)} to confirm
              </label>
              <div className="mt-1.5 flex items-center gap-2">
                <input
                  id="typed-confirm"
                  className={`${inputCls} fc-num w-56`}
                  style={typed && typedOk ? { borderColor: "var(--fc-ok)" } : undefined}
                  value={typed}
                  onChange={(ev) => setTyped(ev.target.value)}
                  placeholder={money(preview.typed_confirmation_paise ?? 0, { whole: true }).replace("₹", "")}
                  inputMode="decimal"
                />
                {typed && (typedOk ? <Check size={14} color="var(--fc-ok)" /> : <X size={14} color="var(--fc-bad)" />)}
              </div>
            </div>
          )}

          {preview.requires_acknowledgement && (
            <label className="mt-3 flex items-start gap-2 text-[12px]">
              <input type="checkbox" className="mt-0.5" checked={ack} onChange={(ev) => setAck(ev.target.checked)} />
              <span>I understand the consequence above and accept it.</span>
            </label>
          )}

          {preview.cluster_offer && (
            <label className="mt-3 flex items-start gap-2 text-[12px]">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={applyCluster}
                onChange={(ev) => setApplyCluster(ev.target.checked)}
              />
              <span>
                Apply to the other {otherCount} in this cluster. <span className="fc-faint">Any that fail validation are excluded and named.</span>
              </span>
            </label>
          )}

          <div className="mt-4 flex items-center gap-2">
            <button
              className="fc-btn"
              style={{ padding: "6px 14px", fontSize: 12 }}
              disabled={!canConfirm}
              onClick={() => void execute()}
            >
              {executing ? "Confirming…" : applyCluster ? `Confirm for ${otherCount + 1}` : "Confirm"}
            </button>
            <button className="fc-btn fc-btn--ghost" style={{ padding: "6px 14px", fontSize: 12 }} onClick={reset} disabled={executing}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="mt-3 rounded-[10px] border p-4" style={{ background: "var(--fc-hover)" }}>
          <div className="flex items-center gap-2 text-[13px] font-medium" style={{ color: "var(--fc-ok)" }}>
            <Check size={14} />
            Applied
          </div>
          <ul className="mt-2 flex flex-col gap-1">
            {result.applied.map((a) => (
              <AppliedRow key={a.exception_id} id={a.exception_id} ok={a.ok} detail={a.detail} />
            ))}
          </ul>
          {result.excluded.length > 0 && (
            <>
              <div className="fc-label mb-1 mt-3">Excluded</div>
              <ul className="flex flex-col gap-1">
                {result.excluded.map((a) => (
                  <AppliedRow key={a.exception_id} id={a.exception_id} ok={false} detail={a.detail} />
                ))}
              </ul>
            </>
          )}
          {result.audit_seq != null && (
            <div className="fc-faint mt-2 text-[11.5px]">
              Audit entry <span className="font-mono">{result.audit_seq}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PushbackBlock({ message, candidates, code }: { message: string; candidates: string[]; code?: string }) {
  return (
    <div
      className="mt-3 rounded-[12px] border p-4"
      style={{ borderColor: "color-mix(in srgb, var(--fc-bad) 35%, var(--fc-border))", background: "var(--fc-card)" }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="fc-label" style={{ color: "var(--fc-bad)" }}>
          Pushed back
        </div>
        {code && <span className="fc-faint font-mono text-[11px]">{code}</span>}
      </div>
      <p className="mt-1.5 text-[13px] leading-relaxed">{message}</p>
      {candidates.length > 0 && (
        <ul className="mt-2 flex flex-col gap-1">
          {candidates.map((c) => (
            <li key={c} className="fc-faint font-mono text-[12px]">
              {c}
            </li>
          ))}
        </ul>
      )}
      <p className="fc-faint mt-2 text-[12px]">This will not be done.</p>
    </div>
  );
}

function AppliedRow({ id, ok, detail }: { id: string; ok: boolean; detail?: string | null }) {
  return (
    <li className="flex items-center gap-2 text-[12px]">
      {ok ? <Check size={12} color="var(--fc-ok)" /> : <X size={12} color="var(--fc-bad)" />}
      <span className="fc-faint font-mono">{id.slice(-6).toUpperCase()}</span>
      {detail && (
        <span style={ok ? { color: "var(--fc-text-3)" } : { color: "var(--fc-bad)" }}>{detail}</span>
      )}
    </li>
  );
}
