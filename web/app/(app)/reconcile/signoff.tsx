"use client";

// What blocks closing the period, and the two exports a controller takes to
// the auditor. The close pack is built from the register rows in the browser;
// the audit export streams from the API.

import { useMemo, useState } from "react";
import Link from "next/link";
import { Download, ExternalLink, GitCompare, Play } from "lucide-react";
import { FcCard, FcCardHeader, FcMoney } from "../_components/fc-ui";
import { plural, sumPaise } from "../_lib/format";
import { CATEGORY, categoryLabel } from "../_lib/labels";
import type { Exception } from "../_lib/api";
import { isOpen, registerCsv, type RegisterRow } from "../settlements/register";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function SignOff({ rows, exceptions, runId }: { rows: RegisterRow[]; exceptions: Exception[]; runId: string }) {
  const [exported, setExported] = useState(false);

  const blockers = useMemo(() => {
    const byCat = new Map<string, Exception[]>();
    for (const x of exceptions) {
      if (!isOpen(x)) continue;
      const list = byCat.get(x.category);
      if (list) list.push(x);
      else byCat.set(x.category, [x]);
    }
    return [...byCat.entries()]
      .map(([category, list]) => ({
        category,
        count: list.length,
        paise: sumPaise(list.map((x) => x.amount_paise)),
        neverAuto: CATEGORY[category as keyof typeof CATEGORY]?.neverAuto ?? false,
      }))
      .sort((a, b) => b.paise - a.paise);
  }, [exceptions]);

  const openTotal = sumPaise(blockers.map((b) => b.paise));
  const openCount = blockers.reduce((n, b) => n + b.count, 0);

  function exportClosePack() {
    const csv = registerCsv(rows);
    const blob = new Blob(["﻿", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `close-pack-${runId.slice(-6).toLowerCase()}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setExported(true);
  }

  return (
    <div className="fc-split">
      <FcCard style={{ padding: 0 }}>
        <FcCardHeader
          title="Sign-off"
          sub={
            openCount === 0
              ? "Nothing is open. The period can close."
              : `${plural(openCount, "open decision")} stand between this period and a close.`
          }
        />
        <div style={{ padding: "0 16px 14px" }}>
          {blockers.length === 0 ? (
            <div
              style={{
                borderRadius: 10,
                border: "1px solid color-mix(in srgb, var(--fc-ok) 35%, transparent)",
                background: "color-mix(in srgb, var(--fc-ok) 10%, transparent)",
                padding: "8px 12px",
                fontSize: 12.5,
                color: "var(--fc-ok)",
              }}
            >
              Every settlement is proven, explained by a rule, or resolved by a person.
            </div>
          ) : (
            <div className="grid gap-x-8 md:grid-cols-2">
              {blockers.map((b) => (
                <Link
                  key={b.category}
                  href="/decisions"
                  className="-mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-2 transition-colors hover:bg-[var(--fc-card-hover)]"
                  style={{ fontSize: 12.5, borderBottom: "1px solid var(--fc-divider)" }}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate">{categoryLabel(b.category)}</span>
                    {b.neverAuto && (
                      <span
                        style={{
                          background: "var(--fc-divider)",
                          color: "var(--fc-text-3)",
                          fontSize: 11,
                          padding: "2px 8px",
                          borderRadius: 20,
                          whiteSpace: "nowrap",
                        }}
                      >
                        never auto
                      </span>
                    )}
                  </span>
                  <span className="flex shrink-0 items-center gap-3">
                    <span className="fc-faint fc-num" style={{ fontSize: 11.5 }}>{plural(b.count, "item")}</span>
                    <FcMoney paise={b.paise} tone="warn" />
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </FcCard>

      <FcCard className="flex flex-col gap-3">
        <div>
          <div className="fc-label">Open, in total</div>
          <FcMoney paise={openTotal} size="lg" tone={openTotal > 0 ? "warn" : "ok"} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Link href="/run" className="fc-btn fc-btn--ghost w-full justify-center">
            <Play size={13} />
            Run reconciliation
          </Link>
          <Link href="/controller-activity#diff" className="fc-btn fc-btn--ghost w-full justify-center">
            <GitCompare size={13} />
            Replay and diff
          </Link>
          <button className="fc-btn w-full justify-center" onClick={exportClosePack}>
            <Download size={13} />
            {exported ? "Export again" : "Export close pack"}
          </button>
          <a
            href={`${API_BASE}/api/v1/audit/export?format=csv`}
            target="_blank"
            rel="noreferrer"
            className="fc-btn fc-btn--ghost w-full justify-center"
          >
            Audit export <ExternalLink size={13} />
          </a>
        </div>

        <p className="fc-faint" style={{ fontSize: 11.5 }}>
          The close pack lists every settlement with what Razorpay, the bank and Tally each said and who decided. The
          audit export is the hash-chained log of every action taken.
        </p>
      </FcCard>
    </div>
  );
}
