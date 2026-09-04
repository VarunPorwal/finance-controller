"use client";

import type { S } from "../_lib/api";
import { categoryLabel, stageLabel, STAGE_ORDER } from "../_lib/labels";
import { pct } from "../_lib/format";
import { FcCard, FcCardHeader } from "../_components/fc-ui";
import { isRec, num, type Rec } from "./shape";

type Confusion = S["ConfusionOut"];

const MONO: React.CSSProperties = { fontFamily: "var(--font-geist-mono)" };

interface CategoryRow {
  key: string;
  raised: number | null;
  correct: number | null;
  gt_total: number | null;
  precision: number | null;
  recall: number | null;
}

export function ConfusionTables({ confusion }: { confusion: Confusion }) {
  const byCategory: CategoryRow[] = Object.entries(confusion.by_category)
    .filter((e): e is [string, Rec] => isRec(e[1]))
    .map(([key, v]) => ({
      key,
      raised: num(v.raised),
      correct: num(v.correct),
      gt_total: num(v.gt_total),
      precision: num(v.precision),
      recall: num(v.recall),
    }))
    .sort((a, b) => (b.raised ?? 0) - (a.raised ?? 0) || a.key.localeCompare(b.key));

  const stageEntries = Object.entries(confusion.by_stage).filter((e): e is [string, Rec] => isRec(e[1]));
  const stageCols = [...new Set(stageEntries.flatMap(([, v]) => Object.keys(v).filter((k) => num(v[k]) !== null)))];
  const stageRows = stageEntries.sort(([a], [b]) => {
    const ia = STAGE_ORDER.indexOf(a as (typeof STAGE_ORDER)[number]);
    const ib = STAGE_ORDER.indexOf(b as (typeof STAGE_ORDER)[number]);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });

  return (
    <div className="grid gap-3 xl:grid-cols-[3fr_2fr]">
      <FcCard variant="flat">
        <FcCardHeader title="By category" sub="What it raised against what ground truth holds" />
        <div className="overflow-auto" style={{ maxHeight: 420 }}>
          <table className="fc-table">
            <thead>
              <tr>
                <th>Category</th>
                <th className="text-right">Raised</th>
                <th className="text-right">Correct</th>
                <th className="text-right">In truth</th>
                <th className="text-right">Precision</th>
                <th className="text-right">Recall</th>
              </tr>
            </thead>
            <tbody>
              {byCategory.map((r) => (
                <tr key={r.key}>
                  <td className="fc-ref">{categoryLabel(r.key)}</td>
                  <td className="fc-table-num" style={MONO}>{r.raised ?? "—"}</td>
                  <td className="fc-table-num" style={MONO}>{r.correct ?? "—"}</td>
                  <td className="fc-table-num fc-faint" style={MONO}>{r.gt_total ?? "—"}</td>
                  <td className="text-right">
                    <PrecisionCell value={r.precision} />
                  </td>
                  <td className="text-right">
                    <RecallCell value={r.recall} />
                  </td>
                </tr>
              ))}
              {byCategory.length === 0 && (
                <tr>
                  <td colSpan={6} className="fc-faint">
                    No categories scored.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </FcCard>

      <FcCard variant="flat">
        <FcCardHeader title="By stage" sub="Which cascade stage formed the pair" />
        <div className="overflow-auto" style={{ maxHeight: 420 }}>
          <table className="fc-table">
            <thead>
              <tr>
                <th>Stage</th>
                {stageCols.map((c) => (
                  <th key={c} className="text-right">
                    {c.replace(/_/g, " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stageRows.map(([key, v]) => (
                <tr key={key}>
                  <td className="fc-ref">{stageLabel(key)}</td>
                  {stageCols.map((c) => {
                    const val = num(v[c]);
                    if (c.includes("recall")) return <td key={c} className="text-right"><RecallCell value={val} /></td>;
                    if (isRate(c)) return <td key={c} className="text-right"><PrecisionCell value={val} /></td>;
                    return (
                      <td key={c} className="fc-table-num" style={MONO}>
                        {val ?? "—"}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {stageRows.length === 0 && (
                <tr>
                  <td colSpan={1 + stageCols.length} className="fc-faint">
                    No stages scored.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </FcCard>
    </div>
  );
}

function isRate(key: string): boolean {
  return key.includes("precision") || key.includes("recall") || key.includes("rate") || key.includes("pct");
}

// Color is spent only where a cell is actually a problem (0%, nothing
// proved) — a strong score reads in the ordinary text color, not a
// celebratory green, so the red the rest of the table earns still stands out.
function PrecisionCell({ value }: { value: number | null }) {
  if (value === null) return <span className="fc-faint">—</span>;
  const problem = value === 0;
  return (
    <span className="fc-num" style={{ ...MONO, color: problem ? "var(--fc-bad)" : "var(--fc-text)" }}>
      {pct(value, 1)}
    </span>
  );
}

function RecallCell({ value }: { value: number | null }) {
  if (value === null) return <span className="fc-faint">—</span>;
  const w = Math.max(0, Math.min(1, value));
  const problem = w === 0;
  return (
    <span className="flex items-center justify-end gap-2">
      <span className="h-1 w-14 overflow-hidden rounded" style={{ background: "var(--fc-divider)" }}>
        <span
          className="block h-full rounded"
          style={{ width: `${w * 100}%`, background: problem ? "var(--fc-bad)" : "var(--fc-accent)" }}
        />
      </span>
      <span className="fc-num" style={{ ...MONO, fontSize: 12, color: problem ? "var(--fc-bad)" : "var(--fc-text)" }}>
        {pct(value, 0)}
      </span>
    </span>
  );
}
