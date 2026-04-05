# Makefile for Orpheus Audio Motion Detector agent

SERVICE_NAME := orpheus-agent-audio-motion
DEPLOY_ROOT  := /opt/orpheus/agents/$(SERVICE_NAME)

include ../../make/common_python.mk
include ../../make/common_lint.mk
include ../../make/common_service.mk
include ../../make/common_deploy.mk

.PHONY: help venv install reinstall run test coverage clean update dry-run

help:
	@echo "Orpheus Audio Motion Detector"
	@echo ""
	@echo "Local development (no sudo):"
	@echo "  make install          Create venv and install dependencies"
	@echo "  make reinstall        Recreate venv from scratch"
	@echo "  make run [ARGS=...]   Run agent locally (pass extra args via ARGS)"
	@echo "  make test             Execute pytest suite"
	@echo "  make coverage         Run tests with coverage report"
	@echo "  make format           Format source with ruff"
	@echo "  make lint             Run ruff lint checks"
	@echo "  make clean            Remove venv and caches"
	@echo "  make dry-run          Validate Python 3.9.5 venv + imports (no deploy)"
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
	@echo "Running agent (using unified orpheus.yaml from orpheus-common)..."
	@if [ -f .env ]; then \
		echo "Loading environment from .env..."; \
		set -a && . .env && set +a && PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_audio_motion.main $(ARGS); \
	else \
		PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_audio_motion.main $(ARGS); \
	fi

test: check-deps
	@echo "Running pytest..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v

coverage: check-deps
	@echo "Running pytest with coverage..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v --cov=orpheus_agent_audio_motion --cov-report=term-missing

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

# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------
dry-run: check-python-version
	@echo "=========================================="
	@echo "DRY-RUN: Validating Python 3.9.5 compatibility"
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
	@echo "Installing agent dependencies..."
	@$(DRYRUN_PIP_INSTALL) -r requirements.txt -q
	@echo "✓ Dependencies installed"
	@echo ""
	@echo "Validating Python version in venv..."
	@$(DRYRUN_PYTHON) -c "import sys; print('  Venv Python: ' + f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
	@echo ""
	@echo "Validating imports..."
	@$(DRYRUN_PYTHON) -c "from orpheus_common import OrpheusConfig; print('  ✓ orpheus_common.OrpheusConfig')"
	@$(DRYRUN_PYTHON) -c "import numpy; print('  ✓ numpy')"
	@$(DRYRUN_PYTHON) -c "import soundfile; print('  ✓ soundfile')"
	@PYTHONPATH=$(SRC_DIR) $(DRYRUN_PYTHON) -c "from orpheus_agent_audio_motion.config import AudioMotionConfig; print('  ✓ orpheus_agent_audio_motion.config')"
	@echo ""
	@echo "Cleaning up dry-run venv..."
	@rm -rf $(DRYRUN_VENV_PATH)
	@echo ""
	@echo "=========================================="
	@echo "✅ DRY-RUN PASSED: Python 3.9.5 compatible"
	@echo "=========================================="
