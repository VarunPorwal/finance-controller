import Link from "next/link";
import type { Metadata } from "next";
import { ArrowDown, ArrowRight, GitBranch, Lock, ShieldCheck, Sparkles } from "lucide-react";
import { HeroField } from "@/components/marketing/hero-field";
import { LiquidCta } from "@/components/marketing/liquid-cta";
import { SourcesDiagram } from "@/components/marketing/sources-diagram";
import { LiveBridge, LiveGates, LiveProof, LiveStats } from "@/components/marketing/live";
import { Reveal } from "@/components/marketing/reveal";
import { CardSpotlight } from "@/components/marketing/card-spotlight";
import type { CSSProperties } from "react";

const cascadeStyle = (i: number) => ({ "--i": i }) as CSSProperties;

export const metadata: Metadata = {
  title: "Finco — close the books on proof, not confidence",
};

function Brand() {
  return (
    <Link href="/landing" className="flex items-center gap-2.5">
      <span className="flex h-7 w-7 items-center justify-center rounded-[8px] border border-[rgba(255,255,255,0.12)] bg-[rgba(255,255,255,0.04)]">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden>
          <path d="M3.5 4.2 8 8m-4.5 3.8L8 8m5-0.2L8 8" stroke="#6d7686" strokeWidth="1.2" strokeLinecap="round" />
          <circle cx="3.5" cy="4.2" r="1.7" fill="#6ea8ff" />
          <circle cx="3.5" cy="11.8" r="1.7" fill="#f49ac1" />
          <circle cx="13" cy="7.8" r="1.7" fill="#d6dce6" />
          <circle cx="8" cy="8" r="2" fill="#3ddc97" />
        </svg>
      </span>
      <span className="text-[14px] font-semibold tracking-[-0.01em]">Finco</span>
    </Link>
  );
}

export default function LandingPage() {
  return (
    <main>
      <CardSpotlight />
      <header className="fixed inset-x-0 top-0 z-30 border-b border-[rgba(255,255,255,0.06)] bg-[rgba(5,6,10,0.6)] backdrop-blur-md">
        <div className="mx-auto flex h-[60px] max-w-[1200px] items-center justify-between px-6">
          <Brand />
          <nav className="hidden items-center gap-7 text-[13.5px] text-ink-2 md:flex">
            <a href="#sources" className="hover:text-ink">
              Sources
            </a>
            <a href="#bridge" className="hover:text-ink">
              The bridge
            </a>
            <a href="#evidence" className="hover:text-ink">
              Evidence
            </a>
            <a href="#rules" className="hover:text-ink">
              Rules
            </a>
            <a href="#gates" className="hover:text-ink">
              Gates
            </a>
          </nav>
          <Link href="/app1" className="btn btn-primary h-[34px] rounded-full px-4">
            Open the controller
            <ArrowRight width={13} height={13} />
          </Link>
        </div>
      </header>

      <section className="relative flex min-h-[100vh] items-center overflow-hidden">
        <HeroField />
        <div className="relative mx-auto w-full max-w-[1200px] px-6 pt-24 pb-14">
          <Reveal className="max-w-[820px]">
            <span className="m-eyebrow">
              <span className="m-live flex h-5 items-center rounded-full bg-ok-soft px-2 text-[11.5px] font-semibold tracking-[0.06em] text-ok uppercase">
                Live
              </span>
              Razorpay · bank statements · Tally, reconciled three ways
            </span>
            <h1 className="m-h1 mt-5">
              Close the books on proof,
              <br />
              not confidence.
            </h1>
            <p className="mt-5 max-w-[640px] text-[18px] leading-relaxed text-ink-2">
              Finco reconciles Razorpay settlements, bank statements and Tally ledgers. It resolves what it can prove, refuses to close what it
              cannot, and hands you a ranked queue of the decisions only a human can make.
            </p>
            <div className="mt-7 flex flex-wrap items-center gap-4">
              <LiquidCta href="/app1" label="Open the controller" />
              <a href="#bridge" className="m-ghost">
                See how it proves it
                <ArrowDown width={14} height={14} />
              </a>
            </div>
          </Reveal>
          <Reveal delay={0.1} className="mt-10">
            <LiveStats />
            <p className="mt-2 text-[12.5px] text-ink-3">Figures are read from the current run, not typed in. The model never touches them.</p>
          </Reveal>
        </div>
      </section>

      <section id="sources" className="m-section">
        <div className="mx-auto max-w-[1200px] px-6">
          <Reveal className="max-w-[640px]">
            <div className="m-label text-accent">Three sources, one bridge</div>
            <h2 className="m-section-title mt-3">A five-stage cascade, and a rule for what it may not do.</h2>
            <p className="mt-4 text-[16px] leading-relaxed text-ink-2">
              Exact reference, fee-adjusted, date-shift, subset-sum, fuzzy. Each stage only claims what it can show, field by field. A fuzzy
              match caps at 0.75 and never auto-closes. When several answers are valid the engine abstains and files an exception instead of
              guessing. A group is only as provable as its weakest leg, and only the bank proves money moved.
            </p>
          </Reveal>
          <Reveal delay={0.1} className="m-card mt-10 px-6 py-8 md:px-10">
            <SourcesDiagram />
          </Reveal>
          <Reveal className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
            {[
              {
                title: "Money is integer paise",
                body: "No floats anywhere near a rupee. Decimal for intermediate arithmetic, integer paise for storage, enforced by a scan of the source tree.",
              },
              {
                title: "The model never decides",
                body: "Matching, rules, tiering and cash never import the LLM. CI enforces it. Anything a model wrote is shown in violet, so you always know.",
              },
              {
                title: "Abstention is a result",
                body: "Ambiguous, duplicate, chargeback and batch cases escalate regardless of confidence. Coverage is never bought with a guess.",
              },
            ].map((c, i) => (
              <div key={c.title} className="cascade m-card px-5 py-5" style={cascadeStyle(i)}>
                <div className="text-[15px] font-semibold text-ink">{c.title}</div>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">{c.body}</p>
              </div>
            ))}
          </Reveal>
        </div>
      </section>

      <section id="bridge" className="m-section border-t border-[rgba(255,255,255,0.05)]">
        <div className="mx-auto grid max-w-[1250px] grid-cols-1 gap-12 px-6 lg:grid-cols-[1.6fr_1fr] lg:items-center">
          <Reveal>
            <div className="m-label text-accent">The bridge, live</div>
            <h2 className="m-section-title mt-3">
              The thing a finance
              <br />
              person draws by hand
              <br />
              when explaining a
              <br />
              settlement.
            </h2>
            <p className="mt-4 text-[16px] leading-relaxed text-ink-2">
              Gross collected, each deduction taken off it by a versioned rule, the expected net, what the bank actually credited, and the
              residual. In the product every line is hoverable and the gap is clickable: it filters the queue to exactly the exceptions that
              carry it.
            </p>
            <p className="mt-3 text-[13.5px] text-ink-3">
              A rule shrinks an exception. It never passes or fails one. &ldquo;₹3,240 unexplained after rule X applied&rdquo;, not &ldquo;₹19,000 mismatch&rdquo;.
            </p>
            <Link href="/reconcile" className="mt-6 inline-flex items-center gap-1.5 text-[14px] text-accent hover:underline">
              Open the reconciliation <ArrowRight width={13} height={13} />
            </Link>
          </Reveal>
          <Reveal delay={0.1}>
            <LiveBridge />
          </Reveal>
        </div>
      </section>

      <section id="evidence" className="m-section border-t border-[rgba(255,255,255,0.05)]">
        <div className="mx-auto grid max-w-[1200px] grid-cols-1 gap-12 px-6 lg:grid-cols-[1.2fr_1fr] lg:items-center">
          <Reveal>
            <LiveProof />
          </Reveal>
          <Reveal delay={0.1}>
            <div className="m-label text-accent">Nothing closes without evidence</div>
            <h2 className="m-section-title mt-3">Every decision carries its proof tree.</h2>
            <p className="mt-4 text-[16px] leading-relaxed text-ink-2">
              Stage attempted, fields agreed and disagreed, the confidence derivation, the rules considered and what each explained, down to the
              raw source row. A reviewer can re-derive any auto-close by hand. Empty evidence is a bug, not a state.
            </p>
            <ul className="mt-5 flex flex-col gap-2.5 text-[13.5px] text-ink-2">
              {[
                "Tell the agent what an exception is, in a sentence. It shows what it would do and waits.",
                "Over ₹50,000 you type the amount. Closing a chargeback without a dispute reference needs an acknowledgement.",
                "If the order you named does not exist, it lists the near matches and declines to pick one for you.",
              ].map((t, i) => (
                <li key={t} className="cascade flex gap-2.5" style={cascadeStyle(i)}>
                  <ShieldCheck width={14} height={14} className="mt-0.5 shrink-0 text-ok" />
                  {t}
                </li>
              ))}
            </ul>
          </Reveal>
        </div>
      </section>

      <section id="rules" className="m-section border-t border-[rgba(255,255,255,0.05)]">
        <div className="mx-auto max-w-[1200px] px-6">
          <Reveal className="max-w-[640px]">
            <div className="m-label text-accent">Rules earn their activation</div>
            <h2 className="m-section-title mt-3">Policy as versioned code, back-tested before it can touch a run.</h2>
          </Reveal>
          <Reveal className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-3">
            {[
              {
                icon: <GitBranch width={16} height={16} />,
                title: "Immutable per version",
                body: "An edit creates version N+1. A database trigger refuses anything else. Every exception cites the rule id and version that shrank it.",
              },
              {
                icon: <Lock width={16} height={16} />,
                title: "Back-tested before activation",
                body: "A draft runs against every exception a human already resolved. Would explain, would partially explain, would wrongly close. A rule that would wrongly close anything is told so.",
              },
              {
                icon: <Sparkles width={16} height={16} />,
                title: "Learned, never self-activated",
                body: "When three payouts share a pattern, the controller drafts a rule and shows it in violet. It waits for a back-test and a human. Always.",
              },
            ].map((c, i) => (
              <div key={c.title} className="cascade m-card px-5 py-5" style={cascadeStyle(i)}>
                <span className="flex h-8 w-8 items-center justify-center rounded-[8px] border border-[rgba(255,255,255,0.1)] bg-[rgba(255,255,255,0.04)] text-ink-2">
                  {c.icon}
                </span>
                <div className="mt-3.5 text-[15px] font-semibold text-ink">{c.title}</div>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">{c.body}</p>
              </div>
            ))}
          </Reveal>
        </div>
      </section>

      <section id="gates" className="m-section border-t border-[rgba(255,255,255,0.05)]">
        <div className="mx-auto grid max-w-[1200px] grid-cols-1 gap-12 px-6 lg:grid-cols-[1fr_1.1fr] lg:items-center">
          <Reveal>
            <div className="m-label text-accent">Deterministic where it counts</div>
            <h2 className="m-section-title mt-3">Measured against ground truth it cannot see.</h2>
            <p className="mt-4 text-[16px] leading-relaxed text-ink-2">
              A seeded adversarial generator writes the corpus and the answer key: truncated UTRs, split settlements, a mid-period rate change,
              duplicate vouchers, chargebacks nobody booked. The engine is scored against it on every run. The gates block merge, and false
              auto-resolutions is the one that matters.
            </p>
            <p className="mt-3 text-[13.5px] text-ink-3">
              Same seed, same rule set, byte-identical output. No wall-clock in logic, no unordered iteration. Replay any run under new rules and
              diff exactly which decisions moved.
            </p>
          </Reveal>
          <Reveal delay={0.1}>
            <LiveGates />
          </Reveal>
        </div>
      </section>

      <section className="m-section border-t border-[rgba(255,255,255,0.05)]">
        <Reveal className="mx-auto max-w-[1200px] px-6 text-center">
          <h2 className="m-section-title">See the queue shrink in front of you.</h2>
          <p className="mx-auto mt-4 max-w-[520px] text-[16px] text-ink-2">
            The demo corpus runs in about a second. Every number on this page came from it.
          </p>
          <div className="mt-8 flex justify-center">
            <LiquidCta href="/app1" label="Open the controller" />
          </div>
        </Reveal>
      </section>

      <footer className="border-t border-[rgba(255,255,255,0.05)] py-8">
        <Reveal className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-4 px-6 text-[12.5px] text-ink-3">
          <Brand />
          <span>Razorpay × bank × Tally · integer paise · one Postgres · the model narrates, it never decides.</span>
        </Reveal>
      </footer>
    </main>
  );
}
