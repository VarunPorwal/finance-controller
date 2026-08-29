# AI Finance Controller

Reconciles Razorpay settlements, Indian bank statements and Tally ledger exports.
Resolves what it can prove, refuses to close what it cannot, hands a human a
ranked queue of decisions.

Buildathon deadline: 5 Sept 2026. Full spec: `docs/PRD.md` (read the section you
need, not the whole file).

## Hard rules

1. **Money is integer paise. Never float.** No `float`, no `/`, no `round()` on
   money. `Decimal` for intermediate arithmetic, `int` paise for storage.
2. **The LLM never decides whether something is reconciled.** `fc/matching/`,
   `fc/rules/evaluator.py`, `fc/exceptions/tier.py` and `fc/cash/` must not
   import `fc.llm`. CI enforces this.
3. **Every LLM output is verified by deterministic code before it affects
   state.** Extraction → balance check. SQL → guard + database. Command →
   validator + human confirm. Rule draft → back-test + human approve.
4. **Abstention is a correct outcome.** When several answers are valid, emit an
   exception, never a guess. `ambiguous_multi_candidate` is a success.
5. **Nothing closes without evidence**: stage, fields agreed, arithmetic, rule
   version. Empty evidence is a bug.
6. **`engine/` imports nothing from `api/` or `db/`.** `make eval` must run with
   no database and no network.
7. **Every write endpoint accepts `dry_run`.** The preview flow depends on it.
8. **Rules are immutable per version.** Edits create version N+1. A DB trigger
   enforces this; don't work around it.
9. **Determinism.** Same seed + same ruleset → byte-identical output. No
   wall-clock in logic, no unordered iteration.

## Commands

**GNU Make is not installed on this machine and is not going to be.** The
Makefile is the canonical description of the commands; `scripts/dev.ps1` is what
actually runs here. The two mirror each other target for target — change one,
change the other.

| Target | PowerShell (use this) | Does |
|---|---|---|
| `make setup` | `.\scripts\dev.ps1 setup` | uv sync + npm install |
| `make api` | `.\scripts\dev.ps1 api` | uvicorn, reload |
| `make web` | `.\scripts\dev.ps1 web` | next dev |
| `make demo` | `.\scripts\dev.ps1 demo` | seed + full reconciliation |
| `make demo-local` | `.\scripts\dev.ps1 demo-local` | same, local Postgres, LLM_MODE=cache_only, no network |
| `make check` | `.\scripts\dev.ps1 check` | lint + typecheck + test + eval. **Run this before every commit.** |
| `make eval` | `.\scripts\dev.ps1 eval` | accuracy suite; **exits non-zero when a §12.5 gate fails** |
| `make migrate` | `.\scripts\dev.ps1 migrate` | alembic upgrade head |
| `make generate` | `.\scripts\dev.ps1 generate -Seed 42 -N 500` | synthetic corpus |
| `make test` | `.\scripts\dev.ps1 test` | pytest |
| `make lint` | `.\scripts\dev.ps1 lint` | ruff check + format check |
| `make typecheck` | `.\scripts\dev.ps1 typecheck` | mypy --strict engine/src |
| `make client` | `.\scripts\dev.ps1 client` | regenerate web/lib/api.ts |

Run `.\scripts\dev.ps1 check` before reporting a task complete. It is lint +
typecheck + test + eval, and it fails the build on any §12.5 gate.

`test` deliberately excludes the eval suite (`addopts = -m 'not eval'`) because
it needs the generated corpus and is slow. That exclusion meant
`false_auto_resolutions == 0` — the merge blocker this submission rests on — ran
only when somebody typed `pytest -m eval` by hand, and `make eval` printed the
number without ever comparing it to anything. Both are fixed; `check` is the
target that enforces them.

## Conventions

- Python 3.12, Pydantic v2 with `extra="forbid"`, SQLAlchemy 2.0 async.
- IDs are ULIDs, not UUID4.
- Timestamps are timezone-aware.
- Regexes compile at module level, never per row.
- Engine functions are pure: take data and config, return data. No DB inside a
  matching stage or a rule evaluator.
- Routers validate, call engine, serialise. No business logic in `api/routers/`.
- Frontend calls the generated client in `web/lib/api.ts`. Never hand-write
  fetch. Regenerate with `make client` after any Pydantic change.
- Never use localStorage or sessionStorage in the frontend.


## Things that are easy to get wrong here

- **Razorpay amounts are already integer paise.** Don't run them through
  `to_paise()`. Bank and Tally amounts do need it.
- **Tally negatives use a `(-)` prefix**, not a minus sign, with Indian digit
  grouping: `(-)1,24,500.00`.
- **Bank CSV rows can have more fields than the header** when the narration
  contains a comma. Absorb the overflow into the narration column.
- **Narration truncates at ~100 chars**, often cutting the UTR. Truncated
  references are excluded from exact matching. This is the main cause of real
  match failures, not an edge case.
- **MDR is computed per transaction then summed**, so batch settlements carry a
  few paise of rounding drift. The tolerance model absorbs it via the
  `n_txns * rounding_drift_paise` term. Don't remove that term.
- **`NEVER_AUTO` categories escalate regardless of confidence**:
  `chargeback_unrecorded`, `duplicate_ledger_entry`, `ambiguous_multi_candidate`,
  `nach_batch_unexploded`, `unknown`. Don't soften this to raise coverage.
- **A rule shrinks an exception**, it doesn't pass or fail. `₹3,240 unexplained
  after rule X applied`, not `₹19,000 mismatch`.
- **Fuzzy matches cap at 0.75 and never auto-close.** Enforced by assertion.
- **`fc/eval/report.py` was created early in Prompt 4 as a partial** so
  `dev.ps1 eval` would run. Prompt 10 must replace it with the full harness per
  PRD §12.4, not extend the stub.
- **`false_auto_resolutions` does not measure the `NEVER_AUTO` rule.** It is
  scored pairwise, and ground truth files a duplicate voucher under the same
  `gt_match_group` as the settlement it duplicates — so pairwise it is a correct
  pair while as a decision it is a wrong auto-close. Read
  `never_auto_inside_auto_closed` for that. It stands at **14** (4
  `chargeback_unrecorded`, 10 `ambiguous_multi_candidate`) and needs
  `fc/exceptions/classify.py`; three-way already closed the 3
  `duplicate_ledger_entry` cases it can prove.
- **Stage 4's subset-sum DP has zero corpus cases.** Every scenario-3 batch is
  claimed by stage 1 first via the shared UTR, and the 41-row batch is over
  `max_subset_n`. The DP is unit-tested only, and
  `many_to_one.subset_sum_invocations` is expected to read 0 — treat a non-zero
  value as new information, not as the stage finally working.
- **Group-level properties (`auto_closed`, confidence cap) must be computed
  across all legs. Never read `host.stage` for anything that describes the
  group. A group is only as provable as its weakest leg.** `MatchResult.stage`
  is the *forming* stage and stays that way — it is a label, not the rule, and
  treating it as the rule has produced this bug twice: once in `auto_closed` and
  once in the confidence cap, in adjacent lines. Both are now enforced by
  `MatchResult` validation via `group_confidence_cap` and `stage_may_auto_close`,
  and asserted over the corpus in `eval`, because the pairwise metric cannot see
  either — ground truth scores such a group as correctly matched.
- **`order_id` identifies an order, not a money movement.** A payment, its
  partial refund and its chargeback all quote the same order id and settle in
  different batches. `fc/matching/stages/exact_ref.py` splits order-scoped join
  keys by payment/refund side; without that, stage 1 merges a payment with its
  own refund and precision drops below 100%.
- **A ledger narration citing two ids of one kind identifies itself with
  neither.** `Rolling reserve release settlement setl_B for setl_A` merged two
  settlements until `LedgerRefs.identity_claims()` started requiring exactly
  one. Extraction is not attribution.
- **A shared reference prefix is not evidence.** An RBI UTR is
  `bank + year + day-of-year + sequence`, so one 8-character prefix covers a
  dozen settlements. `date_shift` requires a *unique completion*, not a prefix
  match.
- **Subset-sum with multiple valid subsets returns None**, producing an
  exception. Never pick one.
  - **RLS tests must run as `fc_app_user`, not the owner.** `neondb_owner`
  carries `rolbypassrls` via Neon's `neon_superuser`, so `FORCE ROW LEVEL
  SECURITY` doesn't constrain it. Verifying tenant isolation on the owner
  connection gives a false pass. Use `DATABASE_URL_APP`.
- **`DATABASE_URL_READONLY` points at the owner until day 8.** The
  text-to-SQL guard is not yet backed by a real read-only role. Don't
  treat it as enforced.
- **The IDFC, ICICI and Tally-XML shapes in `fc/ingest/` are invented, not
  sourced from a real export.** The PRD gives HDFC's NEFT format, the UPI/
  IMPS/RTGS/NACH shapes, and the Tally field table precisely, but nothing
  concrete for IDFC/ICICI narrations or a Tally XML tag schema — the demo
  only ever sees generator output, so this is fine, but it means the
  generator (Prompt 3) is the sole source of truth for those shapes. If
  either side changes — a parser regex in `fc/ingest/narration/idfc.py` or
  `icici.py`, the XML tag aliases in `fc/ingest/tally.py`, or what the
  generator emits — change the other side in the same commit, or ingestion
  silently stops matching what it's fed.

## Quality gates (block merge)

- `false_auto_resolutions == 0` on the eval corpus
- recall ≥ 90%
- no float in money modules
- no `fc.llm` import in decision modules
- same seed → same output
- mypy strict passes on `engine/`

## When to stop and ask

- A change would require altering the DB schema after 28 Aug.
- Ground-truth labels in the generator look wrong.
- A fix would involve loosening a hard rule above.
- The eval gate fails and the obvious fix is to change the threshold.

## Don't

- Don't add dependencies without asking. The stack is fixed and free-tier only.
- Don't add DuckDB, Redis, Celery or a message broker. One Postgres.
- Don't write Docker config unless asked. `make` is the interface.
- Don't add explanatory comments to self-evident code.
- Don't tune confidence constants to improve headline numbers. The coverage
  curve will expose it.
- Don't create files outside the structure in `docs/PRD.md` §3.7.
