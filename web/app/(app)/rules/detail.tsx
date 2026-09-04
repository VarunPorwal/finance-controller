"use client";

// Rule detail. Everything the card shows, the worked example on a real
// settlement, the version timeline, the back-test panel, and the three human
// actions that change a rule's status: back-test, activate/edit (a new
// version), retire.

import { useState } from "react";
import { clsx } from "clsx";
import { FlaskConical, Power, Archive, Trash2, Lock } from "lucide-react";
import Link from "next/link";
import { useRuleVersions, useWrite, writes, errorMessage, type Rule } from "../_lib/api";
import { formatDateShort, formatDateTime, hashShort, money, plural, shortId } from "../_lib/format";
import { FcErrorNote, FcMoney, Identifier } from "../_components/fc-ui";
import { BacktestResult, BacktestSkeleton } from "./backtest";
import { MiniWaterfall } from "./waterfall";
import { Evidence } from "./cards";
import {
  basisLabel,
  confidenceText,
  deductionLabel,
  FcPanel,
  illustrate,
  OriginPill,
  rateText,
  scopeLines,
  StatusPill,
  type RuleUsage,
} from "./shared";

export function RuleDetail({
  rule,
  open,
  onClose,
  usage,
  promptBacktest,
}: {
  rule: Rule | null;
  open: boolean;
  onClose: () => void;
  usage?: RuleUsage;
  promptBacktest?: boolean;
}) {
  return (
    <FcPanel
      open={open && !!rule}
      onClose={onClose}
      width={680}
      title={rule?.name}
      sub={
        rule && (
          <span className="flex items-center gap-2 fc-num">
            <Identifier value={rule.rule_id} />
            <span className="fc-chip">v{rule.version}</span>
          </span>
        )
      }
    >
      {rule && <Body key={`${rule.rule_id}:${rule.version}`} rule={rule} usage={usage} promptBacktest={promptBacktest} />}
    </FcPanel>
  );
}

function Body({ rule, usage, promptBacktest }: { rule: Rule; usage?: RuleUsage; promptBacktest?: boolean }) {
  const versions = useRuleVersions(rule.rule_id);
  const illustrated = illustrate(rule.deductions ?? []);

  const backtest = useWrite((a: { ruleId: string; version: number }) =>
    writes.backtest(a.ruleId, a.version, undefined as never),
  );
  const activate = useWrite((a: { ruleId: string; version: number; reason: string }) =>
    writes.activate(a.ruleId, a.version, { reason: a.reason }),
  );
  const retire = useWrite((a: { ruleId: string; version: number; reason: string }) =>
    writes.retire(a.ruleId, a.version, { reason: a.reason }),
  );

  const [ack, setAck] = useState(false);
  const [activateReason, setActivateReason] = useState("Back-test reviewed; explains the gap without wrong closes.");
  const [retiring, setRetiring] = useState(false);
  const [retireReason, setRetireReason] = useState("");

  const tested = !!backtest.data;
  const isDraft = rule.status === "draft";
  const isActive = rule.status === "active";
  const isRetired = rule.status === "retired";
  const writeErr = activate.error ?? retire.error;

  return (
    <div className="flex flex-col gap-6 px-5 py-5">
      <div className="flex flex-wrap items-center gap-1.5">
        <StatusPill status={rule.status} />
        <OriginPill origin={rule.origin} />
        <span className="fc-chip fc-num">
          {formatDateShort(rule.effective_from)} → {rule.effective_to ? formatDateShort(rule.effective_to) : "open"}
        </span>
        <span className="fc-chip fc-num">{hashShort(rule.version_hash, 10)}</span>
      </div>
      {rule.description && (
        <p className="fc-muted -mt-2" style={{ fontSize: 13 }}>
          {rule.description}
        </p>
      )}

      {promptBacktest && !tested && (
        <div
          className="rounded-lg px-3 py-2"
          style={{ border: "1px solid rgba(242,185,70,0.35)", background: "rgba(242,185,70,0.1)", fontSize: 12.5, color: "var(--fc-warn)" }}
        >
          Draft saved. Back-test it against this run before activating.
        </div>
      )}

      {/* ---------- the stack ---------- */}
      <section className="flex flex-col gap-3">
        <div className="fc-label">What it deducts</div>
        <div className="flex items-end justify-between gap-4">
          <MiniWaterfall deductions={rule.deductions ?? []} width={400} height={96} />
          <div className="fc-faint text-right" style={{ fontSize: 11, lineHeight: 1.4 }}>
            illustration
            <br />
            on ₹10,000
          </div>
        </div>
        <div className="fc-card fc-card--flat" style={{ overflowX: "auto" }}>
          <table className="fc-table">
            <thead>
              <tr>
                <th>Deduction</th>
                <th>Basis</th>
                <th className="fc-table-num">Rate</th>
                <th className="fc-table-num">On ₹10,000</th>
              </tr>
            </thead>
            <tbody>
              {illustrated.lines.map((l, i) => (
                <tr key={i}>
                  <td className="fc-ref">{deductionLabel(l.type)}</td>
                  <td>{basisLabel(l.basis)}</td>
                  <td className="fc-table-num fc-num">{rateText(l.rate)}</td>
                  <td className="fc-table-num fc-num">{money(l.amount)}</td>
                </tr>
              ))}
              <tr>
                <td className="fc-faint" colSpan={3}>
                  Total deducted
                </td>
                <td className="fc-table-num fc-num">{money(illustrated.total)}</td>
              </tr>
              <tr>
                <td className="fc-strong" colSpan={3}>
                  Net
                </td>
                <td className="fc-table-num fc-num" style={{ color: "var(--fc-ok)" }}>
                  {money(illustrated.net)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div className="grid grid-cols-2 gap-6">
          <dl className="flex flex-col gap-1.5" style={{ fontSize: 12.5 }}>
            <KV
              label="Tolerance"
              value={`±${money(rule.tolerance.absolute_paise, { whole: true })} or ${rateText(rule.tolerance.percent)}`}
            />
            <KV label="Priority" value={String(rule.priority)} />
            <KV label="Confidence when applied" value={confidenceText(rule.effective_confidence)} />
          </dl>
          <dl className="flex flex-col gap-1.5" style={{ fontSize: 12.5 }}>
            {scopeLines(rule.scope).map(([k, v]) => (
              <KV key={k} label={k} value={v} />
            ))}
          </dl>
        </div>
      </section>

      <div className="fc-divider" />

      {/* ---------- in this run ---------- */}
      <section className="flex flex-col gap-2">
        <div className="fc-label">In this run</div>
        <Evidence usage={usage} />
        {usage?.example && (
          <div className="fc-ev-rule mt-1">
            <div className="fc-ev-label">Worked example, on an actual settlement</div>
            {usage.example.arithmetic ? (
              <p className="fc-muted mb-2" style={{ fontSize: 12.5, lineHeight: 1.6 }}>
                {usage.example.arithmetic}
              </p>
            ) : (
              <p className="fc-faint mb-2" style={{ fontSize: 12.5 }}>
                Explained <FcMoney paise={usage.example.explainedPaise} size="sm" tone="ok" /> of one case; the run did not
                record the arithmetic text for it.
              </p>
            )}
            <Link
              href={`/decisions?open=${encodeURIComponent(usage.example.exceptionId)}`}
              className="fc-link fc-num"
              title={usage.example.exceptionId}
            >
              {shortId(usage.example.exceptionId)} →
            </Link>
          </div>
        )}
        {usage && usage.exceptionIds.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-1">
            {usage.exceptionIds.slice(0, 12).map((id) => (
              <Link key={id} href={`/decisions?open=${encodeURIComponent(id)}`} title={id}>
                <span className="fc-chip fc-num">{shortId(id)}</span>
              </Link>
            ))}
            {usage.exceptionIds.length > 12 && (
              <span className="fc-faint" style={{ fontSize: 11.5 }}>
                +{usage.exceptionIds.length - 12} more
              </span>
            )}
          </div>
        )}
      </section>

      <div className="fc-divider" />

      {/* ---------- versions ---------- */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="fc-label">Versions</div>
          <span className="fc-faint flex items-center gap-1.5" style={{ fontSize: 11.5 }}>
            <Lock size={11} />A rule is immutable per version. June replays at June&apos;s rate.
          </span>
        </div>
        {versions.isLoading && (
          <div className="flex flex-col gap-2">
            {[0, 1].map((i) => (
              <div key={i} className="animate-pulse" style={{ height: 14, borderRadius: 6, background: "var(--fc-divider)" }} />
            ))}
          </div>
        )}
        {versions.error && <FcErrorNote message={errorMessage(versions.error)} />}
        {versions.data && <Timeline versions={[...versions.data].sort((a, b) => b.version - a.version)} current={rule.version} />}
      </section>

      <div className="fc-divider" />

      {/* ---------- back-test ---------- */}
      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <div className="fc-label">Back-test</div>
          <button
            className="fc-btn"
            style={{ padding: "6px 12px", fontSize: 12.5 }}
            disabled={backtest.isPending}
            onClick={() => backtest.mutate({ ruleId: rule.rule_id, version: rule.version })}
          >
            <FlaskConical size={13} />
            {backtest.isPending ? "Running…" : tested ? "Run again" : "Back-test against this run"}
          </button>
        </div>
        {!tested && !backtest.isPending && (
          <p className="fc-faint" style={{ fontSize: 12.5 }}>
            Replays this version over every case in the run and says what it would have explained, what it would
            have closed wrongly, and what it only shrinks.
          </p>
        )}
        {backtest.isPending && <BacktestSkeleton />}
        {backtest.error && <FcErrorNote message={errorMessage(backtest.error)} />}
        {backtest.data && <BacktestResult result={backtest.data} />}
      </section>

      {!isRetired && (
        <>
          <div className="fc-divider" />
          <section className="flex flex-col gap-3">
            <div className="fc-label">Decide</div>
            {!isActive && (
              <div
                className={clsx("fc-card fc-card--flat flex flex-col gap-3 p-4", !tested && "opacity-60")}
              >
                <label className="flex cursor-pointer items-center gap-2" style={{ fontSize: 12.5 }}>
                  <input
                    type="checkbox"
                    checked={ack}
                    disabled={!tested}
                    onChange={(e) => setAck(e.target.checked)}
                  />
                  I have read the back-test
                </label>
                <input
                  className="fc-num"
                  style={inputStyle}
                  value={activateReason}
                  disabled={!tested}
                  onChange={(e) => setActivateReason(e.target.value)}
                  placeholder="Why this rule should apply from now on"
                />
                <div className="flex items-center justify-between gap-3">
                  <span className="fc-faint" style={{ fontSize: 11.5 }}>
                    {tested ? "Activation is recorded in the audit trail with your name." : "Back-test first, this is a rule that changes state on real cases."}
                  </span>
                  <button
                    className="fc-btn"
                    style={{ padding: "7px 14px", fontSize: 12.5 }}
                    disabled={!tested || !ack || !activateReason.trim() || activate.isPending}
                    onClick={() =>
                      activate.mutate({ ruleId: rule.rule_id, version: rule.version, reason: activateReason.trim() })
                    }
                  >
                    <Power size={13} />
                    {activate.isPending ? "Activating…" : `Activate v${rule.version}`}
                  </button>
                </div>
              </div>
            )}

            {retiring ? (
              <div className="fc-card fc-card--flat flex flex-col gap-3 p-4">
                <input
                  style={inputStyle}
                  autoFocus
                  value={retireReason}
                  onChange={(e) => setRetireReason(e.target.value)}
                  placeholder={isDraft ? "Why this draft is being discarded" : "Why this rule no longer applies"}
                />
                <div className="flex justify-end gap-2">
                  <button className="fc-btn fc-btn--ghost" style={{ padding: "6px 12px", fontSize: 12.5 }} onClick={() => setRetiring(false)}>
                    Keep
                  </button>
                  <button
                    className="fc-btn"
                    style={{ padding: "6px 12px", fontSize: 12.5, background: "var(--fc-bad)" }}
                    disabled={!retireReason.trim() || retire.isPending}
                    onClick={() =>
                      retire.mutate({ ruleId: rule.rule_id, version: rule.version, reason: retireReason.trim() })
                    }
                  >
                    {retire.isPending ? "Working…" : isDraft ? "Discard draft" : "Retire"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex justify-end">
                <button className="fc-btn fc-btn--ghost" style={{ padding: "6px 12px", fontSize: 12.5 }} onClick={() => setRetiring(true)}>
                  {isDraft ? <Trash2 size={13} /> : <Archive size={13} />}
                  {isDraft ? "Discard" : "Retire"}
                </button>
              </div>
            )}

            {activate.isSuccess && (
              <div
                className="rounded-lg px-3 py-2"
                style={{ border: "1px solid rgba(62,168,43,0.35)", background: "rgba(62,168,43,0.1)", fontSize: 12.5, color: "var(--fc-ok)" }}
              >
                Activated. The next run applies v{rule.version} from {formatDateShort(rule.effective_from)}.
              </div>
            )}
            {retire.isSuccess && (
              <div className="fc-card fc-card--flat px-3 py-2" style={{ fontSize: 12.5 }}>
                {isDraft ? "Draft discarded." : "Retired. Runs before today keep using it; new runs will not."}
              </div>
            )}
            {writeErr && <FcErrorNote message={errorMessage(writeErr)} />}
          </section>
        </>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  borderRadius: 8,
  border: "1px solid var(--fc-border)",
  background: "var(--fc-hover)",
  color: "var(--fc-text)",
  padding: "8px 10px",
  fontSize: 12.5,
  outline: "none",
};

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="fc-faint whitespace-nowrap">{label}</dt>
      <dd className="fc-num text-right">{value}</dd>
    </div>
  );
}

function Timeline({ versions, current }: { versions: Rule[]; current: number }) {
  return (
    <ol className="relative ml-2 flex flex-col gap-4 border-l pl-5">
      {versions.map((v) => {
        const isCurrent = v.version === current;
        return (
          <li key={v.version} className="relative">
            <span
              className="absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full border"
              style={{
                borderColor: v.status === "active" ? "var(--fc-ok)" : v.status === "draft" ? "var(--fc-text-3)" : "var(--fc-border)",
                background: v.status === "active" ? "var(--fc-ok)" : v.status === "draft" ? "var(--fc-divider)" : "var(--fc-bg)",
              }}
            />
            <div className="flex flex-wrap items-center gap-2">
              <span className={clsx("fc-num", isCurrent ? "fc-strong" : "fc-muted")} style={{ fontSize: 13 }}>
                v{v.version}
              </span>
              <StatusPill status={v.status} />
              <span className="fc-faint fc-num" style={{ fontSize: 11.5 }}>
                {hashShort(v.version_hash, 10)}
              </span>
              <span className="fc-faint fc-num" style={{ fontSize: 11.5 }}>
                {formatDateShort(v.effective_from)} → {v.effective_to ? formatDateShort(v.effective_to) : "open"}
              </span>
            </div>
            <div className="fc-faint mt-1" style={{ fontSize: 12 }}>
              Drafted by {v.created_by} · {formatDateTime(v.created_at)}
              {v.activated_by && v.activated_at && (
                <>
                  {" "}
                  · Activated by {v.activated_by} · {formatDateTime(v.activated_at)}
                </>
              )}
            </div>
            {(v.deductions?.length ?? 0) > 0 && (
              <div className="fc-muted mt-1" style={{ fontSize: 12 }}>
                {v.deductions!.map((d) => `${deductionLabel(d.type)} ${rateText(d.rate)}`).join(" · ")}
              </div>
            )}
          </li>
        );
      })}
      {versions.length === 0 && (
        <li className="fc-faint" style={{ fontSize: 12.5 }}>
          {plural(0, "version")}
        </li>
      )}
    </ol>
  );
}
