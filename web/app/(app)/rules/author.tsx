"use client";

// New rule. A compact form on the left, a live preview of the stack on the
// right. The preview is the server's arithmetic (/rules/preview); this file
// only assembles the request.

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Plus, Trash2, Save } from "lucide-react";
import { clsx } from "clsx";
import { writes, useWrite, errorMessage, type Rule, type S } from "../_lib/api";
import { FcErrorNote, FcMoney } from "../_components/fc-ui";
import {
  basisLabel,
  DEDUCTION_BASES,
  DEDUCTION_TYPES,
  deductionLabel,
  FcPanel,
  rateText,
  SAMPLE_GROSS_PAISE,
  type DeductionBasis,
  type DeductionIn,
  type DeductionType,
} from "./shared";

type Create = S["RuleCreateRequest"];
type PreviewOut = S["api__routers__rules__PreviewOut"];
type Source = NonNullable<S["Scope"]["source"]>;
type Rail = NonNullable<S["Scope"]["rail"]>;
type Method = NonNullable<S["Scope"]["method"]>;

const SOURCES: Source[] = ["razorpay", "bank", "ledger"];
const RAILS: Rail[] = ["neft", "rtgs", "imps", "upi", "nach", "internal"];
const METHODS: Method[] = ["card", "upi", "netbanking", "wallet", "emi"];

interface DedRow {
  type: DeductionType;
  basis: DeductionBasis;
  rate: string;
  fixed: string;
}

const DEFAULT_ROWS: DedRow[] = [
  { type: "mdr", basis: "gross", rate: "2", fixed: "" },
  { type: "gst_on_fee", basis: "mdr", rate: "18", fixed: "" },
];

const inputStyle: CSSProperties = {
  width: "100%",
  borderRadius: 8,
  border: "1px solid var(--fc-border)",
  background: "var(--fc-hover)",
  color: "var(--fc-text)",
  padding: "8px 10px",
  fontSize: 12.5,
  outline: "none",
};

function slug(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 48);
}

function list(s: string): string[] | null {
  const v = s
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
  return v.length ? v : null;
}

function toDeductions(rows: DedRow[]): DeductionIn[] | null {
  const out: DeductionIn[] = [];
  for (const r of rows) {
    const rate = r.rate.trim();
    if (!rate || Number.isNaN(Number(rate))) return null;
    const d: DeductionIn = { type: r.type, basis: r.basis, rate };
    if (r.fixed.trim()) {
      const f = Number(r.fixed);
      if (!Number.isInteger(f)) return null;
      d.fixed_paise = f;
    }
    out.push(d);
  }
  return out.length ? out : null;
}

export function AuthorRule({
  open,
  onClose,
  onCreated,
  ruleSets,
  defaultDateFrom,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (rule: Rule) => void;
  ruleSets: string[];
  defaultDateFrom?: string | null;
}) {
  return (
    <FcPanel open={open} onClose={onClose} width={900} title="New rule" sub="Saved as a draft. Back-test, then activate.">
      {open && <Form onCreated={onCreated} ruleSets={ruleSets} defaultDateFrom={defaultDateFrom ?? ""} />}
    </FcPanel>
  );
}

function Form({
  onCreated,
  ruleSets,
  defaultDateFrom,
}: {
  onCreated: (rule: Rule) => void;
  ruleSets: string[];
  defaultDateFrom: string;
}) {
  const [name, setName] = useState("");
  const [ruleId, setRuleId] = useState("");
  const [idTouched, setIdTouched] = useState(false);
  const [description, setDescription] = useState("");
  const [ruleSet, setRuleSet] = useState(ruleSets[0] ?? "");
  const [counterparty, setCounterparty] = useState("");
  const [narration, setNarration] = useState("");
  const [source, setSource] = useState<Source | "">("");
  const [rail, setRail] = useState<Rail | "">("");
  const [method, setMethod] = useState<Method | "">("");
  const [dateFrom, setDateFrom] = useState(defaultDateFrom);
  const [dateTo, setDateTo] = useState("");
  const [rows, setRows] = useState<DedRow[]>(DEFAULT_ROWS);
  const [tolAbs, setTolAbs] = useState("100");
  const [tolPct, setTolPct] = useState("0.05");
  const [priority, setPriority] = useState("100");
  const [confidence, setConfidence] = useState("0.9500");

  const [preview, setPreview] = useState<{ loading: boolean; data: PreviewOut | null; error: string | null }>({
    loading: false,
    data: null,
    error: null,
  });
  const seq = useRef(0);
  const rowsKey = JSON.stringify(rows);

  useEffect(() => {
    const deductions = toDeductions(JSON.parse(rowsKey) as DedRow[]);
    const id = ++seq.current;
    if (!deductions) {
      setPreview((p) => ({ ...p, loading: false, error: null }));
      return;
    }
    setPreview((p) => ({ ...p, loading: true }));
    const t = setTimeout(async () => {
      const res = await writes.previewRule({ deductions, gross_paise: SAMPLE_GROSS_PAISE });
      if (id !== seq.current) return;
      if (res.error || !res.data) setPreview({ loading: false, data: null, error: errorMessage(res.error) });
      else setPreview({ loading: false, data: res.data, error: null });
    }, 400);
    return () => clearTimeout(t);
  }, [rowsKey]);

  const create = useWrite((b: Create) => writes.createRule(b));

  const body = ((): Create | null => {
    const deductions = toDeductions(rows);
    if (!deductions) return null;
    const id = slug(ruleId);
    if (!id || !name.trim() || !dateFrom) return null;
    const abs = Number(tolAbs);
    if (!Number.isInteger(abs) || abs < 0) return null;
    if (!tolPct.trim() || Number.isNaN(Number(tolPct))) return null;
    const pr = Number(priority);
    if (!Number.isInteger(pr)) return null;
    if (!confidence.trim() || Number.isNaN(Number(confidence))) return null;
    return {
      rule_id: id,
      name: name.trim(),
      description: description.trim() || null,
      scope: {
        rule_set: ruleSet.trim() || null,
        counterparty_matches: list(counterparty),
        narration_contains: list(narration),
        source: source || null,
        rail: rail || null,
        method: method || null,
        date_from: dateFrom,
        date_to: dateTo || null,
      },
      deductions,
      tolerance: { absolute_paise: abs, percent: tolPct.trim() },
      priority: pr,
      effective_confidence: confidence.trim(),
    };
  })();

  const updateRow = (i: number, patch: Partial<DedRow>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  return (
    <div className="grid grid-cols-1 gap-6 px-5 py-5 lg:grid-cols-[1fr_300px]">
      <form
        className="flex flex-col gap-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (body) create.mutate(body, { onSuccess: (rule) => onCreated(rule) });
        }}
      >
        <section className="flex flex-col gap-3">
          <div className="fc-label">Identity</div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name">
              <input
                style={inputStyle}
                value={name}
                autoFocus
                onChange={(e) => {
                  setName(e.target.value);
                  if (!idTouched) setRuleId(slug(e.target.value));
                }}
                placeholder="Razorpay card MDR with GST"
              />
            </Field>
            <Field label="Rule id" hint="Stable. Versions hang off it.">
              <input
                className="fc-num"
                style={inputStyle}
                value={ruleId}
                onChange={(e) => {
                  setIdTouched(true);
                  setRuleId(slug(e.target.value));
                }}
                placeholder="razorpay_card_mdr"
              />
            </Field>
          </div>
          <Field label="Description">
            <input
              style={inputStyle}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this deduction is, in one sentence"
            />
          </Field>
        </section>

        <section className="flex flex-col gap-3">
          <div className="fc-label">Applies to</div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Rule set">
              <input style={inputStyle} list="fc-rule-sets" value={ruleSet} onChange={(e) => setRuleSet(e.target.value)} />
              <datalist id="fc-rule-sets">
                {ruleSets.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </Field>
            <Field label="Counterparty matches" hint="Comma separated">
              <input
                style={inputStyle}
                value={counterparty}
                onChange={(e) => setCounterparty(e.target.value)}
                placeholder="Razorpay, RAZORPAY SOFTWARE"
              />
            </Field>
            <Field label="Narration contains" hint="Comma separated">
              <input
                style={inputStyle}
                value={narration}
                onChange={(e) => setNarration(e.target.value)}
                placeholder="SETL, MDR"
              />
            </Field>
            <div className="grid grid-cols-3 gap-2">
              <Field label="Source">
                <select style={inputStyle} value={source} onChange={(e) => setSource(e.target.value as Source | "")}>
                  <option value="">Any</option>
                  {SOURCES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Rail">
                <select style={inputStyle} value={rail} onChange={(e) => setRail(e.target.value as Rail | "")}>
                  <option value="">Any</option>
                  {RAILS.map((s) => (
                    <option key={s} value={s}>
                      {s.toUpperCase()}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Method">
                <select style={inputStyle} value={method} onChange={(e) => setMethod(e.target.value as Method | "")}>
                  <option value="">Any</option>
                  {METHODS.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Effective from">
              <input className="fc-num" style={inputStyle} type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
            </Field>
            <Field label="Effective to" hint="Leave open unless the rate ends">
              <input className="fc-num" style={inputStyle} type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
            </Field>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="fc-label">Deductions, in order</div>
            <button
              type="button"
              className="fc-btn fc-btn--ghost"
              style={{ padding: "5px 10px", fontSize: 12 }}
              onClick={() => setRows((rs) => [...rs, { type: "custom", basis: "gross", rate: "", fixed: "" }])}
            >
              <Plus size={13} />
              Add layer
            </button>
          </div>
          <div className="flex flex-col gap-2">
            {rows.map((r, i) => (
              <div key={i} className="grid grid-cols-[1fr_1fr_88px_110px_30px] items-center gap-2">
                <select
                  style={inputStyle}
                  value={r.type}
                  onChange={(e) => updateRow(i, { type: e.target.value as DeductionType })}
                  aria-label="Deduction type"
                >
                  {DEDUCTION_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {deductionLabel(t)}
                    </option>
                  ))}
                </select>
                <select
                  style={inputStyle}
                  value={r.basis}
                  onChange={(e) => updateRow(i, { basis: e.target.value as DeductionBasis })}
                  aria-label="Basis"
                >
                  {DEDUCTION_BASES.map((b) => (
                    <option key={b} value={b}>
                      {basisLabel(b)}
                    </option>
                  ))}
                </select>
                <div className="relative">
                  <input
                    className="fc-num"
                    style={{
                      ...inputStyle,
                      paddingRight: 22,
                      ...(r.rate.trim() && Number.isNaN(Number(r.rate)) ? { borderColor: "var(--fc-bad)" } : null),
                    }}
                    value={r.rate}
                    onChange={(e) => updateRow(i, { rate: e.target.value })}
                    placeholder="rate"
                    inputMode="decimal"
                    aria-label="Rate percent"
                  />
                  <span className="fc-faint pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2" style={{ fontSize: 12 }}>
                    %
                  </span>
                </div>
                <input
                  className="fc-num"
                  style={inputStyle}
                  value={r.fixed}
                  onChange={(e) => updateRow(i, { fixed: e.target.value })}
                  placeholder="+ fixed paise"
                  inputMode="numeric"
                  aria-label="Fixed paise"
                />
                <button
                  type="button"
                  className="fc-btn fc-btn--ghost"
                  style={{ padding: "8px", justifyContent: "center" }}
                  aria-label="Remove layer"
                  disabled={rows.length === 1}
                  onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
          <p className="fc-faint" style={{ fontSize: 11.5 }}>
            Bases chain. GST on fee is usually a percentage of the MDR layer above it, not of gross.
          </p>
        </section>

        <section className="flex flex-col gap-3">
          <div className="fc-label">Tolerance and ranking</div>
          <div className="grid grid-cols-4 gap-3">
            <Field label="Absolute, paise">
              <input className="fc-num" style={inputStyle} value={tolAbs} onChange={(e) => setTolAbs(e.target.value)} inputMode="numeric" />
            </Field>
            <Field label="Percent">
              <input className="fc-num" style={inputStyle} value={tolPct} onChange={(e) => setTolPct(e.target.value)} inputMode="decimal" />
            </Field>
            <Field label="Priority" hint="Lower fires first">
              <input className="fc-num" style={inputStyle} value={priority} onChange={(e) => setPriority(e.target.value)} inputMode="numeric" />
            </Field>
            <Field label="Confidence">
              <input className="fc-num" style={inputStyle} value={confidence} onChange={(e) => setConfidence(e.target.value)} inputMode="decimal" />
            </Field>
          </div>
        </section>

        {create.error && <FcErrorNote message={errorMessage(create.error)} />}

        <div className="flex items-center justify-between gap-3 border-t pt-4">
          <span className="fc-faint" style={{ fontSize: 11.5 }}>
            {body ? "Saves as a draft. Nothing changes until you activate it." : "Name, id, a start date and a numeric rate on every layer."}
          </span>
          <button type="submit" className="fc-btn" disabled={!body || create.isPending}>
            <Save size={13} />
            {create.isPending ? "Saving…" : "Save draft"}
          </button>
        </div>
      </form>

      <aside className="lg:sticky lg:top-0 lg:self-start">
        <div className="fc-card fc-card--flat flex flex-col gap-3 p-4">
          <div className="flex items-center justify-between">
            <div className="fc-label">Preview on ₹10,000</div>
            {preview.loading && <span className="fc-faint" style={{ fontSize: 11 }}>…</span>}
          </div>
          {preview.error && <FcErrorNote message={preview.error} />}
          {!preview.data && !preview.loading && !preview.error && (
            <p className="fc-faint" style={{ fontSize: 12 }}>
              Enter a rate on every layer to see the stack.
            </p>
          )}
          {preview.data && (
            <div className={clsx("transition-opacity", preview.loading && "opacity-50")}>
              <div className="fc-ev-math" style={{ paddingTop: 0 }}>
                <span>Gross</span>
                <FcMoney paise={SAMPLE_GROSS_PAISE} size="sm" />
              </div>
              <div className="fc-divider" style={{ margin: "8px 0" }} />
              <div className="flex flex-col gap-1.5">
                {preview.data.stack.map((l, i) => (
                  <div key={i} className="grid grid-cols-[1fr_auto] gap-x-3" style={{ fontSize: 12.5 }}>
                    <div className="min-w-0">
                      <div className="truncate fc-strong">{deductionLabel(l.type)}</div>
                      <div className="fc-faint" style={{ fontSize: 11 }}>
                        {rateText(l.rate)} {basisLabel(l.basis)} · <FcMoney paise={l.basis_paise} size="sm" className="fc-faint" />
                      </div>
                    </div>
                    <FcMoney paise={-l.amount_paise} size="sm" className="text-right" />
                  </div>
                ))}
              </div>
              <div className="fc-divider" style={{ margin: "8px 0" }} />
              <div className="fc-ev-math">
                <span>Total deducted</span>
                <FcMoney paise={preview.data.total_paise} size="sm" />
              </div>
              <div className="fc-ev-math fc-ev-math--total">
                <span className="fc-strong">Net</span>
                <FcMoney paise={preview.data.net_paise} tone="ok" />
              </div>
            </div>
          )}
          <p className="fc-faint" style={{ fontSize: 11 }}>Computed by the server. The same code applies the rule in a run.</p>
        </div>
      </aside>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="flex items-baseline justify-between">
        <span className="fc-muted" style={{ fontSize: 11.5, fontWeight: 500 }}>
          {label}
        </span>
        {hint && (
          <span className="fc-faint" style={{ fontSize: 10.5 }}>
            {hint}
          </span>
        )}
      </span>
      {children}
    </label>
  );
}
