"use client";

import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Check } from "lucide-react";
import { humanizeSnakeCase } from "@/lib/format";
import { cn } from "@/lib/utils";

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type StageStatus = "pending" | "done" | "running" | "failed";

const EASE = [0.23, 1, 0.32, 1] as const;

/**
 * Consumes `GET /api/v1/runs/{run_id}/progress` (text/event-stream) so a
 * reload mid-run, or right after one, shows the cascade stage by stage.
 *
 * The bar underneath is the sum of what the stream has said so far: done
 * stages fill it, the running stage adds half a step and carries a moving
 * sheen so a stage that takes a while still reads as alive. Nothing here is
 * timed or guessed; a stage moves only when the server says it moved.
 */
export function RunProgressStrip({ runId }: { runId: string | undefined }) {
  const [stages, setStages] = useState<{ stage: string; status: StageStatus }[]>([]);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!runId) return;
    setStages([]);
    setRunStatus(null);
    const source = new EventSource(`${baseUrl}/api/v1/runs/${runId}/progress`);

    source.addEventListener("stage", (evt) => {
      try {
        const payload = JSON.parse((evt as MessageEvent).data) as { stage: string; status: StageStatus };
        setStages((prev) => {
          const idx = prev.findIndex((s) => s.stage === payload.stage);
          if (idx === -1) return [...prev, payload];
          const next = prev.slice();
          next[idx] = payload;
          return next;
        });
      } catch {
        /* malformed event, ignore */
      }
    });
    source.addEventListener("run", (evt) => {
      try {
        const payload = JSON.parse((evt as MessageEvent).data) as { status: string };
        setRunStatus(payload.status);
      } catch {
        /* malformed event, ignore */
      }
      source.close();
    });
    source.onerror = () => source.close();
    return () => source.close();
  }, [runId]);

  if (!runId || stages.length === 0) return null;

  const done = stages.filter((s) => s.status === "done").length;
  const running = stages.some((s) => s.status === "running");
  const failed = stages.some((s) => s.status === "failed");
  const complete = runStatus === "complete" || (done === stages.length && !running);
  const fraction = complete ? 1 : (done + (running ? 0.5 : 0)) / stages.length;
  const pct = Math.round(fraction * 100);
  const live = running && !complete && !failed;

  return (
    <div className="panel mb-5 px-[18px] py-3.5">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="label">Pipeline</div>
          {live && (
            <span className="flex items-center gap-1.5 text-[11px] text-accent">
              <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />
              live
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="num text-[11px] text-ink-3">
            {done}/{stages.length} stages
          </span>
          <span className={cn("num text-[11px] font-semibold", failed ? "text-bad" : complete ? "text-ok" : "text-accent")}>
            {failed ? "failed" : complete ? "complete" : `${pct}%`}
          </span>
        </div>
      </div>

      <div className="relative mb-3.5 h-[6px] overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
        <motion.div
          className={cn("relative h-full rounded-full", failed ? "bg-bad" : complete ? "bg-ok" : "bg-accent")}
          initial={false}
          animate={{ width: `${pct}%` }}
          transition={reduceMotion ? { duration: 0 } : { duration: 0.6, ease: EASE }}
        >
          {live && !reduceMotion && (
            <motion.span
              aria-hidden
              className="absolute inset-y-0 w-1/2"
              style={{ background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.45), transparent)" }}
              initial={{ x: "-100%" }}
              animate={{ x: "300%" }}
              transition={{ duration: 1.4, ease: "linear", repeat: Infinity }}
            />
          )}
        </motion.div>
      </div>

      <ol className="flex items-center gap-2 overflow-x-auto">
        {stages.map((s, i) => (
          <li key={s.stage} className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 whitespace-nowrap">
              <motion.span
                layout
                className={cn(
                  "flex h-[18px] w-[18px] items-center justify-center rounded-full border text-[10px]",
                  s.status === "done" && "border-[rgba(61,220,151,0.4)] bg-ok-soft text-ok",
                  s.status === "running" && "border-[rgba(138,180,255,0.4)] bg-accent-soft text-accent",
                  s.status === "failed" && "border-[rgba(255,107,107,0.4)] bg-bad-soft text-bad",
                  s.status === "pending" && "border-line-strong text-ink-4",
                )}
                animate={s.status === "running" && !reduceMotion ? { scale: [1, 1.12, 1] } : { scale: 1 }}
                transition={s.status === "running" ? { duration: 1.2, repeat: Infinity, ease: "easeInOut" } : { duration: 0.2 }}
              >
                {s.status === "done" && (
                  <motion.span
                    initial={reduceMotion ? false : { scale: 0.4, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ duration: 0.25, ease: EASE }}
                    className="flex"
                  >
                    <Check width={10} height={10} />
                  </motion.span>
                )}
                {s.status === "running" && <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />}
                {s.status === "failed" && "!"}
              </motion.span>
              <span
                className={cn(
                  "text-[12px] transition-colors duration-300",
                  s.status === "done" && "text-ink-2",
                  s.status === "running" && "font-medium text-ink",
                  (s.status === "pending" || s.status === "failed") && "text-ink-3",
                )}
              >
                {humanizeSnakeCase(s.stage)}
              </span>
            </span>
            {i < stages.length - 1 && (
              <span className="relative h-px w-6 overflow-hidden bg-line-strong">
                <motion.span
                  className="absolute inset-y-0 left-0 bg-ok"
                  initial={false}
                  animate={{ width: s.status === "done" ? "100%" : "0%" }}
                  transition={reduceMotion ? { duration: 0 } : { duration: 0.4, ease: EASE }}
                />
              </span>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
