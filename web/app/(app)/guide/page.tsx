import Link from "next/link";
import type { ReactNode } from "react";
import {
  ArrowDown,
  ArrowLeftRight,
  ArrowRight,
  Activity,
  BookOpen,
  Landmark,
  LayoutDashboard,
  MessageSquareText,
  ShieldCheck,
  Table2,
  Target,
  TriangleAlert,
  Upload,
  type LucideIcon,
} from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/ui/panel";
import { Pill } from "@/components/ui/pill";
import { SourceGlyph } from "@/components/ui/source-glyph";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Content                                                            */
/* ------------------------------------------------------------------ */

const SOURCES: { source: string; name: string; what: string; quirk: string }[] = [
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
    quirk: "Narrations get cut at ~100 characters, often chopping the reference number.",
  },
  {
    source: "ledger",
    name: "Tally daybook",
    what: "What the accountant booked. Sales, receipts, fees, refunds, the version of events the books tell.",
    quirk: "Negatives look like (-)1,24,500.00, with Indian digit grouping.",
  },
];

const PIPELINE: { step: string; title: string; body: string; fact: string }[] = [
  {
    step: "1",
    title: "Ingest",
    body: "Read all three files, parse every bank narration for its rail and reference, normalise names, and turn everything into one common record.",
    fact: "1,575 events from 500 orders",
  },
  {
    step: "2",
    title: "Block",
    body: "Group records by amount and date so we compare only plausible pairs, not every record against every other.",
    fact: "332,520 pairs → 6,170 candidates",
  },
  {
    step: "3",
    title: "Match",
    body: "Five passes, strictest first: exact reference, fee-adjusted arithmetic, date shift, one-credit-to-many-payments, and last a fuzzy pass that only suggests.",
    fact: "100% precision on auto-close",
  },
  {
    step: "4",
    title: "Three-way",
    body: "Line up gateway, bank and books for each settlement. A match with no bank leg cannot close, the bank is the only proof money moved.",
    fact: "87 groups fully three-way",
  },
  {
    step: "5",
    title: "Apply rules",
    body: "The Rule Book explains gaps the arithmetic can't: MDR, GST on MDR, TDS, marketplace commission. A rule shrinks a gap; it never just passes it.",
    fact: "437 events rule-resolved",
  },
  {
    step: "6",
    title: "Classify & rank",
    body: "Whatever is left becomes an exception with a category, a tier, a priority and a recommended action. Similar ones cluster into one root cause.",
    fact: "48 exceptions → 11 root causes → 20 queue items",
  },
  {
    step: "7",
    title: "Cash bridge",
    body: "Gross collected minus every deduction, compared to what the bank credited. The difference is the money you need to chase.",
    fact: "₹1,02,271 at risk surfaced",
  },
];

const RULES: { title: string; body: string; tone: "ok" | "model" | "warn" }[] = [
  {
    title: "Nothing closes without evidence",
    body: "Every closed match records which stage closed it, which fields agreed, the arithmetic, and the rule version. You can open any match and see exactly why.",
    tone: "ok",
  },
  {
    title: "The AI never decides a match",
    body: "Matching, rules, tiering and the cash bridge are pure deterministic code. The AI reads, explains, drafts and answers questions. It cannot close anything.",
    tone: "model",
  },
  {
    title: "Refusing is a correct answer",
    body: "When two answers are equally valid, the system emits neither and escalates to you. A guess is the failure; an honest “I can't tell” is the feature.",
    tone: "warn",
  },
];

const TOUR: { href: string; label: string; icon: LucideIcon; see: string; try: string }[] = [
  {
    href: "/ingest",
    label: "Ingest",
    icon: Upload,
    see: "Where files come in. Each source shows how many rows were read and how many were rejected, with the reason.",
    try: "Drop in a Razorpay JSON, a bank CSV and a Tally export, or use the seeded demo data that's already there.",
  },
  {
    href: "/",
    label: "Overview",
    icon: LayoutDashboard,
    see: "The books at a glance: how much matched on its own, how much a rule explained, and how many decisions are waiting for you.",
    try: "Note the human-queue number. That, not the total record count, is your workload.",
  },
  {
    href: "/exceptions",
    label: "Exceptions",
    icon: TriangleAlert,
    see: "The ranked queue. Every row is something the system could not prove. Highest cash impact and nearest deadline sit at the top.",
    try: "Open one. Read the evidence pack, the consequence if ignored, and the recommended action. Resolve, write off, snooze or escalate.",
  },
  {
    href: "/reconcile",
    label: "Reconcile",
    icon: ArrowLeftRight,
    see: "Gross to bank, line by line. Every deduction between what customers paid and what landed in the account.",
    try: "Click any line of the bridge. It opens the exact rows and exceptions that make up that figure.",
  },
  {
    href: "/cash",
    label: "Cash",
    icon: Landmark,
    see: "Money that is at risk, held in reserve, or claimable as GST input credit. The numbers a founder actually asks for.",
    try: "Check the T+90 reserve releases. These are receivables most teams forget to chase.",
  },
  {
    href: "/rules",
    label: "Rule Book",
    icon: BookOpen,
    see: "The deduction policy as versioned rules: MDR by payment method, GST, TDS, marketplace commission, each with an effective date.",
    try: "Draft a rule and back-test it. It shows which past exceptions it would have explained before you activate it.",
  },
  {
    href: "/ask",
    label: "Ask the books",
    icon: MessageSquareText,
    see: "Plain-English questions answered from the data: “how much is at risk this week”, “which settlements are short and by how much”.",
    try: "Ask something. Then look at the SQL it ran, every number in the answer traces to a real query result.",
  },
  {
    href: "/activity",
    label: "Controller Activity",
    icon: Activity,
    see: "A timeline of what the system did on this run, and every AI call it made, with the model, the cost and the fallback used.",
    try: "Find a call that fell back to a template. The page still worked, that's the design.",
  },
  {
    href: "/audit",
    label: "Audit Trail",
    icon: ShieldCheck,
    see: "Every decision in a hash chain. Each row carries the hash of the one before it, so nothing can be edited after the fact.",
    try: "Export it as CSV. Hand that to an auditor.",
  },
  {
    href: "/eval",
    label: "Evaluation",
    icon: Target,
    see: "Precision and recall per matching stage, the coverage curve, and the four quality gates that block a release.",
    try: "Look at false_auto_resolutions. It must read 0. It does.",
  },
  {
    href: "/records",
    label: "Records",
    icon: Table2,
    see: "Every normalised row from every source, searchable. The raw material behind everything above.",
    try: "Search a UTR. See it in the bank, in Razorpay and in Tally side by side.",
  },
];

const GLOSSARY: { term: string; meaning: string }[] = [
  { term: "Settlement", meaning: "One payout from Razorpay to your bank, bundling many customer payments net of fees." },
  { term: "UTR", meaning: "Unique Transaction Reference, the ID a bank stamps on a NEFT/RTGS/IMPS transfer. The best matching key when it survives." },
  { term: "MDR", meaning: "Merchant Discount Rate, the fee the gateway charges per payment, by method (UPI, card, netbanking)." },
  { term: "GST on MDR", meaning: "18% tax on the fee. Claimable back as input credit, which is why the Cash page tracks it." },
  { term: "TDS 194-O", meaning: "Tax deducted at source by an e-commerce operator before paying a seller." },
  { term: "Rolling reserve", meaning: "A slice of each settlement the gateway holds back, typically released after 90 days." },
  { term: "Chargeback", meaning: "A customer disputes a payment and the bank claws it back. Must be booked; the system flags any that aren't." },
  { term: "NACH batch", meaning: "A single bank line covering many mandate debits. Without member detail it can't be split, so it always escalates." },
  { term: "Three-way match", meaning: "Gateway, bank and ledger all agreeing on the same money movement." },
  { term: "Exception", meaning: "Anything the system could not prove. Comes with a category, a tier, a priority and a recommended action." },
  { term: "Abstention", meaning: "The system deliberately not deciding because two answers were equally valid. Counted as a success." },
  { term: "Evidence pack", meaning: "The fields, arithmetic and rule version behind a match. Every closed match has one." },
  { term: "Dry run", meaning: "Preview any action before it happens. Every write in this app supports it." },
];

/* ------------------------------------------------------------------ */
/*  Small pieces                                                        */
/* ------------------------------------------------------------------ */

function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="text-[10.5px] font-semibold tracking-[0.08em] text-ink-3 uppercase">{children}</div>;
}

function Layer({
  name,
  role,
  chips,
  tone = "default",
}: {
  name: string;
  role: string;
  chips?: string[];
  tone?: "default" | "engine";
}) {
  return (
    <div
      className={cn(
        "rounded-[10px] border px-4 py-3",
        tone === "engine" ? "border-[rgba(61,220,151,0.3)] bg-ok-soft" : "border-line-strong bg-surface-2",
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="num text-[13px] font-semibold text-ink">{name}</div>
        <div className="text-[11.5px] text-ink-3">{role}</div>
      </div>
      {chips && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {chips.map((c) => (
            <span key={c} className="num rounded-[5px] border border-line-strong bg-surface px-1.5 py-0.5 text-[10.5px] text-ink-2">
              {c}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Down() {
  return (
    <div className="flex justify-center py-1 text-ink-4" aria-hidden>
      <ArrowDown width={14} height={14} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */

export default function GuidePage() {
  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Guide"
        sub="What this is, how it works, and how to walk through it in ten minutes. Start here if you're new."
        actions={
          <Link href="/ingest" className="btn btn-primary">
            Start the tour <ArrowRight width={13} height={13} />
          </Link>
        }
      />

      {/* ---------- What is this ---------- */}
      <Panel title="What is this?" sub="One paragraph, no jargon">
        <p className="max-w-[68ch] text-[13.5px] leading-relaxed text-ink-2">
          When a business takes payments online, three different documents describe the same money: the payment
          gateway&apos;s report, the bank statement, and the accountant&apos;s ledger. They never agree by themselves -
          fees are taken, refunds lag, references get cut off, one bank credit covers fourteen payments. Someone has
          to line them up by hand, every month.
        </p>
        <p className="mt-3 max-w-[68ch] text-[13.5px] leading-relaxed text-ink-2">
          <span className="font-semibold text-ink">This does that lining-up automatically.</span> It matches what it
          can prove, explains the gaps it can account for, and hands you a short, ranked list of the decisions only
          a person can make, each one with the evidence attached.
        </p>

        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {SOURCES.map((s) => (
            <div key={s.source} className="rounded-[10px] border border-line bg-surface-2 p-4">
              <div className="flex items-center gap-2.5">
                <SourceGlyph source={s.source} size={26} />
                <div className="text-[12.5px] font-semibold text-ink">{s.name}</div>
              </div>
              <p className="mt-2.5 text-[12px] leading-relaxed text-ink-2">{s.what}</p>
              <p className="mt-2 text-[11.5px] leading-relaxed text-ink-3">
                <span className="text-warn">Quirk:</span> {s.quirk}
              </p>
            </div>
          ))}
        </div>
      </Panel>

      {/* ---------- Three rules ---------- */}
      <div className="grid gap-3 md:grid-cols-3">
        {RULES.map((r) => (
          <div key={r.title} className="panel px-[18px] py-4">
            <Pill tone={r.tone} dot>
              {r.tone === "ok" ? "evidence" : r.tone === "model" ? "ai boundary" : "abstention"}
            </Pill>
            <div className="mt-2.5 text-[13.5px] font-semibold text-ink">{r.title}</div>
            <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">{r.body}</p>
          </div>
        ))}
      </div>

      {/* ---------- Architecture ---------- */}
      <Panel title="Architecture" sub="Four layers, one direction of dependency. The AI sits beside the engine, never inside it.">
        <div className="grid gap-5 lg:grid-cols-[1fr_300px]">
          <div>
            <Layer name="web/" role="The dashboard you're looking at" chips={["Next.js 15", "React 19", "typed client generated from the API"]} />
            <Down />
            <Layer name="api/" role="Validates, calls the engine, serialises. No business logic." chips={["FastAPI", "78 endpoints", "dry_run on every write", "per-tenant scoping"]} />
            <Down />
            <Layer
              name="engine/"
              tone="engine"
              role="Pure logic. No database, no network, no clock inside."
              chips={["ingest", "matching", "rules", "exceptions", "cash", "audit", "agent", "llm"]}
            />
            <Down />
            <Layer name="db/" role="Postgres. Enforces what code can't." chips={["13 tables", "row-level security", "immutable rules trigger", "append-only audit"]} />
          </div>

          <div className="flex flex-col gap-3">
            <div className="panel-model rounded-[10px] px-4 py-3">
              <Eyebrow>Where the AI sits</Eyebrow>
              <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
                <span className="text-model">engine/llm</span> is one module among eight. The matching, rules, tiering
                and cash modules cannot import it, a build check fails if they try. With every model provider down,
                reconciliation still runs and every number still computes. Only the prose gets worse.
              </p>
            </div>
            <div className="rounded-[10px] border border-line bg-surface-2 px-4 py-3">
              <Eyebrow>Why engine/ is pure</Eyebrow>
              <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
                Same input always gives the same output, byte for byte. That&apos;s what makes a replay against a new
                rule meaningful and an audit trail reproducible.
              </p>
            </div>
            <div className="rounded-[10px] border border-line bg-surface-2 px-4 py-3">
              <Eyebrow>What the database enforces</Eyebrow>
              <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
                Tenants can&apos;t see each other. An active rule can&apos;t be edited, only versioned. The audit log
                can&apos;t be updated or deleted. These are grants and triggers, not conventions.
              </p>
            </div>
          </div>
        </div>
      </Panel>

      {/* ---------- Pipeline ---------- */}
      <Panel title="How a reconciliation runs" sub="Seven steps, in order. Numbers are from the seeded demo run." flush>
        <ol className="divide-y divide-line">
          {PIPELINE.map((p) => (
            <li key={p.step} className="grid gap-x-5 gap-y-1 px-[18px] py-3.5 md:grid-cols-[28px_140px_1fr_auto] md:items-baseline">
              <span className="num text-[12px] font-semibold text-ink-4">{p.step}</span>
              <span className="text-[13px] font-semibold text-ink">{p.title}</span>
              <p className="text-[12.5px] leading-relaxed text-ink-2">{p.body}</p>
              <span className="num text-[11.5px] whitespace-nowrap text-ok md:text-right">{p.fact}</span>
            </li>
          ))}
        </ol>
      </Panel>

      {/* ---------- Tour ---------- */}
      <Panel title="Walk through the product" sub="Follow the sidebar top to bottom. Each stop: what you'll see, and one thing to try.">
        <ol className="grid gap-3 md:grid-cols-2">
          {TOUR.map((t, i) => {
            const Icon = t.icon;
            return (
              <li key={t.href} className="panel-link group flex gap-3.5 rounded-[10px] border border-line bg-surface-2 p-4">
                <span className="num mt-0.5 w-5 shrink-0 text-right text-[12px] font-semibold text-ink-4">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <Link href={t.href} className="inline-flex items-center gap-2 text-[13px] font-semibold text-ink hover:underline">
                    <Icon width={14} height={14} className="text-ink-3" />
                    {t.label}
                    <ArrowRight width={12} height={12} className="text-ink-4 transition-transform group-hover:translate-x-0.5" />
                  </Link>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">{t.see}</p>
                  <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-3">
                    <span className="text-accent">Try:</span> {t.try}
                  </p>
                </div>
              </li>
            );
          })}
        </ol>
      </Panel>

      {/* ---------- Glossary ---------- */}
      <Panel title="Words you'll see" sub="Finance terms used across the screens" flush>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th w-[180px] pl-[18px]">Term</th>
                <th className="th pr-[18px]">Meaning</th>
              </tr>
            </thead>
            <tbody>
              {GLOSSARY.map((g) => (
                <tr key={g.term} className="text-[12.5px]">
                  <td className="td pl-[18px] font-medium whitespace-nowrap text-ink">{g.term}</td>
                  <td className="td pr-[18px] text-ink-2">{g.meaning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
