# SPDX-FileCopyrightText: 2026 Siddharth Majhi
# SPDX-License-Identifier: MIT
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend

# .env is deliberately NOT included here: Make would parse it as Make syntax (mangling '#', quotes
# and '$'), override the caller's environment, and export secrets to every child process.
# Docker Compose and the backend Settings read .env themselves; test-integration reads one key.
ENV_FILE := .env

.PHONY: help install up migrate down lint typecheck test test-integration test-e2e verify compliance license-check

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies from lockfiles
	cd $(BACKEND) && uv sync --frozen
	cd $(FRONTEND) && pnpm install --frozen-lockfile

up: ## Build and start db, backend and frontend; waits until all are healthy
	docker compose up -d --build --wait

migrate: ## Apply database migrations to DATABASE_URL (reads .env)
	cd $(BACKEND) && uv run alembic upgrade head

down: ## Stop the stack (keeps the database volume)
	docker compose down

lint: ## SPDX headers, Ruff (lint + format check) and ESLint
	python3 scripts/add_spdx_headers.py --check
	cd $(BACKEND) && uv run ruff check --config pyproject.toml . ../scripts
	cd $(BACKEND) && uv run ruff format --config pyproject.toml --check . ../scripts
	cd $(FRONTEND) && pnpm lint

typecheck: ## mypy --strict and tsc --noEmit
	cd $(BACKEND) && uv run mypy && uv run mypy --strict ../scripts
	cd $(FRONTEND) && pnpm typecheck

test: ## Backend unit/contract tests, tooling tests and frontend unit tests
	cd $(BACKEND) && uv run pytest -m "not integration"
	cd $(BACKEND) && uv run pytest ../scripts/tests
	cd $(FRONTEND) && pnpm test

test-integration: ## Backend integration tests against PostgreSQL (TEST_DATABASE_URL from env, else .env)
	@url="$${TEST_DATABASE_URL:-$$(sed -n 's/^TEST_DATABASE_URL=//p' $(ENV_FILE) 2>/dev/null | tail -n 1)}"; \
	test -n "$$url" || { echo "TEST_DATABASE_URL is not set (environment or $(ENV_FILE))"; exit 1; }; \
	cd $(BACKEND) && TEST_DATABASE_URL="$$url" uv run pytest -m integration

test-e2e: ## Playwright end-to-end suite (added in Milestone 10)
	@echo "No end-to-end suite exists yet (planned for Milestone 10)."; exit 1

compliance: ## Regenerate SBOMs, licence inventory and THIRD_PARTY_NOTICES.md
	python3 scripts/compliance.py generate

license-check: ## Fail on licence policy violations or out-of-date inventory/SBOMs
	python3 scripts/compliance.py check

verify: lint typecheck test test-integration license-check ## All gates that currently exist; non-zero on any failure
	@echo "verify: all gates passed"
