"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { humanizeSnakeCase } from "@/lib/format";
import { cn } from "@/lib/utils";

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type StageStatus = "pending" | "done" | "running" | "failed";

/**
 * Consumes `GET /api/v1/runs/{run_id}/progress` (text/event-stream) so a
 * reload mid-run, or right after one, shows the cascade stage by stage.
 */
export function RunProgressStrip({ runId }: { runId: string | undefined }) {
  const [stages, setStages] = useState<{ stage: string; status: StageStatus }[]>([]);
  const [runStatus, setRunStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    setStages([]);
    setRunStatus(null);
    const source = new EventSource(`${baseUrl}/api/v1/runs/${runId}/progress`);

    source.addEventListener("stage", (evt) => {
      try {
        const payload = JSON.parse((evt as MessageEvent).data) as { stage: string; status: StageStatus };
        setStages((prev) => [...prev.filter((s) => s.stage !== payload.stage), payload]);
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

  return (
    <div className="panel mb-5 px-[18px] py-3.5">
      <div className="mb-3 flex items-center justify-between">
        <div className="label">Pipeline</div>
        {runStatus && (
          <span className={cn("num text-[11px]", runStatus === "complete" ? "text-ok" : "text-warn")}>{runStatus}</span>
        )}
      </div>
      <ol className="flex items-center gap-2 overflow-x-auto">
        {stages.map((s, i) => (
          <li key={s.stage} className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 whitespace-nowrap">
              <span
                className={cn(
                  "flex h-[18px] w-[18px] items-center justify-center rounded-full border text-[10px]",
                  s.status === "done" && "border-[rgba(61,220,151,0.4)] bg-ok-soft text-ok",
                  s.status === "running" && "border-[rgba(138,180,255,0.4)] bg-accent-soft text-accent",
                  s.status === "failed" && "border-[rgba(255,107,107,0.4)] bg-bad-soft text-bad",
                  s.status === "pending" && "border-line-strong text-ink-4",
                )}
              >
                {s.status === "done" && <Check width={10} height={10} />}
                {s.status === "running" && <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />}
                {s.status === "failed" && "!"}
              </span>
              <span className={cn("text-[12px]", s.status === "done" ? "text-ink-2" : "text-ink-3")}>{humanizeSnakeCase(s.stage)}</span>
            </span>
            {i < stages.length - 1 && <span className="h-px w-6 bg-line-strong" />}
          </li>
        ))}
      </ol>
    </div>
  );
}
