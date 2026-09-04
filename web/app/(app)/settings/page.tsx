"use client";

// Settings. One thing to configure (the run-complete email) and one card
// that says what this build is and what it will never do.

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Mail, Send } from "lucide-react";
import { useCurrentRun, useSettings, useWrite, writes, type S } from "../_lib/api";
import { hashShort, plural } from "../_lib/format";
import { Button, Card, CardHeader, Divider, ErrorNote, KeyValue, Page, PageHeader, Pill, Reveal, Skeleton } from "../_components/ui";
import { Switch } from "./switch";

type SendSummaryOut = S["SendSummaryOut"];

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** "2 Sep, 14:03" — day without a leading zero, as the brief shows it. */
function lastSent(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

const THESIS = [
  "The model never decides whether something is reconciled. Matching, rules, tiers and cash are deterministic code, and every model output is checked by that code before it touches state.",
];

export default function SettingsPage() {
  const settings = useSettings();
  const { run } = useCurrentRun();

  const [on, setOn] = useState(false);
  const [email, setEmail] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [sent, setSent] = useState<SendSummaryOut | null>(null);

  useEffect(() => {
    if (!settings.data || dirty) return;
    setOn(settings.data.email_on_run_complete);
    setEmail(settings.data.notify_email ?? "");
  }, [settings.data, dirty]);

  const save = useWrite((body: { email_on_run_complete: boolean; notify_email: string | null }) => writes.updateSettings(body));
  const send = useWrite(() => writes.sendSummary());

  useEffect(() => {
    if (!saved) return;
    const t = setTimeout(() => setSaved(false), 2400);
    return () => clearTimeout(t);
  }, [saved]);

  const configured = settings.data?.email_configured ?? false;

  return (
    <Page className="max-w-[960px]">
      <PageHeader title="Settings" />

      <Reveal>
        <Card className="mb-5">
          <CardHeader
            title="Email me when a run finishes"
            sub="One message per run, with the verdict, the unexplained amount and the decisions waiting on you."
            right={
              settings.data && (
                <Pill tone={configured ? "ok" : "warn"} dot>
                  {configured ? "Provider configured" : "No provider"}
                </Pill>
              )
            }
          />
          <div className="px-5 pb-5">
            {settings.isPending ? (
              <Skeleton lines={3} />
            ) : settings.error ? (
              <ErrorNote message={settings.error.message} />
            ) : (
              <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between gap-4">
                  <label htmlFor="email-on-complete" className="text-[13px]">
                    Send the summary automatically
                  </label>
                  <Switch
                    id="email-on-complete"
                    checked={on}
                    label="Email me when a run finishes"
                    onChange={(v) => {
                      setOn(v);
                      setDirty(true);
                    }}
                  />
                </div>

                <div className="flex items-center gap-2">
                  <div className="relative flex-1">
                    <Mail size={14} className="app-faint pointer-events-none absolute left-3 top-1/2 -translate-y-1/2" />
                    <input
                      type="email"
                      className="app-input !pl-9"
                      placeholder="finance@yourcompany.in"
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        setDirty(true);
                      }}
                      aria-label="Notification email"
                    />
                  </div>
                  <Button
                    variant="primary"
                    loading={save.isPending}
                    disabled={!dirty}
                    onClick={() =>
                      save.mutate(
                        { email_on_run_complete: on, notify_email: email.trim() || null },
                        {
                          onSuccess: () => {
                            setDirty(false);
                            setSaved(true);
                          },
                        },
                      )
                    }
                  >
                    Save
                  </Button>
                </div>
                <AnimatePresence>
                  {save.error && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                      <ErrorNote message={save.error.message} />
                    </motion.div>
                  )}
                  {saved && (
                    <motion.div
                      key="saved"
                      initial={{ opacity: 0, y: -4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      className="text-[12.5px] text-[var(--app-ok)]"
                    >
                      Saved.
                    </motion.div>
                  )}
                </AnimatePresence>

                <Divider />

                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-col gap-0.5">
                    <div className="text-[13px]">Send this run&apos;s summary now</div>
                    <div className="app-faint text-[12px]">
                      {settings.data.email_last_sent_at ? (
                        <>Last sent {lastSent(settings.data.email_last_sent_at)}</>
                      ) : (
                        <>Never sent</>
                      )}
                      {!configured && <> · No email provider configured on the server</>}
                    </div>
                  </div>
                  <Button
                    loading={send.isPending}
                    disabled={!configured}
                    title={configured ? undefined : "No email provider configured on the server"}
                    onClick={() => {
                      setSent(null);
                      send.mutate(undefined, { onSuccess: (out) => setSent(out) });
                    }}
                  >
                    <Send size={13} />
                    Send now
                  </Button>
                </div>

                <AnimatePresence>
                  {send.error && (
                    <motion.div key="send-err" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                      <ErrorNote message={send.error.message} />
                    </motion.div>
                  )}
                  {sent && (
                    <motion.div
                      key="sent"
                      initial={{ opacity: 0, y: 6 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.3, ease: [0.2, 0.8, 0.2, 1] }}
                      className={
                        sent.sent
                          ? "rounded-lg border border-[var(--app-ok-line)] bg-[var(--app-ok-soft)] px-3 py-2.5"
                          : "rounded-lg border border-[var(--app-warn-line)] bg-[var(--app-warn-soft)] px-3 py-2.5"
                      }
                    >
                      {sent.sent ? (
                        <>
                          <div className="text-[13px] text-[var(--app-ok)]">
                            Sent to {sent.recipients.length > 0 ? sent.recipients.join(", ") : plural(0, "recipient")}.
                          </div>
                          <div className="app-muted mt-1 text-[12.5px]">{sent.headline}</div>
                        </>
                      ) : (
                        <>
                          <div className="text-[13px] text-[var(--app-warn)]">Not sent{sent.reason ? `: ${sent.reason}` : "."}</div>
                          {sent.headline && <div className="app-muted mt-1 text-[12.5px]">{sent.headline}</div>}
                        </>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )}
          </div>
        </Card>
      </Reveal>

      <Reveal delay={0.08}>
        <Card>
          <CardHeader title="About this build" sub="What the controller is, and what it will never do." />
          <div className="flex flex-col gap-5 px-5 pb-5">
            <KeyValue
              rows={[
                ["Ruleset in force", run ? <span className="mono" title={run.ruleset_hash}>{hashShort(run.ruleset_hash, 16)}</span> : <span className="app-faint">No run loaded</span>],
                ["Current run", run ? <span className="mono" title={run.run_id}>{run.run_id}</span> : <span className="app-faint">—</span>],
                ["API", <span key="api" className="mono">{API_BASE}</span>],
              ]}
            />
            <Divider />
            <ol className="flex flex-col gap-3">
              {THESIS.map((t, i) => (
                <li key={i} className="flex gap-3">
                  <p className="app-muted text-[13px] leading-relaxed">
                    <span className="text-[var(--app-ink)]">{t.slice(0, t.indexOf(".") + 1)}</span>
                    {t.slice(t.indexOf(".") + 1)}
                  </p>
                </li>
              ))}
            </ol>
          </div>
        </Card>
      </Reveal>
    </Page>
  );
}
