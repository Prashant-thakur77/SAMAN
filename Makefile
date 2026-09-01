# SAMAN — Standardised Asset & Material Analysis Network
# One-command local run. Everything below works offline once dependencies are
# installed; nothing here reaches the network at runtime (spec §10).

SHELL := /bin/bash
.DEFAULT_GOAL := help

PY_VERSION  := 3.12
VENV        := backend/.venv
PY          := $(VENV)/bin/python
PIP         := $(VENV)/bin/pip
UVICORN     := $(VENV)/bin/uvicorn
PYTEST      := $(VENV)/bin/pytest

.PHONY: help setup venv deps deps-optional web-deps dev backend frontend test \
        lint build clean licenses seed seed-large pipeline demo demo-restore

help:  ## Show available targets
	@echo "SAMAN — make targets"
	@echo
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

# --- setup ---------------------------------------------------------------

setup: venv deps web-deps  ## Install everything needed for `make dev`

venv:  ## Create backend/.venv on Python 3.12 (spec §0.2)
	@if [ ! -d "$(VENV)" ]; then \
	  if command -v uv >/dev/null 2>&1; then \
	    echo "==> creating venv with uv (python $(PY_VERSION))"; \
	    uv venv --python $(PY_VERSION) $(VENV); \
	  elif command -v python$(PY_VERSION) >/dev/null 2>&1; then \
	    echo "==> creating venv with python$(PY_VERSION)"; \
	    python$(PY_VERSION) -m venv $(VENV); \
	  else \
	    echo "!! Python $(PY_VERSION) not found and uv is unavailable."; \
	    echo "!! Install uv (https://docs.astral.sh/uv/) or python$(PY_VERSION), then re-run."; \
	    exit 1; \
	  fi; \
	fi
	@$(PY) --version

deps: venv  ## Install required backend dependencies
	@if command -v uv >/dev/null 2>&1; then \
	  uv pip install --python $(PY) -r backend/requirements.txt; \
	else \
	  $(PIP) install --upgrade pip && $(PIP) install -r backend/requirements.txt; \
	fi

deps-optional: venv  ## Install splink + sentence-transformers (SAMAN runs without them)
	@if command -v uv >/dev/null 2>&1; then \
	  uv pip install --python $(PY) -r backend/requirements-optional.txt; \
	else \
	  $(PIP) install -r backend/requirements-optional.txt; \
	fi

web-deps:  ## Install frontend dependencies
	cd frontend && npm install

# --- run -----------------------------------------------------------------

dev:  ## Run backend :8000 and frontend :5173 together
	@echo "==> SAMAN dev: API http://localhost:8000/api/docs  ·  UI http://localhost:5173"
	@trap 'kill 0' EXIT INT TERM; \
	  ( cd backend && ../$(UVICORN) app.main:app --reload --port 8000 ) & \
	  ( cd frontend && npm run dev ) & \
	  wait

backend:  ## Run the API only, on :8000
	cd backend && ../$(UVICORN) app.main:app --reload --port 8000

frontend:  ## Run the UI only, on :5173
	cd frontend && npm run dev

# --- quality -------------------------------------------------------------

test:  ## Run the backend test suite
	cd backend && ../$(PYTEST) -q

lint:  ## Type-check the frontend
	cd frontend && npm run typecheck

build:  ## Production build of the frontend
	cd frontend && npm run build

# --- data & demo ---------------------------------------------------------
# These are placeholders until their milestone lands. They fail loudly rather
# than pretending to succeed (spec §10: no faked results).

seed:  ## Seed the demo dataset (~12k items, 4 CPSEs)
	cd backend && ../$(PY) -m app.cli seed --profile demo

seed-large:  ## Seed the benchmark dataset (~150k items, 6 CPSEs)
	cd backend && ../$(PY) -m app.cli seed --profile large

pipeline:  ## Run the pipeline over any unprocessed rows
	cd backend && ../$(PY) -m app.cli pipeline

demo:  ## Seed, run the pipeline, print the held-out metrics table
	@echo "!! Not built yet — needs the matching engine and metrics from M3."; exit 1

demo-restore:  ## Reset to the pre-baked demo snapshot in under 5s
	@echo "!! Not built yet — the snapshot lands in M8B (spec §8A)."; exit 1

licenses:  ## Regenerate THIRD_PARTY_LICENSES.md and fail on any GPL/AGPL dep
	@echo "!! Not built yet — license tooling lands in M8 (spec §9)."; exit 1

clean:  ## Remove build artefacts and caches (leaves data/ alone)
	rm -rf frontend/dist frontend/node_modules/.vite
	find backend -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache
