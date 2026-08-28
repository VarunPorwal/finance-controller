# AI Finance Controller

Reconciles Razorpay settlements, Indian bank statements and Tally ledger exports
against each other. Resolves what it can prove, refuses to close what it cannot,
and hands a human a ranked queue of decisions.

Full specification: [`docs/PRD.md`](docs/PRD.md). Working agreements:
[`CLAUDE.md`](CLAUDE.md).

## Setup

Requires Python 3.12 (pinned in `.python-version`), [uv](https://docs.astral.sh/uv/),
Node 20+, and a Postgres 16 database with `pgvector` (Neon).

```bash
cp .env.example .env      # fill in DATABASE_URL and FC_APP_PASSWORD at minimum
./scripts/dev.ps1 setup
./scripts/dev.ps1 migrate
```

`FC_APP_PASSWORD` is the login password for `fc_app_user`, the non-owner role the
migration creates. Row-level security binds on that role, so the API cannot run
without it. Set `DATABASE_URL_APP` to the same host and database with
`fc_app_user` as the user.

## Commands

Two entry points for the same targets. The `Makefile` is the canonical
description; `scripts/dev.ps1` is the PowerShell equivalent, for machines
without GNU Make. Add a target to one and add it to the other.

| Target | PowerShell | What it does |
|---|---|---|
| `make setup` | `./scripts/dev.ps1 setup` | `uv sync` plus `npm install` in `web/` |
| `make api` | `./scripts/dev.ps1 api` | uvicorn with reload on :8000 |
| `make web` | `./scripts/dev.ps1 web` | `next dev` on :3000 |
| `make demo` | `./scripts/dev.ps1 demo` | seed the corpus, then reconcile it end to end |
| `make demo-local` | `./scripts/dev.ps1 demo-local` | same against local Postgres, `LLM_MODE=cache_only`, no network |
| `make eval` | `./scripts/dev.ps1 eval` | accuracy suite; prints the metrics table |
| `make migrate` | `./scripts/dev.ps1 migrate` | `alembic upgrade head` |
| `make generate` | `./scripts/dev.ps1 generate -Seed 42 -N 500` | synthetic corpus |
| `make test` | `./scripts/dev.ps1 test` | pytest |
| `make lint` | `./scripts/dev.ps1 lint` | ruff check and format check |
| `make typecheck` | `./scripts/dev.ps1 typecheck` | `mypy --strict engine/src` |
| `make client` | `./scripts/dev.ps1 client` | regenerate `web/lib/api.ts` from the OpenAPI schema |

## Layout

```
engine/     pure domain logic. Imports nothing from api/ or db/, and its
            dependency list contains only pydantic and python-dotenv, which is
            what makes that rule mechanical rather than aspirational.
api/        FastAPI. Routers validate, call the engine, serialise.
db/         SQLAlchemy models and Alembic migrations.
web/        Next.js 15, Tailwind, shadcn/ui.
data/       rule definitions and the generated corpus.
scripts/    dev.ps1, the PowerShell mirror of the Makefile.
tests/      unit, integration, eval.
```

uv workspace: the root `pyproject.toml` owns the API and persistence
dependencies and lists `engine` as a member. One lockfile, one `uv sync`.

## Two things to know before changing anything

**Money is integer paise.** No float, anywhere in the money path. `Decimal` for
intermediate arithmetic, `int` paise for storage. `to_paise()` takes a rupee
string or `Decimal` and rejects a bare `int` — "1000" as rupees and 1000 as
paise are the same value written two ways, and there is no safe default. Values
that are already paise (Razorpay) go through `already_paise()` so the unit is
explicit at the call site. `tests/unit/test_money.py` AST-scans the module and
fails on a float literal.

**The database enforces two rules the code cannot.** Active rules are immutable:
a trigger raises on any UPDATE that changes an active rule's `scope`,
`deductions` or `tolerance`, so a new version is the only way to change one.
And `audit_events` has `UPDATE`/`DELETE` revoked, so the hash chain is
append-only by grant, not by convention.

## Row-level security

Every tenant-scoped table has RLS enabled and forced, with policies keyed off
`current_setting('app.tenant_id')`. The API sets that per request with
`SET LOCAL`, which scopes it to the transaction so a pooled connection cannot
carry one tenant's context into the next request.

This only binds because the API connects as `fc_app_user`, which has no
`BYPASSRLS`. Neon's `neondb_owner` — the role migrations run as — carries
`BYPASSRLS` via `neon_superuser` and is not subject to the policies. That is
correct for migrations and admin work, and it is why the application must never
use `DATABASE_URL`.

`DATABASE_URL_READONLY`, which the text-to-SQL layer will use, currently points
at the owner role. It needs its own genuinely read-only role before that layer
ships.

## Status

Foundation only: models, schema, migration, scaffold. Ingestion, matching,
rules, exceptions, the AI layer and the frontend land in later prompts — their
directories exist and their modules do not.
