// Signal colours appear only on tier indicators and their attached amounts.
// This is the one place the tier -> tone mapping lives.

export type Tier = "auto" | "monitor" | "escalate";
export type Tone = "ok" | "warn" | "bad";

export const TIER_TONE: Record<Tier, Tone> = {
  auto: "ok",
  monitor: "warn",
  escalate: "bad",
};

export const TIER_TEXT: Record<Tier, string> = {
  auto: "text-ok",
  monitor: "text-warn",
  escalate: "text-bad",
};

export const TIER_LABEL: Record<Tier, string> = {
  auto: "Auto-resolved",
  monitor: "Monitor",
  escalate: "Needs you",
};

export const TIER_SHORT: Record<Tier, string> = {
  auto: "Auto",
  monitor: "Monitor",
  escalate: "Needs you",
};
