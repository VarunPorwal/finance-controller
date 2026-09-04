"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { Sparkles } from "lucide-react";
import { AskPanel } from "@/components/ask-panel";
import { PageHeader } from "@/components/page-header";
import { Pill } from "@/components/ui/pill";

function AskScreen() {
  const params = useSearchParams();
  const initial = params.get("q");
  return (
    <div className="flex h-[calc(100vh-140px)] flex-col">
      <PageHeader
        title={
          <span className="flex items-center gap-2.5">
            <Sparkles width={18} height={18} className="text-model" />
            Ask the books
            <Pill tone="model">model output</Pill>
          </span>
        }
        sub="Narration over deterministic results. The model writes SQL inside a read-only, tenant-scoped transaction and describes what came back. It never decides what is reconciled."
      />
      <div className="min-h-0 flex-1">
        <AskPanel initialQuestion={initial} />
      </div>
    </div>
  );
}

export default function AskPage() {
  return (
    <Suspense>
      <AskScreen />
    </Suspense>
  );
}
