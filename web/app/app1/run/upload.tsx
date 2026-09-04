"use client";

// Three source slots, any of which may be empty, a bank opening balance
// (required to read the bank statement's balance chain, no default), and
// "Confirm and run" once at least one file is in. Uploads go to the generic
// ingest endpoint as multipart; the results are lifted to the page so the
// source cards and findings can read them.

import { useState, type ChangeEvent, type ReactNode } from "react";
import { clsx } from "clsx";
import { BookOpenCheck, CreditCard, Landmark, Upload } from "lucide-react";
import { apiClient } from "@/lib/client";
import { ErrorNote } from "../_components/ui";
import { errorMessage, writes, type S } from "../_lib/api";
import { fieldStyle } from "./_shared";
import type { SourceKey } from "./timeline";

export type IngestOut = S["IngestOut"];
export type BreakOut = S["BreakOut"];
export type RejectionOut = S["RejectionOut"];

export interface UploadSlot {
  fileName: string;
  loading: boolean;
  result: IngestOut | null;
  error: string | null;
  /** Balance breaks the server reported, whether it accepted the file or refused it. */
  breaks: BreakOut[];
}

export type Uploads = Partial<Record<SourceKey, UploadSlot>>;

const ACCEPT = ".csv,.json,.xml,.pdf,.txt";
const ORDER: SourceKey[] = ["razorpay", "bank", "ledger"];

const SOURCE_ICON: Record<SourceKey, ReactNode> = {
  razorpay: <CreditCard size={20} />,
  bank: <Landmark size={20} />,
  ledger: <BookOpenCheck size={20} />,
};
const SOURCE_HEADING: Record<SourceKey, string> = {
  razorpay: "Razorpay",
  bank: "Bank",
  ledger: "Tally",
};
const SOURCE_DESC: Record<SourceKey, string> = {
  razorpay: "Settlement export, JSON",
  bank: "Statement, CSV or PDF",
  ledger: "Day book export, CSV or XML",
};

export async function uploadFile(
  source: SourceKey,
  runId: string,
  file: File,
  openingBalancePaise?: number,
): Promise<UploadSlot> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await apiClient.POST("/api/v1/ingest/upload", {
    params: { query: { source, run_id: runId, opening_balance_paise: openingBalancePaise } },
    // openapi-typescript renders the multipart `file: binary` field as
    // `file: string`, so the typed body carries the filename to satisfy the
    // contract, and bodySerializer hands openapi-fetch the real FormData. It
    // sends FormData without a JSON content-type so the browser sets the
    // multipart boundary. No cast needed.
    body: { file: file.name },
    bodySerializer: () => fd,
  });
  if (res.error || !res.data) {
    // A refused bank statement reports its breaks alongside `detail`; the
    // generated error type only knows the 422 validation shape.
    const err = res.error as unknown as { breaks?: BreakOut[] } | undefined;
    return { fileName: file.name, loading: false, result: null, error: errorMessage(res.error), breaks: err?.breaks ?? [] };
  }
  return { fileName: file.name, loading: false, result: res.data, error: null, breaks: res.data.breaks };
}

/** "12345.5" -> 1234550 paise. The one place user-typed rupees becomes an
 * integer for the API; nothing downstream ever divides or floats a stored
 * figure. */
function parsePaise(rupees: string): number | undefined {
  const n = Number(rupees);
  if (!rupees.trim() || Number.isNaN(n) || n < 0) return undefined;
  return Math.round(n * 100);
}

export function UploadPanel({
  ruleSet,
  pendingRunId,
  onRunOpened,
  uploads,
  onSlot,
  onFinalize,
  busy,
}: {
  ruleSet: string;
  pendingRunId: string | null;
  onRunOpened: (runId: string) => void;
  uploads: Uploads;
  onSlot: (source: SourceKey, slot: UploadSlot) => void;
  onFinalize: (runId: string) => void;
  busy: boolean;
}) {
  const [openingBalance, setOpeningBalance] = useState("");
  const [openError, setOpenError] = useState<string | null>(null);

  const openingPaise = parsePaise(openingBalance);
  const bankReady = openingPaise !== undefined;

  async function ensureRun(): Promise<string | null> {
    if (pendingRunId) return pendingRunId;
    const res = await writes.createRun({ mode: "empty", seed: 7, rule_set: ruleSet, label: null });
    if (res.error || !res.data) {
      setOpenError(errorMessage(res.error));
      return null;
    }
    onRunOpened(res.data.run_id);
    return res.data.run_id;
  }

  async function pick(source: SourceKey, e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setOpenError(null);
    onSlot(source, { fileName: file.name, loading: true, result: null, error: null, breaks: [] });
    const runId = await ensureRun();
    if (!runId) {
      onSlot(source, { fileName: file.name, loading: false, result: null, error: "Could not open a run to ingest into.", breaks: [] });
      return;
    }
    onSlot(source, await uploadFile(source, runId, file, source === "bank" ? openingPaise : undefined));
  }

  const uploaded = ORDER.filter((s) => uploads[s]?.result).length;

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-3">
        {ORDER.map((s) => (
          <Slot
            key={s}
            source={s}
            slot={uploads[s]}
            onPick={(e) => void pick(s, e)}
            disabled={busy || (s === "bank" && !bankReady)}
          />
        ))}
      </div>

      <label className="flex items-center gap-3">
        <span className="fc-label shrink-0">Bank opening balance ₹ (required)</span>
        <input
          type="number"
          inputMode="decimal"
          min={0}
          step="0.01"
          placeholder="0.00"
          value={openingBalance}
          onChange={(e) => setOpeningBalance(e.target.value)}
          style={{ ...fieldStyle, maxWidth: 200 }}
          className="fc-num"
        />
        {!bankReady && <span className="fc-faint" style={{ fontSize: 11.5 }}>Needed before the bank file can be read</span>}
      </label>

      {openError && <ErrorNote message={openError} />}

      <div className="flex items-center justify-end gap-3">
        <span className="fc-faint" style={{ fontSize: 12 }}>
          {pendingRunId
            ? `${uploaded} of 3 sources in the open run. Finalising runs the cascade over what was uploaded.`
            : "The first upload opens an empty run. Nothing is reconciled until you finalise."}
        </span>
        <button
          className="fc-btn"
          disabled={!pendingRunId || uploaded === 0 || busy || (uploads.bank && !bankReady)}
          onClick={() => pendingRunId && onFinalize(pendingRunId)}
        >
          Confirm and run
        </button>
      </div>
    </div>
  );
}

function Slot({
  source,
  slot,
  onPick,
  disabled,
}: {
  source: SourceKey;
  slot: UploadSlot | undefined;
  onPick: (e: ChangeEvent<HTMLInputElement>) => void;
  disabled: boolean;
}) {
  return (
    <div
      className="fc-card flex flex-col items-center justify-center gap-1.5 text-center"
      style={{ minHeight: 200, padding: "18px 16px" }}
    >
      <span
        className="flex items-center justify-center"
        style={{ width: 40, height: 40, borderRadius: 10, background: "var(--fc-accent-dim)", color: "var(--fc-accent)" }}
      >
        {SOURCE_ICON[source]}
      </span>
      <div className="fc-card-title" style={{ display: "block", fontSize: 14, marginTop: 4 }}>{SOURCE_HEADING[source]}</div>
      <span className="fc-faint" style={{ fontSize: 11.5 }}>{SOURCE_DESC[source]}</span>

      <label className={clsx("fc-btn fc-btn--ghost mt-1.5", disabled && "pointer-events-none opacity-50")} style={{ padding: "6px 12px", fontSize: 11.5 }}>
        <Upload size={12} />
        {slot?.loading ? "Uploading…" : "Import"}
        <input type="file" accept={ACCEPT} className="sr-only" onChange={onPick} disabled={disabled || slot?.loading} />
      </label>

      {slot?.fileName ? (
        <span className="fc-faint truncate" style={{ fontSize: 11, maxWidth: "100%" }} title={slot.fileName}>
          {slot.error ? "Not accepted — " : ""}
          {slot.fileName}
        </span>
      ) : (
        <span className="fc-faint" style={{ fontSize: 10.5 }}>csv, json, xml, pdf or txt</span>
      )}
    </div>
  );
}
