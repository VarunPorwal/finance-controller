"use client";

import { useEffect, useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";

type DeductionInput = components["schemas"]["Deduction-Input"];
type PreviewOut = components["schemas"]["api__routers__rules__PreviewOut"];
type Source = components["schemas"]["Scope"]["source"];
type Method = components["schemas"]["Scope"]["method"];
type Rail = components["schemas"]["Scope"]["rail"];

const DEDUCTION_TYPES: DeductionInput["type"][] = ["commission", "mdr", "gst_on_fee", "tds_194o", "reserve", "platform_fee", "custom"];
const DEDUCTION_BASES: DeductionInput["basis"][] = ["gross", "net", "commission", "mdr", "gst_on_fee", "tds_194o", "reserve", "platform_fee", "custom"];

interface DeductionDraft {
  type: DeductionInput["type"];
  basis: DeductionInput["basis"];
  rate: string;
  fixed_paise: string;
}

const EMPTY_DEDUCTION: DeductionDraft = { type: "commission", basis: "gross", rate: "2", fixed_paise: "" };

export interface RuleSubmitPayload {
  rule_id: string;
  name: string;
  description: string | null;
  scope: components["schemas"]["Scope"];
  deductions: DeductionInput[];
  tolerance: components["schemas"]["Tolerance-Input"];
  priority: number;
  effective_confidence: string;
}

/**
 * Counterparty, deduction lines, tolerance, and a live preview computed by
 * the server on a sample transaction. No client-side arithmetic.
 */
export function RuleAuthoringForm({ onSubmit, submitting }: { onSubmit: (payload: RuleSubmitPayload) => void; submitting: boolean }) {
  const [name, setName] = useState("");
  const [counterparty, setCounterparty] = useState("");
  const [dateFrom, setDateFrom] = useState(() => new Date().toISOString().slice(0, 10));
  const [source, setSource] = useState<Source>(null);
  const [method, setMethod] = useState<Method>(null);
  const [rail, setRail] = useState<Rail>(null);
  const [deductions, setDeductions] = useState<DeductionDraft[]>([{ ...EMPTY_DEDUCTION }]);
  const [toleranceAbsPaise, setToleranceAbsPaise] = useState("100");
  const [tolerancePercent, setTolerancePercent] = useState("0.05");
  const [priority, setPriority] = useState("100");
  const [sampleGrossRupees, setSampleGrossRupees] = useState("50000");
  const [preview, setPreview] = useState<PreviewOut | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    const grossPaise = Math.round(Number(sampleGrossRupees) * 100);
    if (!Number.isFinite(grossPaise) || grossPaise <= 0 || deductions.length === 0) {
      setPreview(null);
      return;
    }
    const handle = setTimeout(() => {
      void (async () => {
        const { data, error } = await apiClient.POST("/api/v1/rules/preview", {
          body: {
            gross_paise: grossPaise,
            deductions: deductions.map((d) => ({ type: d.type, basis: d.basis, rate: d.rate, fixed_paise: d.fixed_paise ? Number(d.fixed_paise) : null })),
          },
        });
        if (error || !data) {
          setPreviewError("Preview failed. Check the deduction rates.");
          setPreview(null);
          return;
        }
        setPreviewError(null);
        setPreview(data);
      })();
    }, 300);
    return () => clearTimeout(handle);
  }, [deductions, sampleGrossRupees]);

  function updateDeduction(index: number, patch: Partial<DeductionDraft>) {
    setDeductions((prev) => prev.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  }

  function submit() {
    const ruleId = `rule_${name.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 40)}_${Date.now().toString(36)}`;
    onSubmit({
      rule_id: ruleId,
      name: name.trim(),
      description: null,
      scope: {
        counterparty_matches: counterparty.trim() ? [counterparty.trim()] : null,
        narration_contains: null,
        source,
        method,
        rail,
        amount_min_paise: null,
        amount_max_paise: null,
        date_from: dateFrom,
        date_to: null,
      },
      deductions: deductions.map((d) => ({ type: d.type, basis: d.basis, rate: d.rate, fixed_paise: d.fixed_paise ? Number(d.fixed_paise) : null })),
      tolerance: { absolute_paise: Number(toleranceAbsPaise), percent: tolerancePercent },
      priority: Number(priority),
      effective_confidence: "0.9500",
    });
  }

  const canSubmit = name.trim().length > 0 && deductions.length > 0 && dateFrom;

  return (
    <Panel title="New rule" sub="Born a draft. A back-test runs before it can activate.">
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.4fr_1fr]">
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="Rule name" className="col-span-2">
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Blinkit commission v3" className="input" />
            </Field>
            <Field label="Counterparty matches">
              <input value={counterparty} onChange={(e) => setCounterparty(e.target.value)} placeholder="BLINKIT" className="input num" />
            </Field>
            <Field label="Effective from">
              <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="input num" />
            </Field>
            <Field label="Source">
              <Select value={source} onChange={(v) => setSource(v as Source)} options={["razorpay", "bank", "ledger"]} />
            </Field>
            <Field label="Method">
              <Select value={method} onChange={(v) => setMethod(v as Method)} options={["card", "upi", "netbanking", "wallet", "emi"]} />
            </Field>
            <Field label="Rail">
              <Select value={rail} onChange={(v) => setRail(v as Rail)} options={["neft", "rtgs", "imps", "upi", "nach", "internal"]} />
            </Field>
            <Field label="Priority, higher wins">
              <input type="number" value={priority} onChange={(e) => setPriority(e.target.value)} className="input num" />
            </Field>
          </div>

          <div>
            <div className="label mb-2">Deduction stack</div>
            <div className="flex flex-col gap-2">
              {deductions.map((d, i) => (
                <div key={i} className="grid grid-cols-[1fr_auto_1fr_90px_130px_auto] items-center gap-2">
                  <select value={d.type} onChange={(e) => updateDeduction(i, { type: e.target.value as DeductionInput["type"] })} className="input">
                    {DEDUCTION_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                  <span className="text-[11.5px] text-ink-3">on</span>
                  <select value={d.basis} onChange={(e) => updateDeduction(i, { basis: e.target.value as DeductionInput["basis"] })} className="input">
                    {DEDUCTION_BASES.map((b) => (
                      <option key={b} value={b}>
                        {b}
                      </option>
                    ))}
                  </select>
                  <input value={d.rate} onChange={(e) => updateDeduction(i, { rate: e.target.value })} placeholder="rate %" className="input num" />
                  <input value={d.fixed_paise} onChange={(e) => updateDeduction(i, { fixed_paise: e.target.value })} placeholder="flat paise" className="input num" />
                  <button type="button" onClick={() => setDeductions((prev) => prev.filter((_, idx) => idx !== i))} className="text-[11.5px] text-ink-3 hover:text-bad">
                    Remove
                  </button>
                </div>
              ))}
              <button type="button" onClick={() => setDeductions((prev) => [...prev, { ...EMPTY_DEDUCTION }])} className="w-fit text-[12px] text-accent hover:underline">
                + Add deduction line
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Tolerance, absolute paise">
              <input value={toleranceAbsPaise} onChange={(e) => setToleranceAbsPaise(e.target.value)} className="input num" />
            </Field>
            <Field label="Tolerance, percent">
              <input value={tolerancePercent} onChange={(e) => setTolerancePercent(e.target.value)} className="input num" />
            </Field>
          </div>
        </div>

        <div className="rounded-[10px] border border-line bg-bg p-4">
          <div className="flex items-center justify-between gap-2">
            <div className="label">Live preview</div>
            <label className="flex items-center gap-2 text-[11.5px] text-ink-3">
              gross ₹
              <input value={sampleGrossRupees} onChange={(e) => setSampleGrossRupees(e.target.value)} className="input num h-[26px] w-24" />
            </label>
          </div>
          <p className="mt-1 text-[11px] text-ink-3">Computed by the server on a sample transaction. This is the exact stack a real settlement would produce.</p>
          {previewError && <p className="mt-3 text-[11.5px] text-warn">{previewError}</p>}
          {preview && (
            <div className="mt-3 flex flex-col">
              {preview.stack.map((line, i) => (
                <div key={i} className="flex items-center justify-between border-b border-line py-1.5 text-[12px]">
                  <span className="text-ink-2">
                    {line.type} <span className="text-ink-4">on {line.basis} · {line.rate}%</span>
                  </span>
                  <span className="num text-ink">{formatPaise(line.amount_paise)}</span>
                </div>
              ))}
              <div className="flex items-center justify-between pt-2.5 text-[12.5px] font-semibold">
                <span>Net</span>
                <span className="num text-[15px] text-ok">{formatPaise(preview.net_paise)}</span>
              </div>
            </div>
          )}
          <Button variant="primary" className="mt-4 w-full" disabled={!canSubmit || submitting} onClick={submit}>
            {submitting ? "Creating…" : "Create draft rule"}
          </Button>
        </div>
      </div>
    </Panel>
  );
}

function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={"flex flex-col gap-1.5 " + (className ?? "")}>
      <span className="text-[11.5px] text-ink-2">{label}</span>
      {children}
    </label>
  );
}

function Select({ value, onChange, options }: { value: string | null | undefined; onChange: (v: string | null) => void; options: string[] }) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} className="input">
      <option value="">any</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}
