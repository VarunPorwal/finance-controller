// Who did it, in words. Actors arrive as "user:<id>" for people and a bare
// service name ("scheduler", "system") for the machine. Nothing here decides
// anything; it only says the actor's name and picks a colour class.

import type { AuditEvent } from "../_lib/api";
import { isHumanActor } from "../_lib/labels";

export type ChainKind = "human" | "system" | "settings";

/** "user:u_demo" -> "Demo". "scheduler" -> "Scheduler". */
export function actorName(actor: string): string {
  const raw = isHumanActor(actor) ? actor.slice("user:".length) : actor;
  const trimmed = raw.replace(/^u_/, "").replace(/[._-]+/g, " ").trim();
  if (!trimmed) return actor;
  return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
}

/** Up to two initials for an avatar circle. */
export function actorInitials(actor: string): string {
  const words = actorName(actor).split(/\s+/).filter(Boolean);
  const letters = words.slice(0, 2).map((w) => w.charAt(0).toUpperCase());
  return letters.join("") || "?";
}

/** Chain-strip colour family for one event. Settings and rule changes read
 * as neutral regardless of who made them; otherwise people are brand, the
 * machine is green. */
export function chainKind(e: Pick<AuditEvent, "actor" | "action">): ChainKind {
  if (e.action.startsWith("settings.") || e.action.startsWith("rule.")) return "settings";
  return isHumanActor(e.actor) ? "human" : "system";
}

export const CHAIN_COLOR: Record<ChainKind, string> = {
  human: "var(--fc-accent)",
  system: "var(--fc-ok)",
  settings: "var(--fc-text-3)",
};

/** Coarse action category for the section-3 filter. Mirrors the vocabulary
 * used by the action labels in `_lib/labels.ts` (`AUDIT_ACTION_LABEL`). */
export type ActionCategory = "decisions" | "rules" | "runs" | "other";

export function actionCategory(action: string): ActionCategory {
  if (action.startsWith("exception.") || action.startsWith("cluster.") || action.startsWith("agent.")) return "decisions";
  if (action.startsWith("rule.")) return "rules";
  if (action.startsWith("run.") || action.startsWith("ingest.")) return "runs";
  return "other";
}

/** Where a subject lives in this app, if anywhere. */
export function subjectHref(subjectType: string, subjectId: string): string | null {
  if (subjectType === "exception") return `/app1/decisions?open=${encodeURIComponent(subjectId)}`;
  if (subjectType === "rule") return "/app1/rules";
  if (subjectType === "run") return "/app1/run";
  return null;
}

const SKIP_KEY = /(^|_)(id|ids|hash|signature|guid)$|^dry_run$|^tenant$/;

export interface PayloadGlance {
  quote: string | null;
  transition: [string, string] | null;
  pairs: [string, string][];
  dryRun: boolean;
}

function scalar(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return null;
}

/** A three-item glance at a payload: a reason or instruction if the human
 * wrote one, a before → after if the event records a state change, then up
 * to three short scalar fields with ids and hashes left out. */
export function glance(payload: Record<string, unknown>): PayloadGlance {
  const quote = scalar(payload.reason) ?? scalar(payload.instruction_text) ?? scalar(payload.instruction) ?? null;

  let transition: [string, string] | null = null;
  const before = scalar(payload.before);
  const after = scalar(payload.after);
  if (before !== null && after !== null) transition = [before, after];
  else {
    for (const k of Object.keys(payload)) {
      if (!k.startsWith("before_")) continue;
      const field = k.slice("before_".length);
      const was = scalar(payload[k]);
      const now = scalar(payload[`after_${field}`]) ?? scalar(payload[field]);
      if (was !== null) {
        transition = [was, now ?? "changed"];
        break;
      }
    }
  }

  const pairs: [string, string][] = [];
  for (const [k, v] of Object.entries(payload)) {
    if (pairs.length >= 3) break;
    if (SKIP_KEY.test(k)) continue;
    if (k === "reason" || k === "instruction_text" || k === "instruction" || k === "before" || k === "after") continue;
    if (k.startsWith("before_") || k.startsWith("after_")) continue;
    const s = scalar(v);
    if (s === null || s.length === 0 || s.length > 48) continue;
    pairs.push([k.replace(/_/g, " "), s]);
  }

  return { quote, transition, pairs, dryRun: payload.dry_run === true };
}
