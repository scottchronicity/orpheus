# Orpheus GPS Service - Makefile

# Load local overrides from .env if present
-include .env
export

# -- Component identity ------------------------------------------------------
SERVICE_NAME := orpheus-gps
DEPLOY_ROOT  := /opt/orpheus/services/$(SERVICE_NAME)

# -- Shared infrastructure ---------------------------------------------------
include ../../make/common_python.mk
include ../../make/common_lint.mk
include ../../make/common_service.mk
include ../../make/common_deploy.mk

# -- Phony declarations (component-specific only) ----------------------------
.PHONY: help install run test coverage clean dry-run update

help:
	@echo "Orpheus GPS Service"
	@echo ""
	@echo "Local development (no sudo):"
	@echo "  make install          Install dependencies"
	@echo "  make run              Run in development mode"
	@echo "  make test             Run Python tests"
	@echo "  make coverage         Run tests with coverage report"
	@echo "  make lint             Run static code analysis"
	@echo "  make format           Format code with ruff"
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

install: $(VENV)/bin/activate
	@echo "Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -e ../../platform/orpheus-common
	$(PIP) install -r ../../platform/orpheus-common/requirements.txt
	$(PIP) install -r requirements.txt
	$(PIP) install -e .
	@echo "Installing dev dependencies..."
	$(PIP) install ruff pytest pytest-cov pytest-asyncio
	@echo "✓ Installation complete"

run: check-deps
	@echo "Starting GPS service in development mode..."
	$(PYTHON) -m orpheus_gps.main

test: check-deps
	@echo "Running tests..."
	$(PYTEST) tests/ -v

coverage: check-deps
	@echo "Running tests with coverage..."
	$(PYTEST) tests/ -v --cov=orpheus_gps --cov-report=term-missing --cov-report=html

clean:
	@echo "Cleaning build artifacts..."
	rm -rf $(VENV)
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	@echo "✓ Clean complete"

dry-run: check-deps
	@echo "Validating Python environment and imports..."
	$(PYTHON) -c "import sys; print(f'Python {sys.version}')"
	$(PYTHON) -c "import orpheus_gps; print('✓ orpheus_gps package imports successfully')"
	$(PYTHON) -c "import orpheus_common; print('✓ orpheus_common imports successfully')"
	$(PYTHON) -c "import pynmea2; print('✓ pynmea2 imports successfully')"
	$(PYTHON) -c "import serial; print('✓ pyserial imports successfully')"
	@echo "✓ Dry run complete - environment is valid"

update:
	@echo "Updating $(SERVICE_NAME)..."
	git pull
	$(MAKE) install
	$(MAKE) deploy
	$(MAKE) restart
	@echo "✓ $(SERVICE_NAME) updated and restarted"
