SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend

# .env is deliberately NOT included here: Make would parse it as Make syntax (mangling '#', quotes
# and '$'), override the caller's environment, and export secrets to every child process.
# Docker Compose and the backend Settings read .env themselves; test-integration reads one key.
ENV_FILE := .env

.PHONY: help install up down lint typecheck test test-integration test-e2e verify

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies from lockfiles
	cd $(BACKEND) && uv sync --frozen
	cd $(FRONTEND) && pnpm install --frozen-lockfile

up: ## Build and start db, backend and frontend; waits until all are healthy
	docker compose up -d --build --wait

down: ## Stop the stack (keeps the database volume)
	docker compose down

lint: ## Ruff (lint + format check) and ESLint
	cd $(BACKEND) && uv run ruff check . && uv run ruff format --check .
	cd $(FRONTEND) && pnpm lint

typecheck: ## mypy --strict and tsc --noEmit
	cd $(BACKEND) && uv run mypy
	cd $(FRONTEND) && pnpm typecheck

test: ## Backend unit/contract tests and frontend unit tests
	cd $(BACKEND) && uv run pytest -m "not integration"
	cd $(FRONTEND) && pnpm test

test-integration: ## Backend integration tests against PostgreSQL (TEST_DATABASE_URL from env, else .env)
	@url="$${TEST_DATABASE_URL:-$$(sed -n 's/^TEST_DATABASE_URL=//p' $(ENV_FILE) 2>/dev/null | tail -n 1)}"; \
	test -n "$$url" || { echo "TEST_DATABASE_URL is not set (environment or $(ENV_FILE))"; exit 1; }; \
	cd $(BACKEND) && TEST_DATABASE_URL="$$url" uv run pytest -m integration

test-e2e: ## Playwright end-to-end suite (added in Milestone 10)
	@echo "No end-to-end suite exists yet (planned for Milestone 10)."; exit 1

verify: lint typecheck test test-integration ## All gates that currently exist; non-zero on any failure
	@echo "verify: all gates passed"
