"use client";

import { useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";

type IngestOut = components["schemas"]["IngestOut"];
type Source = "razorpay" | "bank" | "ledger";

const SOURCES: { key: Source; label: string; accept: string }[] = [
  { key: "razorpay", label: "Razorpay recon (JSON)", accept: ".json" },
  { key: "bank", label: "Bank statement (CSV or PDF)", accept: ".csv,.pdf" },
  { key: "ledger", label: "Tally ledger export (CSV)", accept: ".csv" },
];

interface SlotState {
  fileName: string | null;
  loading: boolean;
  result: IngestOut | null;
  error: { detail: string; breaks?: { row: number; expected_paise: number; found_paise: number }[]; rowCount?: number } | null;
}

const EMPTY_SLOT: SlotState = { fileName: null, loading: false, result: null, error: null };

/**
 * PRD §5.4/§7.7: three source slots, format auto-detected within the bank
 * slot (a PDF and a CSV both land there — `detect_bank_format` decides,
 * this component never declares it). One-click demo corpus alongside it.
 * `POST /runs` with `mode=empty` opens a run with nothing in it; each slot
 * ingests into that run_id; `POST /runs/{id}/finalize` runs the cascade
 * over whatever actually got uploaded.
 */
export function IngestPanel({ onComplete, onClose }: { onComplete: () => void; onClose: () => void }) {
  const [runId, setRunId] = useState<string | null>(null);
  const [openingBalanceRupees, setOpeningBalanceRupees] = useState("1000000");
  const [slots, setSlots] = useState<Record<Source, SlotState>>({
    razorpay: { ...EMPTY_SLOT },
    bank: { ...EMPTY_SLOT },
    ledger: { ...EMPTY_SLOT },
  });
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState<string | null>(null);

  async function runDemoCorpus() {
    setDemoRunning(true);
    setDemoError(null);
    const { error } = await apiClient.POST("/api/v1/runs", { body: { mode: "demo", seed: 7 } });
    setDemoRunning(false);
    if (error) {
      setDemoError("Could not start the demo run.");
      return;
    }
    onComplete();
  }

  async function ensureRun(): Promise<string | null> {
    if (runId) return runId;
    const { data, error } = await apiClient.POST("/api/v1/runs", {
      body: { mode: "empty", seed: 7 },
    });
    if (error || !data) return null;
    setRunId(data.run_id);
    return data.run_id;
  }

  async function uploadSlot(source: Source, file: File) {
    const id = await ensureRun();
    if (!id) {
      setSlots((prev) => ({
        ...prev,
        [source]: { ...prev[source], error: { detail: "Could not open a run to ingest into." } },
      }));
      return;
    }
    setSlots((prev) => ({
      ...prev,
      [source]: { fileName: file.name, loading: true, result: null, error: null },
    }));

    const body = new FormData();
    body.append("file", file);
    const query =
      source === "bank"
        ? `run_id=${encodeURIComponent(id)}&opening_balance_paise=${Math.round(Number(openingBalanceRupees) * 100)}`
        : `run_id=${encodeURIComponent(id)}`;
    const path = `/api/v1/ingest/${source}?${query}`;

    // openapi-fetch's typed client expects a JSON body by schema; a
    // multipart upload needs a raw fetch instead — the one deliberate
    // exception to "never hand-write fetch", since the generated client
    // has no multipart form-data path to call instead.
    const token = process.env.NEXT_PUBLIC_DEMO_TOKEN ?? "";
    const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
    const res = await fetch(`${base}${path}`, {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body,
    });

    if (res.ok) {
      const data = (await res.json()) as IngestOut;
      setSlots((prev) => ({
        ...prev,
        [source]: { fileName: file.name, loading: false, result: data, error: null },
      }));
    } else {
      const problem = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      setSlots((prev) => ({
        ...prev,
        [source]: {
          fileName: file.name,
          loading: false,
          result: null,
          error: {
            detail: problem.detail ?? `HTTP ${res.status}`,
            breaks: problem.breaks,
            rowCount: problem.row_count,
          },
        },
      }));
    }
  }

  async function finalize() {
    if (!runId) return;
    setFinalizing(true);
    setFinalizeError(null);
    const { error } = await apiClient.POST("/api/v1/runs/{run_id}/finalize", {
      params: { path: { run_id: runId } },
    });
    setFinalizing(false);
    if (error) {
      setFinalizeError("Could not reconcile — check that at least one source ingested cleanly.");
      return;
    }
    onComplete();
  }

  const anyIngested = Object.values(slots).some((s) => s.result && s.result.event_count > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="border-rzp-blue bg-ink-800 flex max-h-[90vh] w-[min(680px,95vw)] flex-col gap-4 overflow-y-auto rounded-lg border p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="font-heading text-base font-semibold text-paper-100">Start a run</h2>
            <p className="text-paper-500 text-xs">
              Upload real files, or run the demo corpus in one click.
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-paper-500 hover:text-paper-100 text-sm" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="border-rule bg-ink-900 flex items-center justify-between gap-3 rounded-lg border p-3">
          <p className="text-paper-300 text-sm">Run the generated demo corpus, no upload needed.</p>
          <button
            type="button"
            disabled={demoRunning}
            onClick={runDemoCorpus}
            className="bg-rzp-blue hover:bg-rzp-blue/90 shrink-0 rounded-md px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {demoRunning ? "Running…" : "Run demo corpus"}
          </button>
        </div>
        {demoError && <p className="text-sig-amber text-xs">{demoError}</p>}

        <div className="border-rule border-t pt-4">
          <p className="text-paper-300 mb-3 text-xs font-medium uppercase tracking-wide">
            Or upload your own {runId && <span className="fc-numeric text-paper-500">· {runId}</span>}
          </p>

          <label className="mb-3 flex items-center gap-2 text-xs">
            <span className="text-paper-300">Bank opening balance ₹</span>
            <input
              value={openingBalanceRupees}
              onChange={(e) => setOpeningBalanceRupees(e.target.value)}
              className="fc-numeric border-rule bg-ink-900 text-paper-100 w-28 rounded-md border p-1"
            />
          </label>

          <div className="flex flex-col gap-3">
            {SOURCES.map((s) => (
              <SlotRow key={s.key} source={s} state={slots[s.key]} onFile={(f) => uploadSlot(s.key, f)} />
            ))}
          </div>
        </div>

        <div className="border-rule border-t pt-3">
          <button
            type="button"
            disabled={!runId || !anyIngested || finalizing}
            onClick={finalize}
            className="bg-rzp-blue hover:bg-rzp-blue/90 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {finalizing ? "Reconciling…" : "Reconcile what's ingested"}
          </button>
          {finalizeError && <p className="text-sig-amber mt-2 text-xs">{finalizeError}</p>}
        </div>
      </div>
    </div>
  );
}

function SlotRow({
  source,
  state,
  onFile,
}: {
  source: { key: Source; label: string; accept: string };
  state: SlotState;
  onFile: (file: File) => void;
}) {
  return (
    <div className="border-rule bg-ink-900 rounded-lg border p-3">
      <div className="flex items-center justify-between gap-3">
        <label className="text-paper-100 flex-1 text-sm font-medium">
          {source.label}
          <input
            type="file"
            accept={source.accept}
            className="text-paper-300 mt-1 block w-full text-xs"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onFile(file);
            }}
          />
        </label>
      </div>

      {state.loading && (
        <p className="text-paper-500 mt-2 text-xs">Ingesting {state.fileName}…</p>
      )}

      {state.result && (
        <div className="mt-2 text-xs">
          <p className="text-paper-300">
            <span className="text-sig-green font-semibold">{state.result.event_count}</span> rows
            parsed
            {state.result.rejections.length > 0 && (
              <>
                {" · "}
                <span className="text-sig-amber font-semibold">
                  {state.result.rejections.length}
                </span>{" "}
                rejected
              </>
            )}
            {state.result.balanced !== null && state.result.balanced !== undefined && (
              <>
                {" · balance "}
                {state.result.balanced ? (
                  <span className="text-sig-green">continuity holds ✓</span>
                ) : (
                  <span className="text-sig-amber">broke, ingested anyway (CSV is trusted)</span>
                )}
              </>
            )}
          </p>
          {state.result.rejections.length > 0 && (
            <ul className="mt-1 flex flex-col gap-0.5">
              {state.result.rejections.map((r, i) => (
                <li key={i} className="text-paper-500 fc-numeric">
                  row {r.source_row_id ?? "?"}: {r.reason}
                </li>
              ))}
            </ul>
          )}
          {state.result.breaks.length > 0 && (
            <ul className="mt-1 flex flex-col gap-0.5">
              {state.result.breaks.map((b, i) => (
                <li key={i} className="text-sig-amber fc-numeric">
                  row {b.row}: expected {formatPaise(b.expected_paise)}, found{" "}
                  {formatPaise(b.found_paise)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {state.error && (
        <div className="mt-2 text-xs">
          <p className="text-sig-red">{state.error.detail}</p>
          {state.error.breaks && state.error.breaks.length > 0 && (
            <ul className="mt-1 flex flex-col gap-0.5">
              {state.error.breaks.map((b, i) => (
                <li key={i} className="text-sig-red fc-numeric">
                  row {b.row}: expected {formatPaise(b.expected_paise)}, found{" "}
                  {formatPaise(b.found_paise)}
                </li>
              ))}
            </ul>
          )}
          {state.error.rowCount != null && (
            <p className="text-paper-500 mt-1">
              {state.error.rowCount} rows transcribed, nothing saved.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
