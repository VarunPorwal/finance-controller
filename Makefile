# AI Finance Controller. `make` is the interface; there is no Docker config.
# Python work runs through uv; the web app through npm.

.PHONY: setup api web check demo demo-local eval migrate generate test lint typecheck client

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

# Everything that gates a commit. `test` deliberately excludes the eval suite
# (it needs the generated corpus and is slow), which meant the
# false_auto_resolutions gate - the merge blocker this whole submission rests on
# - ran only when somebody typed `pytest -m eval` by hand. Run this, not `test`.
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
