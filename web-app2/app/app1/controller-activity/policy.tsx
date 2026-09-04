"use client";

import { ShieldCheck, UserRound } from "lucide-react";
import { CATEGORY } from "../_lib/labels";
import { FcCard } from "../_components/fc-ui";

export function PolicyTable() {
  const entries = Object.entries(CATEGORY);
  const auto = entries.filter(([, v]) => !v.neverAuto);
  const human = entries.filter(([, v]) => v.neverAuto);
  return (
    <div className="grid gap-3 md:grid-cols-2 items-stretch">
      <FcCard variant="flat">
        <div style={{ padding: "16px 17px" }}>
          <div className="mb-3 flex items-center gap-2">
            <ShieldCheck size={14} style={{ color: "var(--fc-ok)" }} />
            <span className="fc-card-title">May close automatically</span>
          </div>
          <p className="fc-faint mb-3" style={{ fontSize: 12 }}>
            Only above the confidence threshold, only with evidence, and only when the bank is one of the sources.
          </p>
          <ul className="flex flex-col gap-2">
            {auto.map(([k, v]) => (
              <li key={k} style={{ fontSize: 12.5 }}>
                <div>{v.label}</div>
                <div className="fc-faint" style={{ fontSize: 11.5 }}>{v.hint}</div>
              </li>
            ))}
          </ul>
        </div>
      </FcCard>
      <FcCard variant="flat" style={{ borderColor: "color-mix(in srgb, var(--fc-warn) 45%, transparent)" }}>
        <div style={{ padding: "16px 17px" }}>
          <div className="mb-3 flex items-center gap-2">
            <UserRound size={14} style={{ color: "var(--fc-warn)" }} />
            <span className="fc-card-title">Always goes to a human</span>
          </div>
          <p className="mb-3" style={{ fontSize: 12, color: "var(--fc-warn)" }}>High confidence alone is never sufficient for these.</p>
          <ul className="flex flex-col gap-2">
            {human.map(([k, v]) => (
              <li key={k} style={{ fontSize: 12.5 }}>
                <div>{v.label}</div>
                <div className="fc-faint" style={{ fontSize: 11.5 }}>{v.hint}</div>
              </li>
            ))}
          </ul>
        </div>
      </FcCard>
    </div>
  );
}
