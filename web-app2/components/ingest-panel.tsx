"use client";

import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, FileUp, Play, RotateCcw, Trash2 } from "lucide-react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { SourceGlyph } from "@/components/ui/source-glyph";
import { cn } from "@/lib/utils";

type IngestOut = components["schemas"]["IngestOut"];
type IngestedFileOut = components["schemas"]["IngestedFileOut"];
type Source = "razorpay" | "bank" | "ledger";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

const SOURCES: { key: Source; label: string; hint: string; accept: string }[] = [
  { key: "razorpay", label: "Razorpay recon", hint: "JSON", accept: ".json" },
  { key: "bank", label: "Bank statement", hint: "CSV or PDF, format auto-detected", accept: ".csv,.pdf" },
  { key: "ledger", label: "Tally export", hint: "CSV or XML", accept: ".csv,.xml" },
];

interface SlotState {
  fileName: string | null;
  loading: boolean;
  result: IngestOut | null;
  error: { detail: string; breaks?: { row: number; expected_paise: number; found_paise: number }[]; rowCount?: number } | null;
}

const EMPTY_SLOT: SlotState = { fileName: null, loading: false, result: null, error: null };

/**
 * Three source slots, format auto-detected within the bank slot, and the
 * one-click demo corpus beside them. `POST /runs` with `mode=empty` opens a
 * run; each slot ingests into it; `finalize` runs the cascade over whatever
 * actually got uploaded.
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
  const NO_RULE_SET = "__none__";
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
  const { data: ruleSets } = useQuery({
    queryKey: ["rules", "sets"],
    queryFn: async () => (await apiClient.GET("/api/v1/rules/sets")).data ?? [],
  });

  async function ensureRun(): Promise<string | null> {
    if (runId) return runId;
    try {
      const { data, error } = await apiClient.POST("/api/v1/runs", { body: { mode: "empty", seed: 7, rule_set: ruleSet } });
      if (error || !data) return null;
      setRunId(data.run_id);
      return data.run_id;
    } catch {
      return null;
    }
  }

  function setSlot(source: Source, patch: Partial<SlotState>) {
    setSlots((prev) => ({ ...prev, [source]: { ...prev[source], ...patch } }));
  }

  async function reingestFile(source: Source, file: IngestedFileOut) {
    const id = await ensureRun();
    if (!id) {
      setSlot(source, { error: { detail: "Could not open a run to ingest into." } });
      return;
    }
    setReingestingId(file.file_id);
    setSlot(source, { fileName: file.filename, loading: true, result: null, error: null });
    const query =
      source === "bank"
        ? { run_id: id, source_file_id: file.file_id, opening_balance_paise: Math.round(Number(openingBalanceRupees) * 100) }
        : { run_id: id, source_file_id: file.file_id };
    const { data, error } = await apiClient.POST(`/api/v1/ingest/${source}` as "/api/v1/ingest/razorpay", { params: { query } });
    setReingestingId(null);
    if (error || !data) {
      setSlot(source, { fileName: file.filename, loading: false, result: null, error: { detail: "Could not reconcile from the stored file." } });
      return;
    }
    setSlot(source, { fileName: file.filename, loading: false, result: data, error: null });
  }

  async function deleteStoredFile(fileId: string) {
    await apiClient.DELETE("/api/v1/ingest/files/{file_id}", { params: { path: { file_id: fileId } } });
    void queryClient.invalidateQueries({ queryKey: ["ingest", "files"] });
  }

  async function runDemoCorpus() {
    setDemoRunning(true);
    setDemoError(null);
    try {
      const { error, response } = await apiClient.POST("/api/v1/runs", { body: { mode: "demo", seed: 7 } });
      if (error) {
        const detail =
          error && typeof error === "object" && "detail" in error ? String((error as { detail?: unknown }).detail) : `request failed (${response.status})`;
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

  async function uploadSlot(source: Source, file: File) {
    const id = await ensureRun();
    if (!id) {
      setSlot(source, { error: { detail: "Could not open a run to ingest into." } });
      return;
    }
    setSlot(source, { fileName: file.name, loading: true, result: null, error: null });

    const body = new FormData();
    body.append("file", file);
    const query =
      source === "bank"
        ? `run_id=${encodeURIComponent(id)}&opening_balance_paise=${Math.round(Number(openingBalanceRupees) * 100)}`
        : `run_id=${encodeURIComponent(id)}`;
    const path = `/api/v1/ingest/${source}?${query}`;
    // A multipart upload needs a raw fetch: the generated client has no
    // multipart form-data path to call instead. The one deliberate exception.
    const token = process.env.NEXT_PUBLIC_DEMO_TOKEN ?? "";
    const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

    try {
      const res = await fetch(`${base}${path}`, { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : undefined, body });
      if (res.ok) {
        const data = (await res.json()) as IngestOut;
        setSlot(source, { fileName: file.name, loading: false, result: data, error: null });
        void queryClient.invalidateQueries({ queryKey: ["ingest", "files"] });
      } else {
        const problem = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        setSlot(source, {
          fileName: file.name,
          loading: false,
          result: null,
          error: { detail: problem.detail ?? `HTTP ${res.status}`, breaks: problem.breaks, rowCount: problem.row_count },
        });
      }
    } catch {
      setSlot(source, { fileName: file.name, loading: false, result: null, error: { detail: "Could not reach the API." } });
    }
  }

  async function finalize() {
    if (!runId) return;
    setFinalizing(true);
    setFinalizeError(null);
    try {
      const { error } = await apiClient.POST("/api/v1/runs/{run_id}/finalize", { params: { path: { run_id: runId } } });
      if (error) {
        setFinalizeError("Could not reconcile. Check that at least one source ingested cleanly.");
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
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1fr_1.9fr]">
      <div className="flex flex-col gap-4">
        <div className="panel px-[18px] pt-4 pb-[18px]">
          <div className="label">Demo corpus</div>
          <p className="mt-2 text-[12.5px] text-ink-2">
            A seeded, adversarial corpus with ground truth: truncated UTRs, split settlements, a mid-period rate change, a duplicate
            voucher. One click, no upload.
          </p>
          <Button variant="primary" className="mt-3.5 w-full" icon={<Play width={14} height={14} />} disabled={demoRunning} onClick={runDemoCorpus}>
            {demoRunning ? "Running the cascade…" : "Run the demo corpus"}
          </Button>
          {demoError && <p className="mt-2 text-[11.5px] text-warn">{demoError}</p>}
        </div>

        <div className="panel px-[18px] pt-4 pb-[18px]">
          <div className="label">Upload settings</div>
          <label className="mt-3 block">
            <span className="text-[11.5px] text-ink-2">Rule set</span>
            <select value={ruleSet ?? ""} onChange={(e) => setRuleSet(e.target.value || null)} className="input mt-1.5">
              <option value="">All active rules</option>
              {(ruleSets ?? []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name} · {s.active_rule_count} active
                </option>
              ))}
              <option value={NO_RULE_SET}>No rules</option>
            </select>
          </label>
          <p className="mt-1.5 text-[11px] text-ink-3">The demo corpus is pinned to its own set server-side; this applies to uploads only.</p>
          <label className="mt-3 block">
            <span className="text-[11.5px] text-ink-2">Bank opening balance, ₹</span>
            <input value={openingBalanceRupees} onChange={(e) => setOpeningBalanceRupees(e.target.value)} className="input num mt-1.5" />
          </label>
          {runId && (
            <p className="num mt-3 border-t border-line pt-2.5 text-[10.5px] text-ink-3">
              open run {runId}
            </p>
          )}
        </div>
      </div>

      <div className="panel flex flex-col px-[18px] pt-4 pb-[18px]">
        <div className="flex items-center justify-between">
          <div>
            <div className="label">Upload your own</div>
            <p className="mt-1 text-[11.5px] text-ink-3">Drop a file on a slot. Any slot can be left empty; the cascade runs over what is there.</p>
          </div>
        </div>
        <div className="mt-3.5 flex flex-col gap-3">
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
        <div className="mt-4 flex items-center gap-3 border-t border-line pt-4">
          <Button variant="primary" size="lg" disabled={!runId || !anyIngested || finalizing} onClick={finalize}>
            {finalizing ? "Reconciling…" : "Reconcile what is ingested"}
          </Button>
          <span className="text-[11.5px] text-ink-3">
            {anyIngested ? "Runs the five-stage cascade, then the rule book, then tiering." : "Ingest at least one source to enable."}
          </span>
        </div>
        {finalizeError && <p className="mt-2 text-[11.5px] text-warn">{finalizeError}</p>}
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
  source: { key: Source; label: string; hint: string; accept: string };
  state: SlotState;
  onFile: (file: File) => void;
  storedFiles: IngestedFileOut[];
  reingestingId: string | null;
  onReingest: (file: IngestedFileOut) => void;
  onDelete: (fileId: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const done = !!state.result;

  return (
    <div
      className={cn(
        "rounded-[10px] border transition-colors",
        over ? "border-accent-strong bg-accent-soft" : done ? "border-[rgba(61,220,151,0.3)] bg-bg" : "border-line-strong bg-bg",
      )}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const file = e.dataTransfer.files?.[0];
        if (file) onFile(file);
      }}
    >
      <div className="flex items-center gap-3 px-3.5 py-3">
        <SourceGlyph source={source.key} size={30} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium text-ink">{source.label}</div>
          <div className="text-[11px] text-ink-3">
            {state.loading ? `Ingesting ${state.fileName}…` : state.fileName ? state.fileName : source.hint}
          </div>
        </div>
        {done && (
          <span className="flex items-center gap-1 text-[11px] font-semibold text-ok">
            <Check width={12} height={12} />
            {state.result!.event_count} rows
          </span>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={source.accept}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (file) onFile(file);
          }}
        />
        <Button size="sm" icon={<FileUp width={12} height={12} />} disabled={state.loading} onClick={() => inputRef.current?.click()}>
          Browse
        </Button>
      </div>

      {storedFiles.length > 0 && (
        <div className="border-t border-line px-3.5 py-2">
          <div className="mb-1 text-[10.5px] text-ink-3">Or reuse a previous upload</div>
          <ul className="flex flex-col gap-0.5">
            {storedFiles.map((f) => (
              <li key={f.file_id} className="flex items-center justify-between gap-2 text-[11.5px]">
                <span className="num truncate text-ink-2">
                  {f.filename} <span className="text-ink-3">· {formatBytes(f.size_bytes)}</span>
                </span>
                <span className="flex flex-none items-center gap-1">
                  <button
                    type="button"
                    disabled={reingestingId === f.file_id}
                    onClick={() => onReingest(f)}
                    className="flex items-center gap-1 rounded px-1.5 py-0.5 text-accent hover:bg-accent-soft disabled:opacity-50"
                  >
                    <RotateCcw width={11} height={11} />
                    Use
                  </button>
                  <button type="button" onClick={() => onDelete(f.file_id)} className="rounded px-1 py-0.5 text-ink-3 hover:text-bad" title="Delete stored file">
                    <Trash2 width={11} height={11} />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {state.result && (state.result.rejections.length > 0 || state.result.breaks.length > 0 || state.result.balanced != null) && (
        <div className="border-t border-line px-3.5 py-2 text-[11.5px]">
          <p className="text-ink-2">
            {state.result.rejections.length > 0 && (
              <>
                <span className="font-semibold text-warn">{state.result.rejections.length}</span> rejected ·{" "}
              </>
            )}
            {state.result.balanced != null && (
              <>
                balance{" "}
                {state.result.balanced ? (
                  <span className="text-ok">continuity holds</span>
                ) : (
                  <span className="text-warn">broke, ingested anyway (CSV is trusted)</span>
                )}
              </>
            )}
          </p>
          {state.result.rejections.length > 0 && (
            <ul className="num mt-1 flex flex-col gap-0.5 text-ink-3">
              {state.result.rejections.map((r, i) => (
                <li key={i}>
                  row {r.source_row_id ?? "?"}: {r.reason}
                </li>
              ))}
            </ul>
          )}
          {state.result.breaks.length > 0 && (
            <ul className="num mt-1 flex flex-col gap-0.5 text-warn">
              {state.result.breaks.map((b, i) => (
                <li key={i}>
                  row {b.row}: expected {formatPaise(b.expected_paise)}, found {formatPaise(b.found_paise)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {state.error && (
        <div className="border-t border-line px-3.5 py-2 text-[11.5px]">
          <p className="text-bad">{state.error.detail}</p>
          {state.error.breaks && state.error.breaks.length > 0 && (
            <ul className="num mt-1 flex flex-col gap-0.5 text-bad">
              {state.error.breaks.map((b, i) => (
                <li key={i}>
                  row {b.row}: expected {formatPaise(b.expected_paise)}, found {formatPaise(b.found_paise)}
                </li>
              ))}
            </ul>
          )}
          {state.error.rowCount != null && <p className="mt-1 text-ink-3">{state.error.rowCount} rows transcribed, nothing saved.</p>}
        </div>
      )}
    </div>
  );
}
