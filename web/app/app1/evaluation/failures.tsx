"use client";

// The honest list. Generated from the run, never hand-written.

import { useRouter } from "next/navigation";
import { categoryLabel } from "../_lib/labels";
import { plural } from "../_lib/format";
import { FcCard, FcChip, FcEmpty, FcMoney, Identifier, type FcTone } from "../_components/fc-ui";
import type { Failure } from "./shape";

const MONO: React.CSSProperties = { fontFamily: "var(--font-geist-mono)" };

function kindTone(kind: string): FcTone {
  const k = kind.toLowerCase();
  if (k.includes("wrong") || k.includes("false")) return "bad";
  if (k.includes("miss") || k.includes("not")) return "warn";
  if (k.includes("abstain") || k.includes("refus")) return "accent";
  return "neutral";
}

function kindLabel(kind: string): string {
  return kind.replace(/_/g, " ");
}

function label(l: string | null): string {
  if (l === null || l === "") return "nothing";
  if (l.includes(" ")) return l;
  return categoryLabel(l);
}

export function HonestList({ failures }: { failures: Failure[] }) {
  const router = useRouter();
  const sorted = [...failures].sort((a, b) => Math.abs(b.amount_paise) - Math.abs(a.amount_paise));
  const byKind = new Map<string, number>();
  for (const f of failures) byKind.set(f.kind, (byKind.get(f.kind) ?? 0) + 1);

  if (failures.length === 0) {
    return (
      <FcCard variant="flat">
        <FcEmpty title="Nothing to list" sub="Every item in the corpus was matched, escalated or refused exactly as ground truth says." />
      </FcCard>
    );
  }

  return (
    <FcCard variant="flat">
      <div className="flex flex-wrap items-center gap-2" style={{ padding: "16px 16px 12px" }}>
        <span className="fc-muted" style={{ fontSize: 12.5 }}>{plural(failures.length, "item")} across</span>
        {[...byKind.entries()]
          .sort((a, b) => b[1] - a[1])
          .map(([k, n]) => (
            <FcChip key={k} tone={kindTone(k)}>
              {kindLabel(k)} <span className="fc-num">{n}</span>
            </FcChip>
          ))}
      </div>
      <div className="overflow-auto" style={{ maxHeight: 560 }}>
        <table className="fc-table">
          <thead>
            <tr>
              <th className="text-right">Amount</th>
              <th>Kind</th>
              <th>Ground truth</th>
              <th>We said</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((f, i) => {
              const firstId = f.event_ids[0];
              const clickable = Boolean(firstId);
              return (
                <tr
                  key={i}
                  className={clickable ? "fc-row-click" : undefined}
                  onClick={clickable ? () => router.push(`/app1/records?q=${encodeURIComponent(firstId)}`) : undefined}
                >
                  <td className="text-right" style={MONO}>
                    <FcMoney paise={f.amount_paise} />
                    <div className="flex flex-wrap justify-end gap-1 mt-0.5">
                      {f.event_ids.slice(0, 3).map((id) => (
                        <Identifier key={id} value={id} />
                      ))}
                      {f.event_ids.length > 3 && (
                        <span className="fc-faint" style={{ fontSize: 10.5 }}>{`+${f.event_ids.length - 3}`}</span>
                      )}
                    </div>
                  </td>
                  <td>
                    <FcChip tone={kindTone(f.kind)}>{kindLabel(f.kind)}</FcChip>
                  </td>
                  <td style={{ color: "var(--fc-ok)" }}>{label(f.gt_label)}</td>
                  <td style={f.our_label === f.gt_label ? undefined : { color: "var(--fc-bad)" }}>{label(f.our_label)}</td>
                  <td className="fc-muted" style={{ maxWidth: 420, fontSize: 12 }}>{f.why}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </FcCard>
  );
}
