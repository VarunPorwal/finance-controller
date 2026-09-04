<div align="center">

# 💰 AI Finance Controller

**Automatic reconciliation of Razorpay settlements, Indian bank statements and Tally ledgers.**

Matches what it can prove. Refuses what it cannot. Hands you a short, ranked list of the rest, with evidence.

`Python 3.12` · `FastAPI` · `Postgres 16` · `Next.js 15` · `Gemini + Groq`

</div>

---

## Table of contents

1. [The problem](#-the-problem)
2. [Quick start](#-quick-start)
3. [Results](#-results)
4. [Architecture](#-architecture)
5. [How a run works](#-how-a-run-works)
6. [The matching cascade](#-the-matching-cascade)
7. [Where AI is used, and where it is not](#-where-ai-is-used-and-where-it-is-not)
8. [Safety and correctness](#-safety-and-correctness)
9. [Screens](#-screens)
10. [Known limits](#-known-limits)
11. [Project structure](#-project-structure)
12. [Commands](#-commands)

---

## 🎯 The problem

A single NEFT credit of ₹4,82,000 lands in your bank account. Behind it sit 14
Razorpay payments, 2 refunds, an MDR charge, GST on that MDR, TDS under 194-O
and a rolling reserve deduction. Your Tally daybook has one receipt voucher for
the whole thing. The bank narration was cut at 100 characters and lost the UTR.

Nothing lines up. A person spends three days a month making it line up.

This project does that lining-up automatically. It proves matches with
references and arithmetic, explains gaps with a versioned rulebook, and turns
what is left into a queue of decisions only a human can make. Every decision it
takes carries the evidence for it. Every decision it refuses says why.

---

## ⚡ Quick start

Requirements: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 20+, Postgres 16 with `pgvector`.

```bash
cp .env.example .env
./scripts/dev.ps1 setup
./scripts/dev.ps1 migrate
```

Seed 500 orders of synthetic data and reconcile them end to end:

```bash
./scripts/dev.ps1 demo
```

Or run the accuracy suite. It needs no database, no network and no API keys:

```bash
./scripts/dev.ps1 eval
```

Start the API and the dashboard:

```bash
./scripts/dev.ps1 api
```

```bash
./scripts/dev.ps1 web
```

---

## 📊 Results

One run over 1,575 events from three sources, with 21 injected failure modes.

| Metric | Value |
|---|---|
| Runtime | **0.25 s** |
| Auto-matched | 700 events (44%) |
| Rule-resolved | 437 events (28%) |
| Exceptions raised | 48, collapsed into **11 root causes** |
| Precision on auto-close | **100.00%** (3,652 correct, 0 wrong) |
| Recall against ground truth | **98.39%** |
| Abstention rate | 2.29% (by design) |
| Human queue | **20 items, not 1,575** |
| Cash at risk surfaced | ₹1,02,271 |
| GST input credit found | ₹8,088 |

Four gates block a release. All four pass on the committed run:

```
[PASS] false_auto_resolutions      0          (needs 0)
[PASS] never_auto_after_pipeline   0          (needs 0)
[PASS] recall                      98.39%     (needs >= 90%)
[PASS] determinism                 identical  (same seed, same output)
```

The eval command exits non-zero when any gate fails, so it can block a merge.

---

## 🏗️ Architecture

### Layers

Four layers. Dependencies point down only. The engine is pure: no database, no
network, no wall clock. Its entire dependency list is `pydantic` and
`python-dotenv`, which is what makes the boundary mechanical rather than a
convention.

```
+------------------------------------------------------------------+
|  web/          Next.js 15, React 19, TanStack Query               |
|                Calls a TypeScript client generated from the API.  |
|                A change to a Pydantic model breaks the frontend   |
|                build at the exact call site.                      |
+-------------------------------+----------------------------------+
                                |  78 endpoints, 15 routers, /api/v1
+-------------------------------v----------------------------------+
|  api/          FastAPI. Validate, call the engine, serialise.     |
|                No business logic. Every write accepts dry_run.    |
|                Tenant scope is set per transaction.               |
+-------------------------------+----------------------------------+
                                |
+-------------------------------v----------------------------------+
|  engine/       Pure domain logic. Data and config in, data out.   |
|                                                                   |
|   ingest/   matching/   rules/   exceptions/   cash/   audit/     |
|   agent/    llm/        eval/    generator/                       |
+-------------------------------+----------------------------------+
                                |
+-------------------------------v----------------------------------+
|  db/           SQLAlchemy 2.0 async, Alembic, Postgres 16         |
|                13 tables. Row-level security on every tenant      |
|                table. Two rules code cannot enforce live here:    |
|                  * a trigger rejects edits to an active rule      |
|                  * UPDATE and DELETE are revoked on audit_events  |
+------------------------------------------------------------------+
```

### Where the AI sits

The language model is one module among ten inside the engine. The four modules
that decide whether money is reconciled cannot import it. A build check scans
the import graph and fails if they try.

```
                       +-----------------------------+
                       |          engine/llm         |
                       |  router, SQL guard,         |
                       |  grounding check,           |
                       |  injection defence          |
                       +--------------+--------------+
                                      |  proposals, prose, drafts
                                      |  (never a decision)
                                      v
   +----------+   +-----------+   +---------+   +--------------+   +-------+
   |  ingest  |-->|  matching |-->|  rules  |-->|  exceptions  |-->| cash  |
   +----------+   +-----------+   +---------+   +--------------+   +-------+
                   no llm import   no llm import  tier: no llm      no llm import

   Every LLM output is checked by deterministic code before it touches state.
   With every model provider down, every number above still computes.
```

### Trust boundaries

```
   untrusted input                 verified by                  trusted state
   ----------------                -----------                  -------------
   bank narration    -> sanitise, delimit, scan     ->  TransactionEvent
   PDF statement     -> LLM extract -> balance continuity  ->  rows, or rejected
   user question     -> LLM SQL -> parser guard -> read-only txn -> RLS -> rows
   user command      -> LLM parse -> validator (7 rules) -> preview -> human -> action
   AI narration      -> every number traced to a query result, else template
   rule draft        -> arithmetic from 3 human fixes -> back-test -> human approves
```

---

## 🔁 How a run works

```
   Razorpay JSON          Bank CSV / PDF          Tally CSV / XML
   (already paise)        (narration cut at       ((-)1,24,500.00,
                           ~100 chars)             Indian grouping)
        |                      |                        |
        +----------------------+------------------------+
                               v
   1  INGEST         parse each rail's narration, verify the running
                     balance, normalise counterparty names, scan for
                     injected text, reject rows with a reason
                               v
   2  BLOCK          332,520 possible pairs -> 6,170 candidates (21x)
                               v
   3  MATCH          five passes, strictest first
                               v
   4  THREE-WAY      gateway + bank + ledger per settlement
                               v
   5  RULEBOOK       versioned, effective-dated deduction rules
                               v
   6  CLASSIFY       category -> cluster -> tier -> priority -> action
                     48 exceptions -> 11 root causes -> 20 queue items
                               v
   7  CASH BRIDGE    gross - MDR - GST - TDS - refunds - chargebacks
                     - reserve = expected net, vs what the bank credited
```

Every line of the cash bridge carries the event ids and exception ids that make
it up, so a figure on screen opens the rows behind it and those rows add up to
the figure.

---

## 🔍 The matching cascade

Each stage is cheaper and more certain than the one after it. A row matched at
one stage never reaches the next. The order is the design: collapsing five
stages into one score would lose the reason a match was made, and the reason is
what the evidence pack is.

| # | Stage | Matches on | Precision | Can auto-close |
|---|---|---|---|---|
| 1 | Exact reference | UTR, RRN or settlement id agree exactly, and are not truncated | 100% | yes |
| 2 | Fee-adjusted | `gross - fees = net`, checked over a whole settlement | 100% | yes |
| 3 | Date shift | same amount, 1 to 3 days apart, reference has a unique completion | n/a | yes |
| 4 | Many-to-one | one bank credit against the gateway rows that sum to it | 100% | grouped path only |
| 5 | Fuzzy | weighted resemblance, capped at 0.75 | n/a | **never** |

Stage 5 exists to rank suggestions for a person. The data model refuses to save
a fuzzy match above 0.75, or an auto-closed group that contains one.

### What it refuses to accept as evidence

| Looks like proof | Why it is not |
|---|---|
| A shared reference prefix | An RBI UTR is `bank + year + day + sequence`. One 8-character prefix covers 14 different settlements here. Stage 3 needs a unique completion. |
| A matching `order_id` | An order id names an order, not a movement. A payment, its refund and its chargeback all quote the same one. |
| A narration naming two ids | "Reserve release for setl_A and setl_B" identifies itself with neither. |
| Gateway and ledger agreeing | Both are statements of what should have happened. Without a bank leg, nothing auto-closes. |

### Abstention is a result

When two answers are equally valid the engine emits neither. Subset-sum with
more than one valid subset returns nothing. Five categories escalate no matter
how confident the match looks: `chargeback_unrecorded`,
`duplicate_ledger_entry`, `ambiguous_multi_candidate`, `nach_batch_unexploded`,
`unknown`. That check runs first in tiering and nothing after it can override
it.

---

## 🤖 Where AI is used, and where it is not

Ten routed tasks across Gemini and Groq, with round-robin inside a tier and a
ladder between tiers. Every route ends in a working non-AI answer.

| Task | Fallback when every model fails | Verified afterwards by |
|---|---|---|
| Bank PDF extraction | manual CSV upload | running-balance continuity |
| Question to SQL | a refusal | parser guard, read-only transaction, row-level security |
| Explaining a result | a template | every number must trace to a query result |
| Natural-language command | a form | a validator with 7 push-back rules, then human confirm |
| Drafting a rule | defer to human | back-test, then explicit approval |
| Cluster label | a template | cosmetic only; a deterministic key decides membership |

Deliberately not AI:

- deciding whether two records match
- deciding whether an exception can auto-close
- which cluster an exception belongs to
- learning a fee rule from repeated human fixes (derived arithmetically so the
  result is reproducible offline)

A rule draft never activates itself. Not at three matching fixes, not at thirty.

---

## 🛡️ Safety and correctness

| Guarantee | How it is enforced |
|---|---|
| Money is integer paise, never float | AST scan over every money module; a float literal fails the build |
| YAML rates stay exact | `rate: 0.9` is parsed from the scalar's own text into `Decimal`, never through a float |
| Tenants cannot see each other | Postgres row-level security, forced, on a role with no bypass right |
| Generated SQL cannot write or leak | parser guard, `SET TRANSACTION READ ONLY`, RLS; each layer is sufficient alone |
| Rules are immutable once active | a database trigger rejects the edit; changes create version N+1 |
| The audit trail cannot be rewritten | `UPDATE` and `DELETE` revoked; SHA-256 hash chain, verifiable end to end |
| Same input, identical output | the pipeline re-runs inside the eval suite and both results are compared byte for byte |
| Nothing writes without a preview | every write endpoint accepts `dry_run` |
| A skipped test is a failure | `check` sets `FC_REQUIRE_DB=1`; an integration test that skips fails the run and is named |

Bank narrations are free text copied from whoever sent you money, so they are
treated as hostile input. The first defence is structural: no model here can
close, tier or price anything, so a successful injection produces a suggestion a
human rejects. Beyond that, narrations are sanitised, delimited and scanned, and
a narration carrying instruction-shaped text is flagged to you as
`suspicious_narration`.

### CI

| Job | What it proves |
|---|---|
| `engine-isolation` | unit tests pass with no `DATABASE_URL` and no model keys in the environment |
| `guards` | no float in money, no LLM in decision modules, `mypy --strict`, ruff |
| `integration` | RLS, the read-only transaction, `dry_run` and the audit chain run against real Postgres |
| `frontend` | the generated client builds; schema drift cannot merge |
| `eval` | `false_auto_resolutions == 0` blocks the merge |

---

## 🖥️ Screens

| Screen | What it shows |
|---|---|
| Overview | Matched, rule-explained and waiting-for-you, at a glance |
| Ingest | Files in, rows read, rows rejected and why |
| Exceptions | The ranked queue. Open one for the evidence pack, the consequence of ignoring it and the recommended action |
| Reconcile | Gross to bank, line by line. Click any line to open the rows behind it |
| Cash | At risk, held in reserve, claimable as GST input credit |
| Rule Book | Deduction policy as versioned rules. Draft, back-test, activate |
| Ask | Plain-English questions answered from the data, with the SQL shown |
| Controller Activity | What the system did this run, and every model call with its fallback |
| Audit Trail | Every decision in a hash chain. Export as CSV or JSONL |
| Evaluation | Precision and recall per stage, the coverage curve, the four gates |
| Records | Every normalised row from every source, searchable |
| Guide | What this is, the architecture, and a ten-minute walkthrough |

---

## ⚠️ Known limits

Published because a reconciliation tool that hides its failures is worse than
no tool. `eval` prints every scored-wrong item with ids and amounts.

- **Labelling is weaker than matching.** `missing_in_gateway` recall is 0% and
  `missing_in_bank` is 2.7%; they get filed under neighbouring categories.
  Every one still reaches the human queue. The failure is a wrong heading on a
  correct escalation, never a wrongly closed settlement.
- **Mid-period rate changes are not closed yet.** A settlement that straddles a
  fee change needs the rule applied per order and summed. Today a single rate
  only shrinks the exception.
- **NACH batch lines never resolve.** A batch credit with no member detail is
  not a bug; it is a permanent escalation.
- **The coverage curve is flat on this corpus.** 100% precision and 0 false
  positives at every threshold from 0.70 to 1.00. Stage eligibility and the
  never-auto gate decide auto-close here, not the threshold.
- **Some bank formats are modelled, not sourced.** HDFC is real. ICICI, IDFC
  and Tally XML follow the generator, which is their only source of truth.
- **Model health counters are per process.** The deployment is a single
  instance; `/agent/health` reports `health_scope: "process"`.

---

## 📁 Project structure

```
engine/src/fc/
  ingest/        3 source adapters, 4 bank dialects, PDF and XML, validators
  matching/      blocking, 5-stage cascade, three-way, tolerance, confidence
  rules/         Decimal-safe YAML loader, evaluator, scope, back-test, learner
  exceptions/    classify, cluster, tier, priority, consequence, recommend
  cash/          the reconciliation bridge
  audit/         hash-chained ledger, deterministic replay
  agent/         command validator, permissions
  llm/           model router, SQL guard, grounding, injection defence, prompts
  eval/          report, confusion matrix, coverage curve
  generator/     21-scenario synthetic corpus with ground truth
api/             15 routers, 78 endpoints, dry_run on every write
db/              13 tables, RLS, immutability trigger, append-only audit
web/             Next.js 15 dashboard, generated client
tests/           unit (offline), integration (real Postgres), eval
docs/PRD.md      full technical specification
```

---

## 🛠️ Commands

| Command | What it does |
|---|---|
| `./scripts/dev.ps1 setup` | `uv sync` and `npm install` |
| `./scripts/dev.ps1 api` | API server on :8000 |
| `./scripts/dev.ps1 web` | Dashboard on :3000 |
| `./scripts/dev.ps1 demo` | Seed the corpus and reconcile it |
| `./scripts/dev.ps1 demo-local` | Same, local Postgres, no network |
| `./scripts/dev.ps1 eval` | Accuracy suite, exits non-zero on a failed gate |
| `./scripts/dev.ps1 fast` | Lint, types and unit tests, about 30 s |
| `./scripts/dev.ps1 check` | Everything including integration and eval, about 3 min |
| `./scripts/dev.ps1 migrate` | Apply migrations |
| `./scripts/dev.ps1 generate -Seed 42 -N 500` | Regenerate the synthetic corpus |
| `./scripts/dev.ps1 client` | Regenerate the TypeScript client |

A `Makefile` mirrors every target for machines with GNU Make.

`FC_APP_PASSWORD` is the login for `fc_app_user`, the non-owner role the
migration creates. Row-level security binds on that role, so the API cannot run
without it.

---

Specification: [`docs/PRD.md`](docs/PRD.md). Engineering conventions and known pitfalls: [`CLAUDE.md`](CLAUDE.md).
