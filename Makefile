# deli — Makefile for common development and CI tasks
# Usage: make [target]

PYTHON ?= python3
VENV ?= .venv
VENV_BIN = $(VENV)/bin
PIP = $(VENV_BIN)/pip
PYTEST = $(VENV_BIN)/pytest
RUFF = $(VENV_BIN)/ruff

.PHONY: help install install-dev test test-verbose lint format check build clean run-example venv docker-build

help:
	@echo "deli — Makefile targets"
	@echo ""
	@echo "  make install       Install package (editable) and runtime deps"
	@echo "  make install-dev   Install with dev deps (pytest, ruff)"
	@echo "  make venv         Create virtualenv at .venv"
	@echo "  make test         Run pytest"
	@echo "  make test-verbose Run pytest with -v --tb=short"
	@echo "  make lint         Ruff check (deli/ tests/)"
	@echo "  make format       Ruff format"
	@echo "  make check        Lint + format check (CI-style)"
	@echo "  make build        Build wheel and sdist"
	@echo "  make clean        Remove build artifacts and caches"
	@echo "  make run-example  Quick load test with examples/"
	@echo "  make docker-build Build Docker image"
	@echo ""

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv
	$(PIP) install -e .

install-dev: venv
	$(PIP) install -e ".[dev]"

test:
	$(PYTEST) tests/ -q --tb=short

test-verbose:
	$(PYTEST) tests/ -v --tb=short

lint:
	$(RUFF) check deli/ tests/

format:
	$(RUFF) format deli/ tests/

check: lint
	$(RUFF) format --check deli/ tests/

build:
	$(PYTHON) -m pip install build --quiet
	$(PYTHON) -m build

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf deli.egg-info
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

run-example:
	$(VENV_BIN)/deli -m https://httpbin.org/get -f examples/config.yaml -o report.html --no-live

docker-build:
	docker build -t deli:latest .
