# Handoff: Finco Reconciliation App

## Overview
A financial reconciliation product ("Finco") that matches records across Razorpay, HDFC Bank, and Tally, surfaces exceptions, encodes deduction rules ("Rule Book"), and reports match-accuracy metrics ("Evaluation"). This package covers the full flow: Reconcile (home), Exceptions, Data Sources, Records, Rule Book (list + detail), Controller Activity, and Evaluation.

## About the Design Files
The bundled file (`CONTROL Reconcile.dc.html`) is a **design reference built in HTML** — a working prototype showing layout, states, and interactions, not production code to copy directly. The task is to **recreate this design in your app's existing environment** (React, Vue, etc.) using your established component patterns, or pick the most suitable framework if none exists yet.

## Fidelity
**High-fidelity.** Colors, type, spacing, and copy are final as specified below. Recreate pixel-perfectly using your codebase's own component library where possible (e.g. swap the demo `<table>`/div markup for your existing Table/Card/Button components, keeping these exact visual values).

## Screens / Views

### 1. Reconcile (home)
- Header: page title "Reconciliation" (24px/600, letter-spacing -0.025em) + date-range chip + secondary "Export" button + primary "Run reconciliation" button (blue, icon+label).
- KPI row: 4 cards, grid 4 columns, 20px gap. Each card: label (13px/500, #5B6472) + icon chip (26×26, 8px radius) top row; mono value (28px/600) + delta pill (12px, green ▲/▼) + comparison text (#9AA1AC) bottom.
- Row 2, grid 1.65fr/1fr, 20px gap:
  - Left column (stacked, 20px gap):
    - **Value reconciled** card: legend (This month solid blue / Last month dashed grey) → SVG line chart (560×170 viewBox), hover-triggered dashed crosshair + two dots + dark tooltip (not pinned open) → big mono value (28px) + delta + Expected/Unexplained mini stats (16px mono).
    - **Cash Bridge** card: 4-segment row (grid 4 cols, 16px gap), each segment: 3px colored top rule, 26×26 icon tile, mono amount (22px/600, colored), caption (12px, #9AA1AC). Segments: Gross settled (blue), Fees/GST/TDS/reserve (grey, "−₹84,651"), Credited to bank (green), Unexplained gap (amber). Footer line (12.5px, #5B6472): "Expected in bank was ₹4,19,549. The ₹7,549 shortfall is what the review queue exists to close."
    - **Sources** card: colored square + mono count + label per source, stacked horizontal bar below (flex-basis by count).
  - Right column (stacked, 20px gap):
    - **Auto-Resolutions**: mono value (22px) + 7-day bar chart (Tue highlighted blue, rest grey).
    - **System Health**: semicircle gauge, 24 radial tick marks (green up to 92.4%, grey rest), mono readout (22px/600) centered, caption, outlined "Show details" button.
    - **Ask Controller** (violet — model output only): background #FAF8FF, border #E6E0FA, heading color #5B21B6, "Model output" pill, gradient orb (purple radial), input-style prompt placeholder.
- **Decisions requiring attention** table (semantic `<table>`): columns Counterparty (icon tile + name), Exception, Cause cluster, Reference (mono), Amount (mono, right-aligned, 16px), Confidence (mono, right-aligned), Tier (status pill, right-aligned). "View all →" link to Exceptions.

### 2. Exceptions
Same table as above, full 46-row set (8 shown in prototype), filter pills above (All/High/Auto-resolved/Assigned to me).

### 3. Data Sources
3 connector cards (Razorpay, HDFC Bank, Tally): icon tile, status pill (Connected/Upload), name, meta line, "View data"/"Upload" link. Below: Import history list (source, file, rows right-aligned mono, status pill, time).

### 4. Records
3 source-health cards (name, mono count, last-import meta, health pill). Below: transaction ledger rows (date, source, reference mono, amount mono right-aligned, status pill).

### 5. Rule Book (list)
Header + primary "+ Create rule" button. Filter pills (All/Active/Draft/Suggested/Archived). Grid of 2 rule cards per row:
- Standard rule card (white): name, scope, deduction lines (label + mono % value), version pill + status pill (ACTIVE/DRAFT) + effective-date text, footer with affected-count + "View rule →".
- **Suggested rule card** (violet — model output): background #FAF8FF/border #E6E0FA, "✦ LEARNED SUGGESTION" label in #5B21B6, "Draft only" pill (violet), disclaimer line "Suggested rules never activate on their own" (11.5px, #5B21B6).
Clicking any card navigates to Rule Detail.

### 6. Rule Book (detail) — keep as-is, this is the reference screen
- Back link to Rule Book.
- Left column: **WHEN** card (2×2 grid of scope fields), **THEN EXPECT** card (deduction rows: label/basis-line + mono % value; Tolerance row separated below), **BACKTEST** card (narrative line, 2×2 stat grid with colored mono values, Precision/Coverage inline stats + green "Activate" pill).
- Right column: **Version history** card — dot timeline (green=active, grey=past), version tag + ACTIVE pill, date, one-line summary.

### 7. Controller Activity
3 stat cards (Runs today, Rules evaluated, Avg run time). Below: "Today" timeline — colored dot + mono timestamp + description per entry.

### 8. Evaluation (new)
- 4 quality-gate cards: label, green "PASS" pill, mono actual value (22px), threshold caption.
- Precision & recall by matching stage: semantic table (Stage / Precision / Recall, numerics right-aligned mono), "Export metrics" outlined button in header.
- False resolutions card: mono "0" (28px hero size) + caption "across 412 auto-matched records".
- Recall trend: small SVG sparkline + mono readout.

## Interactions & Behavior
- Sidebar and in-page links (View all, View rule, back) switch screens via local state — no real routing in the prototype; implement as actual routes/views in the target app.
- Chart tooltip on Value Reconciled is **hover-triggered** (mouseenter/mouseleave on the chart container) — shows dashed crosshair + two series dots + dark tooltip. It must not render open by default.
- Rule cards and nav items are clickable (cursor: pointer).
- No form validation, loading, or error states are modeled in this static prototype — design them per your app's existing patterns.

## Design Tokens

**Colors**
- Background: `#F5F6F8`
- Card surface: `#FFFFFF`, border `#EEF0F3`
- Primary (deterministic engine output only): `#2F6FED`, hover `#1D4ED8`, active nav tint `#EFF6FF` / text `#1D4ED8`
- Success/verified: `#0F9D58`, bg tint `#E7F7EE`
- Amber/monitoring: `#F59E0B` accents, text `#B45309`, bg tint `#FEF2E8`
- Error/needs review: `#DC2626`, bg tint `#FEECEC`
- Violet — reserved exclusively for model/LLM output: surface `#FAF8FF`, border `#E6E0FA`, text `#5B21B6`, pill bg `#EDE4FF`
- Text: heading `#0F172A`, body/secondary `#5B6472`, muted `#9AA1AC`, faint `#B4BAC4`
- Neutral badge (counts, non-semantic): bg `#F1F3F6`, text `#5B6472`

**Typography**
- UI font: Inter (400/500/600)
- Numeral font: JetBrains Mono (400/500/600) — used for every amount, percentage, ID, count
- Page title: 24px / 600 / letter-spacing -0.025em
- Card title: 14px / 600
- Body: 13px
- Numeral scale — exactly 3 sizes: 28px (hero values: KPI values, chart totals, false-resolution count), 22px (secondary values: bridge segments, activity stats, gauge/mini totals), 16px (row values: table cells, deduction values, stat rows)
- Max font-weight anywhere: 600 (no 700 weights)

**Spacing**
- Card padding: header block `16px 20px 0`, body block `14px 20px 20px` (one rule, applied to every card)
- Grid gutters: 20px
- Border radius: 14px cards, 8–9px buttons/inputs, 6–7px pills/tags

**Borders / Shadow**
- Single border color everywhere: `#EEF0F3` (buttons, inputs, cards — no `#E7E9ED`)
- Shadow: `0 1px 2px rgba(16,24,40,0.03)` on all elevated cards

**Icons**
- One line-icon set (Tabler/Lucide style, stroke-based, `currentColor`), no emoji anywhere
- Sizes: 16px sidebar, 15px buttons, nothing above 18px

## Assets
No image/photo assets — everything is inline SVG (icons, charts, gauge). If your target app has an existing icon library (e.g. `lucide-react`, `@tabler/icons`), swap the inline SVGs for the equivalent library icons at the same sizes.

## Files
- `CONTROL Reconcile.dc.html` — full prototype, all 8 screens, view-switching logic in a single component. Open in a browser to click through the flow before implementing.
