# Orpheus UI Backend - Python FastAPI
# This Makefile manages the Python backend for orpheus_ui

# Load local overrides from .env if present
-include .env
export

# -- Shared infrastructure ---------------------------------------------------
include ../../../make/common_python.mk
include ../../../make/common_lint.mk

# -- Extra tool paths --------------------------------------------------------
UVICORN ?= $(PYTHON_DIR)uvicorn

# -- Phony declarations (component-specific only) ----------------------------
.PHONY: help install run test coverage clean

help:
	@echo "Orpheus UI Backend Makefile"
	@echo ""
	@echo "Development:"
	@echo "  make install    - Install Python dependencies"
	@echo "  make run        - Run FastAPI backend (port 8082)"
	@echo "  make test       - Run pytest tests"
	@echo "  make coverage   - Run tests with coverage"
	@echo "  make lint       - Run ruff linting"
	@echo "  make format     - Format code with ruff"
	@echo "  make check      - Check formatting without changes"
	@echo "  make clean      - Remove venv and cache"

install: check-deps
	@if [ "$$(id -u)" = "0" ]; then \
		echo "❌ ERROR: Do not run 'make install' as root/sudo"; \
		exit 1; \
	fi
	@echo "Installing Python dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .
	@echo "✓ Python dependencies installed"

run: check-deps
	@echo "Starting Orpheus UI backend on http://0.0.0.0:8082"
	@if [ -z "$$ORPHEUS_CONFIG_PATH" ] && [ ! -f "/opt/orpheus/config/orpheus.yaml" ]; then \
		export ORPHEUS_CONFIG_PATH="../../../config/orpheus.yaml"; \
	fi; \
	$(UVICORN) orpheus_ui.main:app --host 0.0.0.0 --port 8082 --reload --no-access-log

test: check-deps
	@echo "Running tests..."
	$(PYTHON) -m pytest tests/ -v

coverage: check-deps
	@echo "Running tests with coverage..."
	$(PYTHON) -m pytest tests/ -v --cov=src --cov-report=term-missing

clean:
	rm -rf $(VENV)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@echo "✓ Cleaned build artifacts"
