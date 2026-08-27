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

```
make setup       uv sync + npm install
make api         uvicorn, reload
make web         next dev
make demo        seed + full reconciliation
make demo-local  same, local Postgres, LLM_MODE=cache_only, no network
make eval        accuracy suite, prints the metrics table
make migrate     alembic upgrade head
make generate    synthetic corpus (SEED=42 N=500)
make test        pytest
make typecheck   mypy --strict engine/src
```

Run `make test` and `make typecheck` before reporting a task complete.
For anything touching matching, rules or tiering, also run `make eval`.

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
- **Subset-sum with multiple valid subsets returns None**, producing an
  exception. Never pick one.

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
