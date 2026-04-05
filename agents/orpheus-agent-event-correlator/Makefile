# Makefile for Orpheus Event Correlator Agent

SERVICE_NAME := orpheus-agent-event-correlator
DEPLOY_ROOT  := /opt/orpheus/agents/$(SERVICE_NAME)

include ../../make/common_python.mk
include ../../make/common_lint.mk
include ../../make/common_service.mk
include ../../make/common_deploy.mk

.PHONY: help venv install reinstall run test coverage clean update

help:
	@echo "Orpheus Event Correlator"
	@echo ""
	@echo "Local development (no sudo):"
	@echo "  make install          Create venv and install dependencies"
	@echo "  make reinstall        Recreate venv from scratch"
	@echo "  make run [ARGS=...]   Run agent locally (pass extra args via ARGS)"
	@echo "  make test             Execute pytest suite"
	@echo "  make coverage         Run tests with coverage"
	@echo "  make format           Format source with ruff"
	@echo "  make lint             Run ruff lint checks"
	@echo "  make clean            Remove venv and caches"
	@echo ""
	@echo "Edge deployment (sudo required):"
	@echo "  make install-service  Install systemd unit"
	@echo "  make start            Start systemd service"
	@echo "  make stop             Stop systemd service"
	@echo "  make restart          Restart systemd service"
	@echo "  make status           Show service status"
	@echo "  make logs             Tail service logs (follow)"
	@echo "  make update           git pull + reinstall + restart"

venv: $(VENV)/bin/activate

install: venv
	@if [ "$$(id -u)" = "0" ]; then \
		echo "❌ ERROR: Do not run 'make install' as root/sudo"; \
		echo "   This will create root-owned files in venv/"; \
		echo "   Run without sudo instead."; \
		exit 1; \
	fi
	@echo "Installing dependencies..."
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt
	@echo "Dependencies installed"

reinstall:
	@if [ "$$(id -u)" = "0" ]; then \
		echo "❌ ERROR: Do not run 'make reinstall' as root/sudo"; \
		echo "   Run without sudo instead."; \
		exit 1; \
	fi
	$(MAKE) clean
	$(MAKE) install

run: check-deps
	@echo "Running agent..."
	@if [ -f .env ]; then \
		echo "Loading environment from .env..."; \
		set -a && . .env && set +a && PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_event_correlator.main $(ARGS); \
	else \
		PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_event_correlator.main $(ARGS); \
	fi

test: check-deps
	@echo "Running pytest..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v

coverage: check-deps
	@echo "Running pytest with coverage..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v --cov=orpheus_agent_event_correlator --cov-report=term-missing

clean:
	@echo "Cleaning project..."
	@rm -rf $(VENV)
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name '*.pyc' -delete 2>/dev/null || true
	@echo "✓ Clean complete"

update:
	@echo "Updating $(SERVICE_NAME)..."
	git pull
	$(MAKE) install
	$(MAKE) deploy
	$(MAKE) restart
	@echo "✓ $(SERVICE_NAME) updated and restarted"
