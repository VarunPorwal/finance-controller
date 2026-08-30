// PRD §13.2: signal colours appear ONLY on tier indicators and their
// attached amounts. This is the one place that mapping lives, so nothing
// else in the tree invents its own tier -> colour rule.

export type Tier = "auto" | "monitor" | "escalate";

export const TIER_COLOR: Record<Tier, string> = {
  auto: "text-sig-green",
  monitor: "text-sig-amber",
  escalate: "text-sig-red",
};

export const TIER_DOT: Record<Tier, string> = {
  auto: "🟢",
  monitor: "🟡",
  escalate: "🔴",
};

export const TIER_LABEL: Record<Tier, string> = {
  auto: "Auto-resolved",
  monitor: "Monitor",
  escalate: "Escalate",
};
