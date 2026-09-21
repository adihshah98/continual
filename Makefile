.PHONY: install dev test lint fmt check db-migrate db-rollback db-status materialize spotcheck

install:
	uv sync --extra dev

dev:
	uv run uvicorn continual.main:app --reload

# Unit tests: deterministic/pure logic only (hashing, normalization, validation,
# assembly, tiering) — no DB, no network, no S3.
test:
	uv run pytest

lint:
	uv run ruff check src tests db
	uv run ruff format --check src tests db

fmt:
	uv run ruff check --fix src tests db
	uv run ruff format src tests db

# The full local gate before pushing.
check: lint test

# DB is Supabase (set DATABASE_URL in .env.local — see .env.example).
db-migrate:
	uv run alembic upgrade head

db-rollback:
	uv run alembic downgrade -1

db-status:
	uv run alembic current && uv run alembic history

# Materialize raw spans into episodes. Usage: make materialize TENANT=acme
materialize:
	uv run python -m continual.cli.materialize --tenant $(TENANT)

# The Stage 1 gate: sample episodes for a hand spot-check.
# Usage: make spotcheck TENANT=acme N=40
spotcheck:
	uv run python -m continual.cli.spotcheck --tenant $(TENANT) --n $(N)
