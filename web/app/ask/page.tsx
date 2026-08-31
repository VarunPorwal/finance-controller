"use client";

import { AskPanel } from "@/components/ask-panel";

export default function AskPage() {
  return (
    <div>
      <div className="mb-4">
        <div className="flex items-center gap-2">
          <div className="text-[22px] font-semibold tracking-[-0.025em]">Ask Controller</div>
          <span className="rounded-[6px] bg-model-pill-bg px-[7px] py-[2px] text-[10px] font-semibold text-model-text">
            Model output
          </span>
        </div>
        <div className="mt-[3px] text-[13px] text-text-muted">
          Everything on this page is narration over deterministic results — the model never
          decides what's reconciled.
        </div>
      </div>
      <div className="h-[calc(100vh-220px)]">
        <AskPanel />
      </div>
    </div>
  );
}
