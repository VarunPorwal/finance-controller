"use client";

export type TabKey = "reconcile" | "rulebook" | "ask";

const TABS: { key: TabKey; label: string }[] = [
  { key: "reconcile", label: "Reconcile" },
  { key: "rulebook", label: "Rulebook" },
  { key: "ask", label: "Ask" },
];

export function TabNav({
  active,
  onChange,
}: {
  active: TabKey;
  onChange: (tab: TabKey) => void;
}) {
  return (
    <nav aria-label="Sections" className="flex items-center gap-1">
      {TABS.map((tab) => {
        const isActive = tab.key === active;
        return (
          <button
            key={tab.key}
            type="button"
            onClick={() => onChange(tab.key)}
            aria-current={isActive ? "page" : undefined}
            className={
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rzp-blue " +
              (isActive
                ? "bg-rzp-deep text-paper-100"
                : "text-paper-300 hover:bg-ink-700 hover:text-paper-100")
            }
          >
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}
