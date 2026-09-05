"use client";

// Guide. What this product is, how it is built, and how to walk through it.
// Static by design: nothing here is a live figure, every number is quoted
// from the seeded demo run and labelled as such, so a newcomer reads it
// before any data exists.

import Link from "next/link";
import type { ReactNode } from "react";
import {
  Activity,
  ArrowDown,
  ArrowRight,
  Database,
  Gavel,
  LayoutDashboard,
  Play,
  Scale,
  ShieldCheck,
  Target,
  Wallet,
  BookOpen,
  ArrowLeftRight,
  type LucideIcon,
} from "lucide-react";
import { Button, Card, CardHeader, Eyebrow, Page, PageHeader, Pill, SourceMark } from "../_components/ui";

const SOURCES: { source: "razorpay" | "bank" | "ledger"; name: string; what: string; quirk: string }[] = [
  {
    source: "razorpay",
    name: "Razorpay settlement report",
    what: "What the payment gateway says it collected from customers, what fees it took, and what it sent to your bank.",
    quirk: "Amounts arrive in paise. One settlement bundles many payments.",
  },
  {
    source: "bank",
    name: "Bank statement",
    what: "What actually landed in the account. The only source that proves money moved.",
    quirk: "Narrations get cut at about 100 characters, often chopping the reference number.",
  },
  {
    source: "ledger",
    name: "Tally daybook",
    what: "What the accountant booked. Sales, receipts, fees, refunds: the version of events the books tell.",
    quirk: "Negatives look like (-)1,24,500.00, with Indian digit grouping.",
  },
];

const PIPELINE: { title: string; body: string; fact: string }[] = [
  {
    title: "Ingest",
    body: "Read all three files, parse every bank narration for its rail and reference, normalise names, and turn everything into one common record.",
    fact: "1,575 events from 500 orders",
  },
  {
    title: "Block",
    body: "Group records by amount and date so only plausible pairs are compared, not every record against every other.",
    fact: "332,520 pairs to 6,170 candidates",
  },
  {
    title: "Match",
    body: "Five passes, strictest first: exact reference, fee-adjusted arithmetic, date shift, one credit to many payments, and last a fuzzy pass that only suggests.",
    fact: "100% precision on auto-close",
  },
  {
    title: "Three-way",
    body: "Line up gateway, bank and books for each settlement. A match with no bank leg cannot close; the bank is the only proof money moved.",
    fact: "87 groups fully three-way",
  },
  {
    title: "Apply rules",
    body: "The Rule Book explains gaps the arithmetic cannot: MDR, GST on MDR, TDS, marketplace commission. A rule shrinks a gap; it never just passes it.",
    fact: "437 events rule-resolved",
  },
  {
    title: "Classify and rank",
    body: "Whatever is left becomes a decision with a category, a tier, a priority and a recommended action. Similar ones cluster into one root cause.",
    fact: "48 exceptions, 11 root causes, 20 queue items",
  },
  {
    title: "Cash bridge",
    body: "Gross collected minus every deduction, compared to what the bank credited. The difference is the money you need to chase.",
    fact: "Rs 1,02,271 at risk surfaced",
  },
];

const RULES: { title: string; body: string; tone: "ok" | "model" | "warn"; label: string }[] = [
  {
    label: "evidence",
    title: "Nothing closes without evidence",
    body: "Every closed match records which stage closed it, which fields agreed, the arithmetic, and the rule version. Open any match and see exactly why.",
    tone: "ok",
  },
  {
    label: "ai boundary",
    title: "The AI never decides a match",
    body: "Matching, rules, tiering and the cash bridge are deterministic code. The AI reads, explains, drafts and answers questions. It cannot close anything.",
    tone: "model",
  },
  {
    label: "abstention",
    title: "Refusing is a correct answer",
    body: "When two answers are equally valid, the system emits neither and escalates to you. A guess is the failure; an honest refusal is the feature.",
    tone: "warn",
  },
];

const TOUR: { href: string; label: string; icon: LucideIcon; see: string; try: string }[] = [
  {
    href: "/run",
    label: "Run",
    icon: Play,
    see: "Where files come in and a reconciliation starts. Each source shows how many rows were read and how many were rejected, with the reason.",
    try: "Upload a Razorpay JSON, a bank CSV and a Tally export, or run the seeded demo data that is already there.",
  },
  {
    href: "/overview",
    label: "Overview",
    icon: LayoutDashboard,
    see: "The books at a glance: how much matched on its own, how much a rule explained, and how many decisions are waiting for you.",
    try: "Note the decisions count. That, not the total record count, is your workload.",
  },
  {
    href: "/decisions",
    label: "Decisions",
    icon: Gavel,
    see: "The ranked queue. Every card is something the system could not prove. Highest cash impact and nearest deadline sit at the top.",
    try: "Open one. Read the evidence, the consequence if ignored, and the recommended action. Resolve, write off, snooze or escalate.",
  },
  {
    href: "/settlements",
    label: "Settlements",
    icon: ArrowLeftRight,
    see: "Every settlement as a register: what Razorpay reported, what the bank credited, what the books say, and where each one stands.",
    try: "Pick a settlement that did not fully close and follow it into Decisions.",
  },
  {
    href: "/reconcile",
    label: "Reconcile",
    icon: Scale,
    see: "Gross to bank, line by line. Every deduction between what customers paid and what landed in the account.",
    try: "Click any line of the bridge. It opens the exact rows and decisions that make up that figure.",
  },
  {
    href: "/cash",
    label: "Cash",
    icon: Wallet,
    see: "Money that is at risk, held in reserve, or claimable as GST input credit. The numbers a founder actually asks for.",
    try: "Check the T+90 reserve releases. These are receivables most teams forget to chase.",
  },
  {
    href: "/rules",
    label: "Rule Book",
    icon: BookOpen,
    see: "The deduction policy as versioned rules: MDR by payment method, GST, TDS, marketplace commission, each with an effective date.",
    try: "Draft a rule and back-test it. It shows which past decisions it would have explained before you activate it.",
  },
  {
    href: "/controller-activity",
    label: "Controller Activity",
    icon: Activity,
    see: "A timeline of what the engine did on this run, and every AI call it made, with the model, the cost and the fallback used.",
    try: "Find a call that fell back to a template. The page still worked; that is the design.",
  },
  {
    href: "/audit",
    label: "Audit Trail",
    icon: ShieldCheck,
    see: "Every decision in a hash chain. Each row carries the hash of the one before it, so nothing can be edited after the fact.",
    try: "Export it as CSV. Hand that to an auditor.",
  },
  {
    href: "/evaluation",
    label: "Evaluation",
    icon: Target,
    see: "Precision and recall per matching stage, the coverage curve, and the four quality gates that block a release.",
    try: "Look at false_auto_resolutions. It must read 0. It does.",
  },
  {
    href: "/records",
    label: "Records",
    icon: Database,
    see: "Every normalised row from every source, searchable. The raw material behind everything above.",
    try: "Search a UTR. See it in the bank, in Razorpay and in Tally side by side.",
  },
];

const GLOSSARY: { term: string; meaning: string }[] = [
  { term: "Settlement", meaning: "One payout from Razorpay to your bank, bundling many customer payments net of fees." },
  { term: "UTR", meaning: "Unique Transaction Reference, the id a bank stamps on a NEFT, RTGS or IMPS transfer. The best matching key when it survives." },
  { term: "MDR", meaning: "Merchant Discount Rate, the fee the gateway charges per payment, by method (UPI, card, netbanking)." },
  { term: "GST on MDR", meaning: "18% tax on the fee. Claimable back as input credit, which is why the Cash screen tracks it." },
  { term: "TDS 194-O", meaning: "Tax deducted at source by an e-commerce operator before paying a seller." },
  { term: "Rolling reserve", meaning: "A slice of each settlement the gateway holds back, typically released after 90 days." },
  { term: "Chargeback", meaning: "A customer disputes a payment and the bank claws it back. Must be booked; the system flags any that are not." },
  { term: "NACH batch", meaning: "A single bank line covering many mandate debits. Without member detail it cannot be split, so it always escalates." },
  { term: "Three-way match", meaning: "Gateway, bank and ledger all agreeing on the same money movement." },
  { term: "Decision", meaning: "Anything the system could not prove. Comes with a category, a tier, a priority and a recommended action." },
  { term: "Abstention", meaning: "The system deliberately not deciding because two answers were equally valid. Counted as a success." },
  { term: "Evidence", meaning: "The fields, arithmetic and rule version behind a match. Every closed match has it." },
  { term: "Dry run", meaning: "Preview any action before it happens. Every write in this app supports it." },
];

function Layer({ name, role, chips, accent }: { name: string; role: string; chips: string[]; accent?: boolean }) {
  return (
    <div
      className="rounded-[10px] px-4 py-3"
      style={{
        border: `1px solid ${accent ? "var(--app-ok-line)" : "var(--app-line)"}`,
        background: accent ? "var(--app-ok-soft)" : "var(--app-surface)",
      }}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <span className="mono text-[13px] font-semibold">{name}</span>
        <span className="app-faint text-[11.5px]">{role}</span>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        {chips.map((c) => (
          <span key={c} className="mono rounded-[5px] px-1.5 py-0.5 text-[10.5px]" style={{ border: "1px solid var(--app-line)", background: "var(--app-bg)" }}>
            {c}
          </span>
        ))}
      </div>
    </div>
  );
}

function Down() {
  return (
    <div className="app-faint flex justify-center py-1" aria-hidden>
      <ArrowDown size={14} />
    </div>
  );
}

function Note({ title, children, model }: { title: string; children: ReactNode; model?: boolean }) {
  return (
    <div
      className="rounded-[10px] px-4 py-3"
      style={{ border: `1px solid ${model ? "var(--app-model-line)" : "var(--app-line)"}`, background: model ? "var(--app-model-soft)" : "var(--app-surface)" }}
    >
      <Eyebrow>{title}</Eyebrow>
      <p className="app-muted mt-1.5 text-[12px] leading-relaxed">{children}</p>
    </div>
  );
}

export default function GuidePage() {
  return (
    <Page>
      <PageHeader
        title="Guide"
        question="What this is, how it works, and how to walk through it in ten minutes. Start here if you are new."
        actions={
          <Link href="/run">
            <Button variant="primary">
              Start the tour <ArrowRight size={13} />
            </Button>
          </Link>
        }
      />

      <Card className="mb-5">
        <CardHeader title="What is this?" sub="One paragraph, no jargon" />
        <div className="px-5 pb-5">
          <p className="max-w-[68ch] text-[13.5px] leading-relaxed">
            When a business takes payments online, three different documents describe the same money: the payment
            gateway&apos;s report, the bank statement, and the accountant&apos;s ledger. They never agree by themselves.
            Fees are taken, refunds lag, references get cut off, one bank credit covers fourteen payments. Someone has
            to line them up by hand, every month.
          </p>
          <p className="mt-3 max-w-[68ch] text-[13.5px] leading-relaxed">
            <strong>This does that lining-up automatically.</strong> It matches what it can prove, explains the gaps it
            can account for, and hands you a short, ranked list of the decisions only a person can make, each one with
            the evidence attached.
          </p>
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            {SOURCES.map((s) => (
              <div key={s.source} className="rounded-[10px] p-4" style={{ border: "1px solid var(--app-line)", background: "var(--app-surface)" }}>
                <SourceMark source={s.source} />
                <div className="mt-1.5 text-[12.5px] font-semibold">{s.name}</div>
                <p className="app-muted mt-2 text-[12px] leading-relaxed">{s.what}</p>
                <p className="app-faint mt-2 text-[11.5px] leading-relaxed">
                  <span style={{ color: "var(--app-warn)" }}>Quirk:</span> {s.quirk}
                </p>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <div className="mb-5 grid gap-3 md:grid-cols-3">
        {RULES.map((r) => (
          <Card key={r.title} className="px-5 py-4">
            <Pill tone={r.tone} dot>
              {r.label}
            </Pill>
            <div className="mt-2.5 text-[13.5px] font-semibold">{r.title}</div>
            <p className="app-muted mt-1.5 text-[12px] leading-relaxed">{r.body}</p>
          </Card>
        ))}
      </div>

      <Card className="mb-5">
        <CardHeader title="Architecture" sub="Four layers, one direction of dependency. The AI sits beside the engine, never inside it." />
        <div className="grid gap-5 px-5 pb-5 lg:grid-cols-[1fr_300px]">
          <div>
            <Layer name="web/" role="The dashboard you are looking at" chips={["Next.js 15", "React 19", "typed client generated from the API"]} />
            <Down />
            <Layer name="api/" role="Validates, calls the engine, serialises. No business logic." chips={["FastAPI", "78 endpoints", "dry_run on every write", "per-tenant scoping"]} />
            <Down />
            <Layer name="engine/" accent role="Pure logic. No database, no network, no clock inside." chips={["ingest", "matching", "rules", "exceptions", "cash", "audit", "agent", "llm"]} />
            <Down />
            <Layer name="db/" role="Postgres. Enforces what code cannot." chips={["13 tables", "row-level security", "immutable rules trigger", "append-only audit"]} />
          </div>
          <div className="flex flex-col gap-3">
            <Note title="Where the AI sits" model>
              engine/llm is one module among eight. The matching, rules, tiering and cash modules cannot import it; a
              build check fails if they try. With every model provider down, reconciliation still runs and every number
              still computes. Only the prose gets worse.
            </Note>
            <Note title="Why engine/ is pure">
              Same input always gives the same output, byte for byte. That is what makes a replay against a new rule
              meaningful and an audit trail reproducible.
            </Note>
            <Note title="What the database enforces">
              Tenants cannot see each other. An active rule cannot be edited, only versioned. The audit log cannot be
              updated or deleted. These are grants and triggers, not conventions.
            </Note>
          </div>
        </div>
      </Card>

      <Card className="mb-5">
        <CardHeader title="How a reconciliation runs" sub="Seven steps, in order. Numbers are from the seeded demo run." />
        <ol className="px-5 pb-2">
          {PIPELINE.map((p, i) => (
            <li
              key={p.title}
              className="grid gap-x-5 gap-y-1 py-3.5 md:grid-cols-[28px_150px_1fr_auto] md:items-baseline"
              style={{ borderTop: i === 0 ? "none" : "1px solid var(--app-line)" }}
            >
              <span className="mono app-faint text-[12px] font-semibold">{i + 1}</span>
              <span className="text-[13px] font-semibold">{p.title}</span>
              <p className="app-muted text-[12.5px] leading-relaxed">{p.body}</p>
              <span className="mono text-[11.5px] whitespace-nowrap md:text-right" style={{ color: "var(--app-ok)" }}>
                {p.fact}
              </span>
            </li>
          ))}
        </ol>
      </Card>

      <Card className="mb-5">
        <CardHeader title="Walk through the product" sub="Follow the sidebar top to bottom. Each stop: what you will see, and one thing to try." />
        <ol className="grid gap-3 px-5 pb-5 md:grid-cols-2">
          {TOUR.map((t, i) => {
            const Icon = t.icon;
            return (
              <li key={t.href} className="flex gap-3.5 rounded-[10px] p-4" style={{ border: "1px solid var(--app-line)", background: "var(--app-surface)" }}>
                <span className="mono app-faint mt-0.5 w-5 shrink-0 text-right text-[12px] font-semibold">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <Link href={t.href} className="inline-flex items-center gap-2 text-[13px] font-semibold hover:underline">
                    <Icon size={14} className="app-faint" />
                    {t.label}
                    <ArrowRight size={12} className="app-faint" />
                  </Link>
                  <p className="app-muted mt-1.5 text-[12px] leading-relaxed">{t.see}</p>
                  <p className="app-faint mt-1.5 text-[11.5px] leading-relaxed">
                    <span style={{ color: "var(--app-brand)" }}>Try:</span> {t.try}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
        <div className="px-5 pb-5">
          <div className="rounded-[10px] px-4 py-3" style={{ border: "1px solid var(--app-model-line)", background: "var(--app-model-soft)" }}>
            <Eyebrow>Ask the books</Eyebrow>
            <p className="app-muted mt-1.5 text-[12px] leading-relaxed">
              The assistant in the top bar answers plain-English questions from the data: how much is at risk this
              week, which settlements are short and by how much. It shows the SQL it ran, and every number in the
              answer traces to a real query result. A run summary can also be emailed automatically when a run
              completes; switch that on in Settings.
            </p>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="Words you will see" sub="Finance terms used across the screens" />
        <div className="overflow-x-auto px-5 pb-5">
          <table className="app-table w-full">
            <thead>
              <tr>
                <th className="w-[180px]">Term</th>
                <th>Meaning</th>
              </tr>
            </thead>
            <tbody>
              {GLOSSARY.map((g) => (
                <tr key={g.term}>
                  <td className="font-medium whitespace-nowrap">{g.term}</td>
                  <td className="app-muted">{g.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </Page>
  );
}
