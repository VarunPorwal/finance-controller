"use client";

import { useEffect, useState } from "react";
import { apiClient, type components } from "@/lib/client";
import { formatPaise } from "@/lib/format";

type DeductionInput = components["schemas"]["Deduction-Input"];
type PreviewOut = components["schemas"]["api__routers__rules__PreviewOut"];
type Source = components["schemas"]["Scope"]["source"];
type Method = components["schemas"]["Scope"]["method"];
type Rail = components["schemas"]["Scope"]["rail"];

const DEDUCTION_TYPES: DeductionInput["type"][] = [
  "commission",
  "mdr",
  "gst_on_fee",
  "tds_194o",
  "reserve",
  "platform_fee",
  "custom",
];
const DEDUCTION_BASES: DeductionInput["basis"][] = [
  "gross",
  "net",
  "commission",
  "mdr",
  "gst_on_fee",
  "tds_194o",
  "reserve",
  "platform_fee",
  "custom",
];

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
 * PRD §13.6's authoring form: counterparty -> deduction lines -> tolerance
 * -> live preview computing on a sample transaction. Every keystroke on the
 * deduction stack re-runs `POST /rules/preview` (debounced) so the human
 * sees the exact stack a real settlement would produce before the rule
 * exists — no client-side arithmetic, the server computes the stack.
 */
export function RuleAuthoringForm({
  onSubmit,
  submitting,
}: {
  onSubmit: (payload: RuleSubmitPayload) => void;
  submitting: boolean;
}) {
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
            deductions: deductions.map((d) => ({
              type: d.type,
              basis: d.basis,
              rate: d.rate,
              fixed_paise: d.fixed_paise ? Number(d.fixed_paise) : null,
            })),
          },
        });
        if (error || !data) {
          setPreviewError("preview failed — check the deduction rates");
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
      deductions: deductions.map((d) => ({
        type: d.type,
        basis: d.basis,
        rate: d.rate,
        fixed_paise: d.fixed_paise ? Number(d.fixed_paise) : null,
      })),
      tolerance: { absolute_paise: Number(toleranceAbsPaise), percent: tolerancePercent },
      priority: Number(priority),
      effective_confidence: "0.9500",
    });
  }

  const canSubmit = name.trim().length > 0 && deductions.length > 0 && dateFrom;

  return (
    <div className="border-border bg-card flex flex-col gap-4 rounded-lg border p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Rule name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Blinkit commission v3"
            className="border-border bg-background text-text-heading w-full rounded-md border p-2 text-sm"
          />
        </Field>
        <Field label="Counterparty matches">
          <input
            value={counterparty}
            onChange={(e) => setCounterparty(e.target.value)}
            placeholder="BLINKIT"
            className="border-border bg-background text-text-heading w-full rounded-md border p-2 text-sm"
          />
        </Field>
        <Field label="Effective from">
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="fc-numeric border-border bg-background text-text-heading w-full rounded-md border p-2 text-sm"
          />
        </Field>
        <Field label="Priority (higher wins)">
          <input
            type="number"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className="fc-numeric border-border bg-background text-text-heading w-full rounded-md border p-2 text-sm"
          />
        </Field>
        <Field label="Source">
          <Select
            value={source}
            onChange={(v) => setSource(v as Source)}
            options={["razorpay", "bank", "ledger"]}
          />
        </Field>
        <Field label="Method">
          <Select
            value={method}
            onChange={(v) => setMethod(v as Method)}
            options={["card", "upi", "netbanking", "wallet", "emi"]}
          />
        </Field>
        <Field label="Rail">
          <Select
            value={rail}
            onChange={(v) => setRail(v as Rail)}
            options={["neft", "rtgs", "imps", "upi", "nach", "internal"]}
          />
        </Field>
      </div>

      <div>
        <div className="text-text-body mb-2 text-xs font-medium">Deduction stack</div>
        <div className="flex flex-col gap-2">
          {deductions.map((d, i) => (
            <div key={i} className="flex flex-wrap items-center gap-2">
              <select
                value={d.type}
                onChange={(e) => updateDeduction(i, { type: e.target.value as DeductionInput["type"] })}
                className="border-border bg-background text-text-heading rounded-md border p-1.5 text-xs"
              >
                {DEDUCTION_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
              <span className="text-text-muted text-xs">on</span>
              <select
                value={d.basis}
                onChange={(e) => updateDeduction(i, { basis: e.target.value as DeductionInput["basis"] })}
                className="border-border bg-background text-text-heading rounded-md border p-1.5 text-xs"
              >
                {DEDUCTION_BASES.map((b) => (
                  <option key={b} value={b}>
                    {b}
                  </option>
                ))}
              </select>
              <input
                value={d.rate}
                onChange={(e) => updateDeduction(i, { rate: e.target.value })}
                placeholder="rate %"
                className="fc-numeric border-border bg-background text-text-heading w-20 rounded-md border p-1.5 text-xs"
              />
              <span className="text-text-muted text-xs">%</span>
              <input
                value={d.fixed_paise}
                onChange={(e) => updateDeduction(i, { fixed_paise: e.target.value })}
                placeholder="flat paise (optional)"
                className="fc-numeric border-border bg-background text-text-heading w-32 rounded-md border p-1.5 text-xs"
              />
              <button
                type="button"
                onClick={() => setDeductions((prev) => prev.filter((_, idx) => idx !== i))}
                className="text-error text-xs hover:underline"
              >
                Remove
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setDeductions((prev) => [...prev, { ...EMPTY_DEDUCTION }])}
            className="text-primary w-fit text-xs font-medium hover:underline"
          >
            + Add deduction line
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Tolerance, absolute paise">
          <input
            value={toleranceAbsPaise}
            onChange={(e) => setToleranceAbsPaise(e.target.value)}
            className="fc-numeric border-border bg-background text-text-heading w-full rounded-md border p-2 text-sm"
          />
        </Field>
        <Field label="Tolerance, percent">
          <input
            value={tolerancePercent}
            onChange={(e) => setTolerancePercent(e.target.value)}
            className="fc-numeric border-border bg-background text-text-heading w-full rounded-md border p-2 text-sm"
          />
        </Field>
      </div>

      <div className="border-border bg-background rounded-lg border p-3">
        <div className="mb-2 flex items-center gap-2">
          <label htmlFor="sample-gross" className="text-text-body text-xs font-medium">
            Live preview on a sample transaction, gross ₹
          </label>
          <input
            id="sample-gross"
            value={sampleGrossRupees}
            onChange={(e) => setSampleGrossRupees(e.target.value)}
            className="fc-numeric border-border bg-card text-text-heading w-28 rounded-md border p-1 text-xs"
          />
        </div>
        {previewError && <p className="text-amber-text text-xs">{previewError}</p>}
        {preview && (
          <div className="flex flex-col gap-1">
            {preview.stack.map((line, i) => (
              <div key={i} className="fc-numeric flex items-center justify-between text-xs">
                <span className="text-text-body">
                  {line.type} on {line.basis} ({line.rate}%)
                </span>
                <span className="text-text-heading">{formatPaise(line.amount_paise)}</span>
              </div>
            ))}
            <div className="border-border fc-numeric mt-1 flex items-center justify-between border-t pt-1 text-xs font-semibold">
              <span className="text-text-heading">Net</span>
              <span className="text-text-heading">{formatPaise(preview.net_paise)}</span>
            </div>
          </div>
        )}
      </div>

      <button
        type="button"
        disabled={!canSubmit || submitting}
        onClick={submit}
        className="bg-primary hover:bg-primary/90 w-fit rounded-md px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "Creating…" : "Create draft rule"}
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-text-body text-xs font-medium">{label}</span>
      {children}
    </label>
  );
}

function Select({
  value,
  onChange,
  options,
}: {
  value: string | null | undefined;
  onChange: (v: string | null) => void;
  options: string[];
}) {
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
      className="border-border bg-background text-text-heading w-full rounded-md border p-2 text-sm"
    >
      <option value="">any</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}
