# AI Finance Controller. `make` is the interface; there is no Docker config.
# Python work runs through uv; the web app through npm.

.PHONY: setup api web fast check demo demo-local eval migrate generate test lint typecheck client

SEED ?= 42
N ?= 500
LOCAL_DATABASE_URL ?= postgresql+asyncpg://postgres:postgres@localhost:5432/fc

setup:
	uv sync
	cd web && npm install

api:
	uv run uvicorn api.main:app --reload --port 8000

web:
	cd web && npm run dev

# Seed the synthetic corpus, then reconcile it end to end.
demo: generate
	uv run python -m fc.pipeline --demo

# Same, against local Postgres with the LLM pinned to its disk cache: no network.
demo-local:
	DATABASE_URL="$(LOCAL_DATABASE_URL)" LLM_MODE=cache_only $(MAKE) demo

# Accuracy suite. Runs with no database and no network (PRD §3.7).
# Exits non-zero when a §12.5 gate fails, so it can actually block a merge.
eval:
	uv run python -m fc.eval.report

# The iteration loop: lint, types and unit tests. No database, no network, no
# eval corpus. Under a minute, so it can run after every edit. NOT a gate - the
# integration suite is where RLS, the read-only transaction, dry_run and the
# audit chain are actually proven, and none of that runs without Postgres.
fast: lint typecheck
	uv run pytest tests/unit

# Everything that gates a commit: `fast`, plus integration and the eval gates.
#
# FC_REQUIRE_DB turns a skipped integration test into a failure. pytest counts a
# skip as success, and on 29 Aug a green run had 21-29 integration tests
# silently skipped because Neon was cold - which meant the RLS and
# read-only-transaction proofs had never executed on the run used to justify
# them. A skipped test is an unrun proof; this makes the gate say so.
check: export FC_REQUIRE_DB=1
check: lint typecheck test eval

migrate:
	uv run alembic upgrade head

generate:
	SEED=$(SEED) N=$(N) uv run python -m fc.generator.seed

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy --strict engine/src

# Regenerate the TypeScript client after any Pydantic change.
client:
	uv run python -m api.main --openapi > web/lib/openapi.json
	cd web && npx openapi-typescript lib/openapi.json -o lib/api.ts
