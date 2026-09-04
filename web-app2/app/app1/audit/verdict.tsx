"use client";

// The verdict: one sentence in green or coral, after the server has recomputed
// every hash in order. Until then, a single primary button. `writes.verifyChain`
// is a real cryptographic check against the audit hash chain (CLAUDE.md) — this
// component never invents its own pass/fail, only renders what the server said.

import { AnimatePresence, motion } from "framer-motion";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { FcErrorNote, StatusDot } from "../_components/fc-ui";
import { CountUp } from "../_components/motion";
import { formatCount, plural } from "../_lib/format";
import type { Phase, VerifyChainOut } from "./chain";

const MONO = "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";

export function ChainVerdict({
  total,
  phase,
  result,
  error,
  onVerify,
}: {
  total: number;
  phase: Phase;
  result: VerifyChainOut | null;
  error: string | null;
  onVerify: () => void;
}) {
  const sweeping = phase === "sweeping";
  const settled = phase === "done";

  return (
    <div className="flex min-h-[112px] flex-col justify-between gap-5 md:flex-row md:items-start">
      <div className="min-w-0 flex-1">
        <AnimatePresence mode="wait" initial={false}>
          {!settled || (!result && !error) ? (
            <motion.div
              key={sweeping ? "sweep" : "idle"}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.25 }}
            >
              <p className="fc-title" style={{ fontSize: 20, maxWidth: 820 }}>
                {sweeping ? (
                  <>Recomputing every hash in order.</>
                ) : (
                  <>
                    <span style={{ fontFamily: MONO }}>
                      <CountUp value={total} className="fc-num fc-strong" />
                    </span>{" "}
                    events on record. Nothing here has been checked yet.
                  </>
                )}
              </p>
              <p className="fc-body mt-2" style={{ maxWidth: 720 }}>
                Each event stores the hash of the previous one. Change any row and every later hash stops matching.
              </p>
            </motion.div>
          ) : error ? (
            <motion.div key="err" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              <p className="fc-title" style={{ fontSize: 20, maxWidth: 820, color: "var(--fc-bad)" }}>
                The chain could not be checked.
              </p>
              <div className="mt-3" style={{ maxWidth: 560 }}>
                <FcErrorNote message={error} />
              </div>
            </motion.div>
          ) : result && result.valid ? (
            <motion.div key="ok" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              <p className="fc-title" style={{ fontSize: 20, maxWidth: 820, color: "var(--fc-ok)" }}>
                <ShieldCheck size={20} className="mr-2 inline-block align-[-3px]" aria-hidden />
                Record intact.{" "}
                <span style={{ fontFamily: MONO, color: "var(--fc-ok)" }}>
                  <CountUp value={result.checked} className="fc-num fc-strong" />
                </span>{" "}
                events verified, every hash links to the one before.
              </p>
              <VerdictFootnotes result={result} />
            </motion.div>
          ) : result ? (
            <motion.div key="bad" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
              <p className="fc-title" style={{ fontSize: 20, maxWidth: 820, color: "var(--fc-bad)" }}>
                <ShieldAlert size={20} className="mr-2 inline-block align-[-3px]" aria-hidden />
                Record broken at <span className="fc-num" style={{ fontFamily: MONO }}>#{result.first_break_seq ?? "?"}</span>
                {result.reason ? <>: {result.reason}</> : "."}
              </p>
              <VerdictFootnotes result={result} />
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>

      <div className="flex shrink-0 flex-col items-start gap-2 md:items-end">
        <button
          type="button"
          className="fc-btn"
          disabled={total === 0 || sweeping}
          onClick={onVerify}
          style={settled && result?.valid ? { background: "var(--fc-divider)", color: "var(--fc-text-2)" } : undefined}
        >
          {sweeping ? "Verifying…" : settled ? "Verify again" : "Verify the chain"}
        </button>
        {settled && result && (
          <div className="fc-faint" style={{ fontSize: 11.5 }}>
            <span className="fc-num" style={{ fontFamily: MONO }}>{formatCount(result.checked)}</span> checked
          </div>
        )}
      </div>
    </div>
  );
}

function VerdictFootnotes({ result }: { result: VerifyChainOut }) {
  const gaps = result.gaps ?? [];
  const missing = gaps.reduce((acc, g) => acc + g.missing, 0);
  return (
    <div className="mt-3 flex flex-col gap-2">
      <p className="fc-body" style={{ maxWidth: 720 }}>
        Each event stores the hash of the previous one. Change any row and every later hash stops matching.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {result.advisory && <StatusDot tone="warn">{result.advisory}</StatusDot>}
        {gaps.length > 0 ? (
          <span className="fc-faint" style={{ fontSize: 12 }}>
            {plural(gaps.length, "sequence gap")} ({formatCount(missing)} numbers skipped). Normal for a database that
            burns sequence numbers on rolled-back transactions.
          </span>
        ) : (
          <span className="fc-faint" style={{ fontSize: 12 }}>No sequence gaps.</span>
        )}
      </div>
    </div>
  );
}
