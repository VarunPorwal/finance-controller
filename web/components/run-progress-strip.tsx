"use client";

import { useEffect, useState } from "react";
import { CheckCircle2, Circle, LoaderCircle } from "lucide-react";
import { humanizeSnakeCase } from "@/lib/format";

const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type StageStatus = "pending" | "done" | "running" | "failed";

/**
 * Consumes `GET /api/v1/runs/{run_id}/progress` (text/event-stream) so a
 * reload mid-run — or, for the demo's synchronous pipeline, a reload right
 * after one — shows the stage-by-stage status instead of nothing. Re-opens
 * whenever `runId` changes.
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
        setStages((prev) => {
          const next = prev.filter((s) => s.stage !== payload.stage);
          return [...next, payload];
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

  return (
    <div className="fc-card mb-5 overflow-hidden">
      <div className="flex items-center justify-between border-b border-border px-[22px] py-3.5">
        <div className="text-sm font-semibold">Pipeline progress</div>
        {runStatus && <span className="text-[11px] text-text-muted">run status: {runStatus}</span>}
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-2 px-[22px] py-3.5">
        {stages.map((s) => (
          <div key={s.stage} className="flex items-center gap-1.5 text-[12.5px]">
            {s.status === "done" && <CheckCircle2 width={14} height={14} color="var(--success)" />}
            {s.status === "running" && <LoaderCircle width={14} height={14} className="animate-spin" color="var(--primary)" />}
            {s.status !== "done" && s.status !== "running" && <Circle width={14} height={14} color="var(--text-faint)" />}
            <span className={s.status === "done" ? "text-text-body" : "text-text-muted"}>
              {humanizeSnakeCase(s.stage)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
