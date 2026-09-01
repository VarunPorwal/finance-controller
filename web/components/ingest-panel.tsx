"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Trash2 } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";

type IngestOut = components["schemas"]["IngestOut"];
type IngestedFileOut = components["schemas"]["IngestedFileOut"];
type Source = "razorpay" | "bank" | "ledger";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

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
export function IngestPanel({ onComplete }: { onComplete: () => void }) {
  const queryClient = useQueryClient();
  const [runId, setRunId] = useState<string | null>(null);
  const [openingBalanceRupees, setOpeningBalanceRupees] = useState("1000000");
  const [slots, setSlots] = useState<Record<Source, SlotState>>({
    razorpay: { ...EMPTY_SLOT },
    bank: { ...EMPTY_SLOT },
    ledger: { ...EMPTY_SLOT },
  });
  //: The server's "run with no rulebook at all" sentinel, distinct from
  //: "not specified" (which means every active rule).
  const NO_RULE_SET = "__none__";
  // Defaults to the last set used in this browser session, which is what a
  // second upload of the same dataset almost always wants.
  const [ruleSet, setRuleSet] = useState<string | null>(null);
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [finalizeError, setFinalizeError] = useState<string | null>(null);
  const [reingestingId, setReingestingId] = useState<string | null>(null);

  const { data: storedFiles } = useQuery({
    queryKey: ["ingest", "files"],
    queryFn: async () => (await apiClient.GET("/api/v1/ingest/files", { params: { query: {} } })).data ?? [],
  });

  async function reingestFile(source: Source, file: IngestedFileOut) {
    const id = await ensureRun();
    if (!id) {
      setSlots((prev) => ({
        ...prev,
        [source]: { ...prev[source], error: { detail: "Could not open a run to ingest into." } },
      }));
      return;
    }
    setReingestingId(file.file_id);
    setSlots((prev) => ({
      ...prev,
      [source]: { fileName: file.filename, loading: true, result: null, error: null },
    }));
    const query =
      source === "bank"
        ? { run_id: id, source_file_id: file.file_id, opening_balance_paise: Math.round(Number(openingBalanceRupees) * 100) }
        : { run_id: id, source_file_id: file.file_id };
    const { data, error } = await apiClient.POST(`/api/v1/ingest/${source}` as "/api/v1/ingest/razorpay", {
      params: { query },
    });
    setReingestingId(null);
    if (error || !data) {
      setSlots((prev) => ({
        ...prev,
        [source]: {
          fileName: file.filename,
          loading: false,
          result: null,
          error: { detail: "Could not reconcile from the stored file." },
        },
      }));
      return;
    }
    setSlots((prev) => ({
      ...prev,
      [source]: { fileName: file.filename, loading: false, result: data, error: null },
    }));
  }

  async function deleteStoredFile(fileId: string) {
    await apiClient.DELETE("/api/v1/ingest/files/{file_id}", { params: { path: { file_id: fileId } } });
    void queryClient.invalidateQueries({ queryKey: ["ingest", "files"] });
  }

  const { data: ruleSets } = useQuery({
    queryKey: ["rules", "sets"],
    queryFn: async () => (await apiClient.GET("/api/v1/rules/sets")).data ?? [],
  });

  async function runDemoCorpus() {
    setDemoRunning(true);
    setDemoError(null);
    // try/finally, not just an `error` check: a thrown network error (a
    // dropped connection, an unparseable body) must still clear the
    // loading flag — otherwise the button spins forever instead of
    // showing a message, which is worse than any error text.
    try {
      const { error, response } = await apiClient.POST("/api/v1/runs", {
        body: { mode: "demo", seed: 7 },
      });
      if (error) {
        const detail =
          error && typeof error === "object" && "detail" in error
            ? String((error as { detail?: unknown }).detail)
            : `request failed (${response.status})`;
        setDemoError(detail);
        return;
      }
      onComplete();
    } catch {
      setDemoError("Could not reach the API.");
    } finally {
      setDemoRunning(false);
    }
  }

  async function ensureRun(): Promise<string | null> {
    if (runId) return runId;
    try {
      const { data, error } = await apiClient.POST("/api/v1/runs", {
        body: { mode: "empty", seed: 7, rule_set: ruleSet },
      });
      if (error || !data) return null;
      setRunId(data.run_id);
      return data.run_id;
    } catch {
      return null;
    }
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

    try {
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
        void queryClient.invalidateQueries({ queryKey: ["ingest", "files"] });
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
    } catch {
      // A thrown network error must still clear `loading` — the same
      // reasoning as runDemoCorpus's try/finally.
      setSlots((prev) => ({
        ...prev,
        [source]: {
          fileName: file.name,
          loading: false,
          result: null,
          error: { detail: "Could not reach the API." },
        },
      }));
    }
  }

  async function finalize() {
    if (!runId) return;
    setFinalizing(true);
    setFinalizeError(null);
    try {
      const { error } = await apiClient.POST("/api/v1/runs/{run_id}/finalize", {
        params: { path: { run_id: runId } },
      });
      if (error) {
        setFinalizeError(
          "Could not reconcile — check that at least one source ingested cleanly.",
        );
        return;
      }
      onComplete();
    } catch {
      setFinalizeError("Could not reach the API.");
    } finally {
      setFinalizing(false);
    }
  }

  const anyIngested = Object.values(slots).some((s) => s.result && s.result.event_count > 0);

  return (
    <div className="fc-card flex flex-col gap-4 p-5">
      <div>
        <h2 className="text-base font-semibold text-text-heading">Start a run</h2>
        <p className="text-text-muted text-xs">
          Upload real files, or run the demo corpus in one click.
        </p>
      </div>

        <div className="border-border bg-background flex items-center justify-between gap-3 rounded-lg border p-3">
          <p className="text-text-body text-sm">Run the generated demo corpus, no upload needed.</p>
          <button
            type="button"
            disabled={demoRunning}
            onClick={runDemoCorpus}
            className="bg-primary hover:bg-primary/90 shrink-0 rounded-md px-3 py-1.5 text-xs font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {demoRunning ? "Running…" : "Run demo corpus"}
          </button>
        </div>
        {demoError && <p className="text-amber-text text-xs">{demoError}</p>}

        <div className="border-border border-t pt-4">
          <p className="text-text-body mb-3 text-xs font-medium uppercase tracking-wide">
            Or upload your own {runId && <span className="fc-numeric text-text-muted">· {runId}</span>}
          </p>

          {/*
            Which rulebook this data should be reconciled against. Uploaded
            data gets the choice; the demo corpus above does not, because it is
            pinned to its own set server-side — a judge pressing Run must get
            the rules that describe the demo data, never whichever set was
            uploaded most recently.
          */}
          <label className="mb-3 flex items-center gap-2 text-xs">
            <span className="text-text-body">Rule set</span>
            <select
              value={ruleSet ?? ""}
              onChange={(e) => setRuleSet(e.target.value || null)}
              className="border-border bg-background text-text-heading rounded-md border p-1"
            >
              <option value="">All active rules</option>
              {(ruleSets ?? []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name} · {s.active_rule_count} active
                </option>
              ))}
              <option value={NO_RULE_SET}>No rules</option>
            </select>
          </label>

          <label className="mb-3 flex items-center gap-2 text-xs">
            <span className="text-text-body">Bank opening balance ₹</span>
            <input
              value={openingBalanceRupees}
              onChange={(e) => setOpeningBalanceRupees(e.target.value)}
              className="fc-numeric border-border bg-background text-text-heading w-28 rounded-md border p-1"
            />
          </label>

          <div className="flex flex-col gap-3">
            {SOURCES.map((s) => (
              <SlotRow
                key={s.key}
                source={s}
                state={slots[s.key]}
                onFile={(f) => uploadSlot(s.key, f)}
                storedFiles={(storedFiles ?? []).filter((f) => f.source === s.key)}
                reingestingId={reingestingId}
                onReingest={(f) => reingestFile(s.key, f)}
                onDelete={deleteStoredFile}
              />
            ))}
          </div>
        </div>

        <div className="border-border border-t pt-3">
          <button
            type="button"
            disabled={!runId || !anyIngested || finalizing}
            onClick={finalize}
            className="bg-primary hover:bg-primary/90 w-full rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {finalizing ? "Reconciling…" : "Reconcile what's ingested"}
          </button>
          {finalizeError && <p className="text-amber-text mt-2 text-xs">{finalizeError}</p>}
        </div>
    </div>
  );
}

function SlotRow({
  source,
  state,
  onFile,
  storedFiles,
  reingestingId,
  onReingest,
  onDelete,
}: {
  source: { key: Source; label: string; accept: string };
  state: SlotState;
  onFile: (file: File) => void;
  storedFiles: IngestedFileOut[];
  reingestingId: string | null;
  onReingest: (file: IngestedFileOut) => void;
  onDelete: (fileId: string) => void;
}) {
  return (
    <div className="border-border bg-background rounded-lg border p-3">
      <div className="flex items-center justify-between gap-3">
        <label className="text-text-heading flex-1 text-sm font-medium">
          {source.label}
          <input
            type="file"
            accept={source.accept}
            className="text-text-body mt-1 block w-full text-xs"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onFile(file);
            }}
          />
        </label>
      </div>

      {storedFiles.length > 0 && (
        <div className="border-border mt-2.5 border-t pt-2.5">
          <p className="text-text-muted mb-1.5 text-[11px] font-medium uppercase tracking-wide">
            Or reuse a previous upload
          </p>
          <ul className="flex flex-col gap-1">
            {storedFiles.map((f) => (
              <li key={f.file_id} className="flex items-center justify-between gap-2 text-xs">
                <span className="text-text-body truncate">
                  {f.filename} <span className="text-text-muted">· {formatBytes(f.size_bytes)}</span>
                </span>
                <span className="flex flex-none items-center gap-1">
                  <button
                    type="button"
                    disabled={reingestingId === f.file_id}
                    onClick={() => onReingest(f)}
                    className="text-primary hover:bg-primary-tint flex items-center gap-1 rounded px-1.5 py-0.5 disabled:opacity-50"
                    title="Reconcile from this file"
                  >
                    <RotateCcw width={11} height={11} />
                    Use
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(f.file_id)}
                    className="text-text-muted hover:text-error rounded px-1 py-0.5"
                    title="Delete stored file"
                  >
                    <Trash2 width={11} height={11} />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {state.loading && (
        <p className="text-text-muted mt-2 text-xs">Ingesting {state.fileName}…</p>
      )}

      {state.result && (
        <div className="mt-2 text-xs">
          <p className="text-text-body">
            <span className="text-success font-semibold">{state.result.event_count}</span> rows
            parsed
            {state.result.rejections.length > 0 && (
              <>
                {" · "}
                <span className="text-amber-text font-semibold">
                  {state.result.rejections.length}
                </span>{" "}
                rejected
              </>
            )}
            {state.result.balanced !== null && state.result.balanced !== undefined && (
              <>
                {" · balance "}
                {state.result.balanced ? (
                  <span className="text-success">continuity holds ✓</span>
                ) : (
                  <span className="text-amber-text">broke, ingested anyway (CSV is trusted)</span>
                )}
              </>
            )}
          </p>
          {state.result.rejections.length > 0 && (
            <ul className="mt-1 flex flex-col gap-0.5">
              {state.result.rejections.map((r, i) => (
                <li key={i} className="text-text-muted fc-numeric">
                  row {r.source_row_id ?? "?"}: {r.reason}
                </li>
              ))}
            </ul>
          )}
          {state.result.breaks.length > 0 && (
            <ul className="mt-1 flex flex-col gap-0.5">
              {state.result.breaks.map((b, i) => (
                <li key={i} className="text-amber-text fc-numeric">
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
          <p className="text-error">{state.error.detail}</p>
          {state.error.breaks && state.error.breaks.length > 0 && (
            <ul className="mt-1 flex flex-col gap-0.5">
              {state.error.breaks.map((b, i) => (
                <li key={i} className="text-error fc-numeric">
                  row {b.row}: expected {formatPaise(b.expected_paise)}, found{" "}
                  {formatPaise(b.found_paise)}
                </li>
              ))}
            </ul>
          )}
          {state.error.rowCount != null && (
            <p className="text-text-muted mt-1">
              {state.error.rowCount} rows transcribed, nothing saved.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
