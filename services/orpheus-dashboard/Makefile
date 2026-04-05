# Orpheus Dashboard Service - Makefile

# Load local overrides from .env if present
-include .env
export

# -- Component identity ------------------------------------------------------
SERVICE_NAME       := orpheus-dashboard
DEPLOY_ROOT        := /opt/orpheus/dashboard
DEPLOY_EXTRA_FILES := pyproject.toml requirements.txt setup.py

# -- Shared infrastructure ---------------------------------------------------
include ../../make/common_python.mk
# NOTE: common_lint.mk intentionally NOT included — dashboard has custom
#       lint/format/check targets that also run prettier for HTML/JS/CSS.
include ../../make/common_service.mk
include ../../make/common_deploy.mk

# -- Extra tool paths --------------------------------------------------------
UVICORN  ?= $(PYTHON_DIR)uvicorn
PRETTIER ?= prettier

# -- Phony declarations (component-specific only) ----------------------------
.PHONY: help install run test coverage lint format check clean dry-run update

help:
	@echo "Orpheus Dashboard"
	@echo ""
	@echo "Local development (no sudo):"
	@echo "  make install          Install dependencies"
	@echo "  make run              Run in development mode"
	@echo "  make test             Run Python tests"
	@echo "  make coverage         Run tests with coverage"
	@echo "  make lint             Run static code analysis"
	@echo "  make format           Format code (Python, HTML, JS)"
	@echo "  make check            Check code formatting without changes"
	@echo "  make clean            Remove build artifacts"
	@echo "  make dry-run          Validate Python 3.9+ venv + imports (no deploy)"
	@echo ""
	@echo "Edge deployment (sudo required):"
	@echo "  make install-service  Install as systemd service"
	@echo "  make start            Start systemd service"
	@echo "  make stop             Stop systemd service"
	@echo "  make restart          Restart systemd service"
	@echo "  make status           Show service status"
	@echo "  make logs             Tail service logs (follow)"
	@echo "  make update           git pull + reinstall + restart"
	@echo ""
	@echo "Configuration:"
	@echo "  Create .env file to override Python paths"
	@echo "  Currently using: $(PYTHON_SYSTEM) for venv creation"

install: check-deps
	@if [ "$$(id -u)" = "0" ]; then \
		echo "❌ ERROR: Do not run 'make install' as root/sudo"; \
		echo "   This will create root-owned files in your dev environment"; \
		echo "   Run without sudo instead."; \
		exit 1; \
	fi
	@echo "Installing dependencies with $(PIP)..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .
	@echo "✓ Dependencies installed"

run: check-deps
	@echo "Starting Orpheus Dashboard (legacy) on http://0.0.0.0:8081"
	@echo "Using Python: $(PYTHON)"
	@if [ -z "$$ORPHEUS_CONFIG_PATH" ] && [ ! -f "/opt/orpheus/config/orpheus.yaml" ]; then \
		export ORPHEUS_CONFIG_PATH="../../config/orpheus.yaml"; \
	fi; \
	$(UVICORN) orpheus_dashboard.main:app --host 0.0.0.0 --port 8081 --reload

test: check-deps
	@echo "Running tests with: $(PYTHON)"
	$(PYTHON) -m pytest tests/ -v

coverage: check-deps
	@echo "Running tests with coverage..."
	$(PYTHON) -m pytest tests/ -v --cov=src --cov-report=term-missing

lint: check-deps
	@echo "Running static code analysis..."
	@echo "Linting Python code with ruff..."
	@FAILED=0; \
	$(RUFF) check src/ tests/ || FAILED=1; \
	if [ $$FAILED -ne 0 ]; then \
		echo "❌ Linting found errors"; \
		exit 1; \
	fi; \
	echo "✓ Static analysis complete"

format: check-deps
	@echo "Formatting code..."
	@echo "Formatting Python code with ruff..."
	@FAILED=0; \
	$(RUFF) format src/ tests/ || FAILED=1; \
	echo "Fixing Python code with ruff..."; \
	$(RUFF) check --fix src/ tests/ || FAILED=1; \
	echo "Formatting HTML and JavaScript with prettier..."; \
	$(PRETTIER) --write "src/orpheus_dashboard/static/**/*.{html,js,css}" || FAILED=1; \
	if [ $$FAILED -ne 0 ]; then \
		echo "❌ Formatting completed with errors"; \
		exit 1; \
	fi; \
	echo "✓ Code formatting complete"

check: check-deps
	@echo "Checking code formatting..."
	@echo "Checking Python code..."
	$(RUFF) format --check src/
	$(RUFF) check src/
	@echo "Checking HTML and JavaScript..."
	$(PRETTIER) --check "static/**/*.{html,js,css}"
	@echo "✓ All code is properly formatted"

clean:
	rm -rf $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	@echo "✓ Cleaned build artifacts"

# ---------------------------------------------------------------------------
# Dry-run: Create a test venv with Python 3.9+, install deps, validate imports
# ---------------------------------------------------------------------------
dry-run: check-python-version
	@echo "=========================================="
	@echo "DRY-RUN: Validating Python 3.9+ compatibility"
	@echo "=========================================="
	@echo ""
	@echo "Creating dry-run venv at $(DRYRUN_VENV_PATH)..."
	@rm -rf $(DRYRUN_VENV_PATH)
	@$(CREATE_DRYRUN_VENV)
	@echo "✓ Venv created"
	@echo ""
	@echo "Installing orpheus-common first..."
	@$(DRYRUN_PIP_INSTALL) --upgrade pip -q
	@$(DRYRUN_PIP_INSTALL) -e ../../platform/orpheus-common -q
	@echo "✓ orpheus-common installed"
	@echo ""
	@echo "Installing dashboard dependencies..."
	@$(DRYRUN_PIP_INSTALL) -r requirements.txt -q
	@$(DRYRUN_PIP_INSTALL) -e . -q
	@echo "✓ Dependencies installed"
	@echo ""
	@echo "Validating Python version in venv..."
	@$(DRYRUN_PYTHON) -c "import sys; print('  Venv Python: ' + f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
	@echo ""
	@echo "Validating imports..."
	@$(DRYRUN_PYTHON) -c "from orpheus_common import OrpheusConfig; print('  ✓ orpheus_common.OrpheusConfig')"
	@$(DRYRUN_PYTHON) -c "from fastapi import FastAPI; print('  ✓ fastapi.FastAPI')"
	@$(DRYRUN_PYTHON) -c "import uvicorn; print('  ✓ uvicorn')"
	@$(DRYRUN_PYTHON) -c "from orpheus_dashboard.main import app; print('  ✓ orpheus_dashboard.main.app')"
	@echo ""
	@echo "Cleaning up dry-run venv..."
	@rm -rf $(DRYRUN_VENV_PATH)
	@echo ""
	@echo "=========================================="
	@echo "✅ DRY-RUN PASSED: Python 3.9+ compatible"
	@echo "=========================================="

update:
	@echo "Updating $(SERVICE_NAME)..."
	git pull
	$(MAKE) install
	$(MAKE) deploy
	$(MAKE) restart
	@echo "✓ $(SERVICE_NAME) updated and restarted"
