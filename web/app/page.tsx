import { AppShell } from "@/components/app-shell";
import { RunProvider } from "@/lib/run-context";
import { ReconcilePanel } from "@/components/reconcile-panel";
import { RulebookPanel } from "@/components/rulebook-panel";
import { AskPanel } from "@/components/ask-panel";

export default function Home() {
  return (
    <RunProvider>
      <AppShell
        reconcile={<ReconcilePanel />}
        rulebook={<RulebookPanel />}
        ask={<AskPanel />}
      />
    </RunProvider>
  );
}
