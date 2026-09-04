"use client";

// Source cards, shown once a run exists: what was read, how much of it is in
// scope for this run, and — for whatever was uploaded this session — how
// much the parser rejected. "In scope" is the one figure every run has (the
// events actually created for it); "read" and "rejected" only exist for a
// file this browser session uploaded, so they are shown only then rather
// than guessed for the demo corpus or an earlier run.

import { clsx } from "clsx";
import { ShieldCheck, ShieldAlert } from "lucide-react";
import { formatDateTime, formatCount, money } from "../_lib/format";
import { bytes } from "../_lib/format";
import { skel, SourceDot } from "./_shared";
import type { IngestedFile } from "../_lib/api";
import type { SourceKey } from "./timeline";
import type { UploadSlot } from "./upload";

const ORDER: SourceKey[] = ["razorpay", "bank", "ledger"];

export function latestFiles(files: IngestedFile[] | undefined): Partial<Record<SourceKey, IngestedFile>> {
  const out: Partial<Record<SourceKey, IngestedFile>> = {};
  for (const f of files ?? []) {
    const key = f.source as SourceKey;
    if (!ORDER.includes(key)) continue;
    const cur = out[key];
    if (!cur || cur.uploaded_at < f.uploaded_at) out[key] = f;
  }
  return out;
}

function BalanceVerdict({ slot }: { slot: UploadSlot | undefined }) {
  if (!slot) return null;
  const broke = slot.result?.balanced === false || (slot.error != null && slot.breaks.length > 0);
  if (broke) {
    const b = slot.breaks[0];
    return (
      <div className="flex items-start gap-1.5" style={{ fontSize: 12, color: "var(--fc-bad)" }}>
        <ShieldAlert size={13} className="mt-0.5 shrink-0" />
        <span>
          Balance chain broke{b ? ` at row ${b.row}` : ""}.
          {b && (
            <>
              {" "}
              Expected <span className="fc-num">{money(b.expected_paise)}</span>, found <span className="fc-num">{money(b.found_paise)}</span>.
            </>
          )}
        </span>
      </div>
    );
  }
  if (slot.result?.balanced) {
    return (
      <div className="flex items-center gap-1.5 fc-muted" style={{ fontSize: 12 }}>
        <ShieldCheck size={13} />
        Balance chain verified
      </div>
    );
  }
  return null;
}

export function SourceCards({
  files,
  counts,
  loading,
  bankSlot,
}: {
  files: Partial<Record<SourceKey, IngestedFile>>;
  counts: Partial<Record<string, number>> | undefined;
  loading: boolean;
  bankSlot: UploadSlot | undefined;
}) {
  if (loading) {
    return (
      <div className="fc-row4">
        {ORDER.map((s) => (
          <div key={s}>{skel("h-40 w-full")}</div>
        ))}
      </div>
    );
  }
  return (
    <div className="grid grid-cols-3 gap-3">
      {ORDER.map((s) => {
        const f = files[s];
        const inScope = counts?.[s] ?? 0;
        return (
          <div key={s} className="fc-card flex h-full flex-col gap-2.5">
            <div className="flex items-center justify-between gap-2">
              <SourceDot source={s} />
            </div>
            <div className="min-w-0">
              {f ? (
                <>
                  <div className="fc-row-val truncate" title={f.filename}>
                    {f.filename}
                  </div>
                  <div className="fc-faint mt-0.5" style={{ fontSize: 11.5 }}>
                    {bytes(f.size_bytes)} · {formatDateTime(f.uploaded_at)}
                  </div>
                </>
              ) : (
                <span className="fc-faint" style={{ fontSize: 12 }}>No file on record for this source.</span>
              )}
            </div>
            <div className="flex items-baseline gap-2">
              <span className="fc-metric-val fc-num">{formatCount(inScope)}</span>
              <span className="fc-faint" style={{ fontSize: 12 }}>in scope</span>
            </div>
            {s === "bank" && (
              <>
                {uploadRow(bankSlot)}
                <BalanceVerdict slot={bankSlot} />
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Only the bank slot is lifted to the page today (it is the one the balance
 * chain depends on), so razorpay/ledger cards fall back to the "in scope"
 * figure every run has rather than a per-file read/rejected breakdown. */
function uploadRow(slot: UploadSlot | undefined) {
  const r = slot?.result;
  if (!r) return null;
  return (
    <div className="flex items-center gap-3" style={{ fontSize: 11.5 }}>
      <span className="fc-faint">{formatCount(r.event_count)} read</span>
      <span
        className={clsx(r.rejections.length > 0 ? "fc-bad" : "fc-faint")}
      >
        {formatCount(r.rejections.length)} rejected
      </span>
    </div>
  );
}
