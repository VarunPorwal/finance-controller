# Finco web

Next.js 15 (App Router, Turbopack), Tailwind v4, TanStack Query, and the
generated OpenAPI client in `lib/api.ts`. Run it with `.\scripts\dev.ps1 web`
from the repo root; the API must be up on `NEXT_PUBLIC_API_BASE_URL`.

## Routes

Two route groups. `(app)` is the controller and ships zero WebGL.
`(marketing)` is the product page and is the only place Three.js loads.

| Route | Screen |
|---|---|
| `/` | Overview: headline figures, run history, match-rate dial, the queue, ask-the-books |
| `/ingest` | Three source slots, demo corpus, stored files, import history (`/sources` redirects here) |
| `/exceptions`, `/exceptions/[id]` | The queue, grouped by what to do; evidence pack and proof tree beside it |
| `/reconcile` | The reconciliation bridge, wired to the queue; books vs bank; replay and diff |
| `/cash` | At risk, held, reserve, GST input credit; deductions and unexplained segments |
| `/rules`, `/rules/[id]` | Rule Book: versions, back-test, activation, learned suggestions |
| `/activity` | Narrative, audit timeline, model calls |
| `/audit` | Hash-chained event log and chain verification |
| `/records` | Normalised rows from every source |
| `/eval`, `/ask` | Reachable from the command bar (⌘K) and in-page links, not the sidebar |
| `/landing` | The product page, with live figures from the current run |

## Design system

Tokens live in `app/globals.css`. Dark surface, hairline borders, Geist for
UI text and Geist Mono with tabular figures for every rupee amount, UTR,
rule id and count (the `.num` utility). Three numeral sizes: 28, 22, 15.

Colour carries meaning and nothing else:

- emerald `--ok` proven or auto-resolved
- amber `--warn` open, monitoring, unexplained
- red `--bad` needs a human, at risk
- violet `--model` anything a model wrote: Ask the books, the run narrative, learned rules, the instruction preview
- source hues `--src-razorpay`, `--src-bank`, `--src-ledger` are categorical and never signal state

Primitives are in `components/ui`: `Panel`, `Stat`, `Pill`, `Button`,
`Segmented`, `Skeleton`, `EmptyState`, `Sparkline`, `Gauge` (one per screen,
for a rate), `SourceGlyph`, `TrendChart`. Tables use the `.th` / `.td`
classes directly.

## Rules the frontend keeps

- Every figure is read from the API. Nothing financial is computed here;
  formatting only (`lib/format.ts`).
- Never hand-write `fetch`; use `apiClient` from `lib/client.ts`. The one
  exception is the multipart upload in `components/ingest-panel.tsx`.
- Never use `localStorage` or `sessionStorage`.
- The `@designcodeio/threeui` package renders its scenes inside `srcdoc`
  iframes and sizes them to the parent, so the parent sets the box. It is
  imported only from `components/marketing/*` via `next/dynamic` with
  `ssr: false`, behind a WebGL and reduced-motion check, over a CSS poster.

Regenerate the client after any Pydantic change: `.\scripts\dev.ps1 client`.
