# Finguard 3.0 — developer entrypoints.
# One-command targets so the project runs the same from a fresh checkout.
.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend
COMPOSE := docker compose -f infrastructure/docker-compose.yml

.PHONY: help install backend-test backend-lint backend-typecheck backend-migrate \
        frontend-install frontend-lint frontend-typecheck frontend-build \
        test lint typecheck up down logs

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n",$$1,$$2}'

install: frontend-install ## Install all dependencies
	cd $(BACKEND) && uv sync --all-extras

# ── Backend ───────────────────────────────────────────────────────────────────
backend-test: ## Run backend test suite
	cd $(BACKEND) && uv run pytest tests/ -q

backend-lint: ## Lint backend (ruff)
	cd $(BACKEND) && uv run ruff check src tests

backend-typecheck: ## Type-check backend (mypy)
	cd $(BACKEND) && uv run mypy --explicit-package-bases src

backend-migrate: ## Apply database migrations
	cd $(BACKEND) && uv run alembic -c alembic/alembic.ini upgrade head

# ── Frontend ──────────────────────────────────────────────────────────────────
frontend-install: ## Install frontend dependencies
	cd $(FRONTEND) && npm ci

frontend-lint: ## Lint frontend
	cd $(FRONTEND) && npm run lint

frontend-typecheck: ## Type-check frontend
	cd $(FRONTEND) && npx tsc --noEmit

frontend-build: ## Production build of the frontend
	cd $(FRONTEND) && npm run build

# ── Aggregates ────────────────────────────────────────────────────────────────
test: backend-test ## Run all tests

lint: backend-lint frontend-lint ## Lint everything

typecheck: backend-typecheck frontend-typecheck ## Type-check everything

# ── Local stack ───────────────────────────────────────────────────────────────
up: ## Start the local stack (docker compose)
	$(COMPOSE) up -d

down: ## Stop the local stack
	$(COMPOSE) down

logs: ## Tail stack logs
	$(COMPOSE) logs -f
