"use client";

// The five direct actions, each previewed with dry_run before it runs.
// Finco-skinned: fc-btn/fc-chip in place of the old a1 Button/Pill kit.

import { useState } from "react";
import { errorMessage, useWrite, writes, type Exception } from "../_lib/api";
import { CATEGORY, STATUS_LABEL, categoryLabel, decidedBy, type Category } from "../_lib/labels";
import { formatDateShort } from "../_lib/format";
import { CATEGORIES } from "./helpers";

type Verb = "resolve" | "write_off" | "snooze" | "escalate" | "reclassify";

const VERBS: { key: Verb; label: string; hint: string }[] = [
  { key: "resolve", label: "Resolve", hint: "You know what this is and it is settled." },
  { key: "write_off", label: "Write off", hint: "Below threshold. Recorded as a loss, with a reason." },
  { key: "snooze", label: "Snooze", hint: "Recheck on a date. It comes back on its own." },
  { key: "escalate", label: "Escalate", hint: "Hand it to someone who can decide." },
  { key: "reclassify", label: "Reclassify", hint: "The category is wrong. Say which one it is." },
];

type Args = { verb: Verb; reason: string; until: string; category: Category | ""; dry: boolean };

type WriteResult = Promise<{ data?: Exception; error?: unknown }>;

function call(id: string, a: Args): WriteResult {
  switch (a.verb) {
    case "resolve":
      return writes.resolve(id, { reason: a.reason }, a.dry);
    case "write_off":
      return writes.writeOff(id, { reason: a.reason }, a.dry);
    case "snooze":
      return writes.snooze(id, { reason: a.reason, until: a.until }, a.dry);
    case "escalate":
      return writes.escalate(id, { reason: a.reason }, a.dry);
    case "reclassify":
      return writes.reclassify(id, { reason: a.reason, category: a.category || "unknown" }, a.dry);
  }
}

const inputCls =
  "rounded-[8px] border bg-[var(--fc-hover)] px-3 py-2 text-[12.5px] text-[var(--fc-text)] placeholder:text-[var(--fc-text-3)] outline-none";

export function QuickActions({
  exception,
  note,
  onApplied,
}: {
  exception: Exception;
  note?: string;
  onApplied: () => void;
}) {
  const [verb, setVerb] = useState<Verb | null>(null);
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [preview, setPreview] = useState<Exception | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Exception | null>(null);
  const apply = useWrite((a: Args) => call(exception.exception_id, a));

  const ready =
    !!verb && reason.trim().length > 0 && (verb !== "snooze" || !!until) && (verb !== "reclassify" || !!category);
  const args = (dry: boolean): Args => ({ verb: verb ?? "resolve", reason: reason.trim(), until, category, dry });

  function pick(v: Verb) {
    setVerb(v === verb ? null : v);
    setPreview(null);
    setError(null);
    setDone(null);
  }

  async function doPreview() {
    if (!ready) return;
    setPreviewing(true);
    setError(null);
    setPreview(null);
    try {
      const res = await call(exception.exception_id, args(true));
      if (res.error || !res.data) setError(errorMessage(res.error));
      else setPreview(res.data);
    } catch {
      setError("Could not reach the API.");
    } finally {
      setPreviewing(false);
    }
  }

  async function doApply() {
    if (!ready || !preview) return;
    setError(null);
    try {
      const out = await apply.mutateAsync(args(false));
      setDone(out);
      setVerb(null);
      setPreview(null);
      setReason("");
      onApplied();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const hint = VERBS.find((v) => v.key === verb)?.hint;

  return (
    <section>
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="fc-label">Quick actions</div>
        {note && <span className="fc-faint text-[12px]">{note}</span>}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {VERBS.map((v) => (
          <button
            key={v.key}
            className={verb === v.key ? "fc-btn" : "fc-btn fc-btn--ghost"}
            style={{ padding: "6px 12px", fontSize: 12 }}
            onClick={() => pick(v.key)}
            title={v.hint}
            aria-pressed={verb === v.key}
          >
            {v.label}
          </button>
        ))}
      </div>

      {verb && (
        <div className="mt-3 rounded-[10px] border p-3" style={{ background: "var(--fc-hover)" }}>
          {hint && <div className="fc-faint mb-2 text-[12px]">{hint}</div>}
          <div className="flex flex-wrap gap-2">
            <input
              className={`${inputCls} min-w-[220px] flex-1`}
              placeholder="Reason, for the audit trail"
              value={reason}
              onChange={(ev) => setReason(ev.target.value)}
              aria-label="Reason"
            />
            {verb === "snooze" && (
              <input
                type="date"
                className={`${inputCls} fc-num w-[170px]`}
                value={until}
                onChange={(ev) => setUntil(ev.target.value)}
                aria-label="Recheck on"
              />
            )}
            {verb === "reclassify" && (
              <select
                className={`${inputCls} w-[240px]`}
                value={category}
                onChange={(ev) => setCategory(ev.target.value as Category | "")}
                aria-label="New category"
              >
                <option value="">Choose a category</option>
                {CATEGORIES.filter((c) => c !== exception.category).map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY[c].label}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              className="fc-btn fc-btn--ghost"
              style={{ padding: "6px 12px", fontSize: 12 }}
              onClick={() => void doPreview()}
              disabled={!ready || previewing}
            >
              {previewing ? "Previewing…" : "Preview"}
            </button>
            <button
              className="fc-btn"
              style={{ padding: "6px 12px", fontSize: 12 }}
              onClick={() => void doApply()}
              disabled={!ready || !preview || apply.isPending}
            >
              {apply.isPending ? "Applying…" : "Apply"}
            </button>
            {preview && (
              <span className="fc-faint text-[12px]">
                Would become <span className="fc-strong">{STATUS_LABEL[preview.status]}</span>
                {" · "}
                {decidedBy(preview)}
                {preview.category !== exception.category ? ` · ${categoryLabel(preview.category)}` : ""}
                {preview.recheck_at ? ` · rechecked ${formatDateShort(preview.recheck_at)}` : ""}
              </span>
            )}
          </div>
          {error && (
            <div className="mt-3 text-[12px]" style={{ color: "var(--fc-bad)" }}>
              {error}
            </div>
          )}
        </div>
      )}

      {done && !verb && (
        <div className="mt-2 text-[12px]" style={{ color: "var(--fc-ok)" }}>
          Applied. Now {STATUS_LABEL[done.status]}, decided by {decidedBy(done)}.
        </div>
      )}
      {error && !verb && (
        <div className="mt-2 text-[12px]" style={{ color: "var(--fc-bad)" }}>
          {error}
        </div>
      )}
    </section>
  );
}
