# Ride Pulse developer commands. Run `make help` for the list.

PY      ?= .venv/bin/python
NPM     := PATH="$(CURDIR)/.venv/bin:$$PATH" npm --prefix frontend
MANAGE  := $(PY) manage.py

.DEFAULT_GOAL := help
.PHONY: help setup install db-start db-stop migrate seed reset frontend frontend-dev run simulate dev test coverage lint format check docker-up docker-down history data-setup data-run data-ui

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: install db-start migrate seed frontend ## First-time setup: deps, database, demo data, front end

install: ## Create .venv (Python 3.12) and install Python + Node dependencies
	test -d .venv || uv venv --python 3.12 .venv || python3.12 -m venv .venv
	uv pip install --python $(PY) -r requirements/base.txt -r requirements/dev.txt || $(PY) -m pip install -r requirements/base.txt -r requirements/dev.txt
	$(NPM) install --no-fund --no-audit

db-start: ## Start the bundled PostgreSQL 16 on 127.0.0.1:5433
	$(PY) scripts/devdb.py start

db-stop: ## Stop the bundled PostgreSQL
	$(PY) scripts/devdb.py stop

migrate: ## Apply database migrations
	$(MANAGE) migrate

seed: ## Load demo accounts and three weeks of trip history
	$(MANAGE) seed_demo

reset: ## Wipe the database and reseed the demo
	$(MANAGE) seed_demo --reset

frontend: ## Build the React apps (served by Django at /)
	$(NPM) run build

frontend-dev: ## Vite dev server with hot reload on :5173 (proxies the API to :8000)
	$(NPM) run dev

run: ## Django (HTTP + WebSockets) on :8000
	$(MANAGE) runserver 127.0.0.1:8000

simulate: ## Bot drivers and riders + dispatch/surge jobs (run next to `make run`)
	$(MANAGE) simulate

dev: ## Server and simulator together (Ctrl+C stops both)
	trap 'kill 0' EXIT; $(MANAGE) simulate --quiet & $(MANAGE) runserver 127.0.0.1:8000

test: ## Run the test suite
	$(PY) -m pytest

e2e: ## Browser end-to-end tests (Playwright + Chromium; run `make frontend` first)
	$(PY) -m pytest -m e2e

loadtest: ## Locust load test against the running server (50 riders, 1 minute)
	$(MANAGE) loadtest_users --count 50
	LOADTEST_USERS=50 $(PY) -m locust -f tests/load/locustfile.py --host http://localhost:8000 \
		--users 50 --spawn-rate 10 --run-time 1m --headless --only-summary

coverage: ## Tests with a coverage report
	$(PY) -m pytest --cov --cov-report=term-missing:skip-covered

lint: ## Lint Python and type-check TypeScript
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(NPM) run typecheck
	$(NPM) test

format: ## Auto-format Python
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

contract: ## Refresh the API contract snapshot after a deliberate API change
	$(MANAGE) api_contract --update

check: lint test ## Everything CI runs
	$(MANAGE) makemigrations --check --dry-run
	$(MANAGE) spectacular --fail-on-warn --file /dev/null
	$(MANAGE) api_contract

docker-up: ## Full stack in Docker (Postgres, Redis, web, worker, beat, simulator)
	docker compose up --build

docker-down: ## Stop the Docker stack
	docker compose down

# --- Data platform (data/: Parquet lake, DuckDB warehouse, dbt, Dagster) -----------------------

DATA_PY := data/.venv/bin/python

history: ## Back-fill 60 days of trips in every city (stop the simulator first)
	$(MANAGE) generate_history --days 60 --trips-per-day 300

data-setup: ## Create data/.venv with DuckDB, dbt and Dagster (separate from the app)
	uv venv --python 3.12 data/.venv
	uv pip install --python $(DATA_PY) -r data/requirements.in
	cd data/dbt && ../.venv/bin/dbt parse --profiles-dir . -q

data-run: ## Run the pipeline once: extract -> dbt build + tests -> insights report -> train models
	cd data && .venv/bin/python -m pipeline.run

data-ui: ## Dagster UI at http://localhost:3000 (pipeline graph, runs, daily schedule)
	cd data && mkdir -p .dagster && DAGSTER_HOME="$$PWD/.dagster" .venv/bin/dagster dev -f orchestration/definitions.py -d . -p 3000
