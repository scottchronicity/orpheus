# Makefile for Orpheus Crow Detection agent

SERVICE_NAME := orpheus-agent-crow-detection
DEPLOY_ROOT  := /opt/orpheus/agents/$(SERVICE_NAME)

include ../../make/common_python.mk
include ../../make/common_lint.mk
include ../../make/common_service.mk
include ../../make/common_deploy.mk

.PHONY: help venv install reinstall run test coverage clean update dry-run \
        download-models check-models

help:
	@echo "Orpheus Crow Detection"
	@echo ""
	@echo "Local development (no sudo):"
	@echo "  make install          Create venv and install dependencies"
	@echo "  make reinstall        Recreate venv from scratch"
	@echo "  make run [ARGS=...]   Run agent locally (pass extra args via ARGS)"
	@echo "  make test             Execute pytest suite"
	@echo "  make coverage         Run pytest with coverage report"
	@echo "  make format           Format source with ruff"
	@echo "  make lint             Run ruff lint checks"
	@echo "  make clean            Remove venv and caches"
	@echo "  make dry-run          Validate Python 3.9.5 venv + imports (no deploy)"
	@echo "  make download-models  Download AVES crow models to \$$ORPHEUS_DATA_ROOT/models/"
	@echo "  make check-models     Verify which models are present"
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
# this version constraint is to avoid pip 24.1+ which has some issues with fairseq
	@$(PIP) install "pip==24.0"
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
		set -a && . .env && set +a && PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_crow_detection.main $(ARGS); \
	else \
		PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_crow_detection.main $(ARGS); \
	fi

test: check-deps
	@echo "Running pytest (unit; e2e excluded — see test-e2e)..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v -m "not e2e"

coverage: check-deps
	@echo "Running pytest with coverage..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v -m "not e2e" --cov=orpheus_agent_crow_detection --cov-report=term-missing

test-e2e: check-deps
	@echo "Running e2e bus-contract oracle (needs a broker; pair with 'make sim-up')..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v -m e2e

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
	@# Provision the AVES + crow-classifier checkpoints into
	@# $ORPHEUS_DATA_ROOT/models/ if they aren't there yet. Reuses
	@# download-models (idempotent — skips when present) so models land
	@# automatically on deploy instead of being copied by hand. Defaults the
	@# data root to the Jetson path and is non-fatal: a model hiccup must
	@# never block the code restart.
	@ORPHEUS_DATA_ROOT="$${ORPHEUS_DATA_ROOT:-/data/orpheus}" $(MAKE) download-models \
		|| echo "⚠️  Model provisioning skipped — run 'make download-models' manually"
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
	@$(DRYRUN_PIP_INSTALL) "pip<24.1" -q
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
	@PYTHONPATH=$(SRC_DIR) $(DRYRUN_PYTHON) -c "from orpheus_agent_crow_detection.config import CrowDetectionConfig; print('  ✓ orpheus_agent_crow_detection.config')"
	@echo ""
	@echo "Cleaning up dry-run venv..."
	@rm -rf $(DRYRUN_VENV_PATH)
	@echo ""
	@echo "=========================================="
	@echo "✅ DRY-RUN PASSED: Python 3.9.5 compatible"
	@echo "=========================================="

# ---------------------------------------------------------------------------
# Model management targets
# ---------------------------------------------------------------------------

download-models:
	@echo "Downloading AVES crow detection models..."
	@if [ -z "$$ORPHEUS_DATA_ROOT" ]; then \
		echo "❌ ERROR: ORPHEUS_DATA_ROOT environment variable not set"; \
		echo "   Set it to your data directory:"; \
		echo "   export ORPHEUS_DATA_ROOT=~/data/orpheus  # Laptop"; \
		echo "   export ORPHEUS_DATA_ROOT=/data/orpheus   # Jetson"; \
		exit 1; \
	fi
	@echo "Using ORPHEUS_DATA_ROOT: $$ORPHEUS_DATA_ROOT"
	@mkdir -p "$$ORPHEUS_DATA_ROOT/models"
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/aves-base-bio.pt" ]; then \
		echo "✓ aves-base-bio.pt already exists, skipping download"; \
	else \
		echo "Downloading AVES embedder model..."; \
		curl -L -o "$$ORPHEUS_DATA_ROOT/models/aves-base-bio.pt" "https://huggingface.co/tkinghorn/aves/resolve/main/aves-base-bio.pt"; \
		echo "✓ aves-base-bio.pt downloaded"; \
	fi
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/mt_70.pt" ]; then \
		echo "✓ mt_70.pt already exists, skipping download"; \
	else \
		echo "Downloading crow classifier model..."; \
		curl -L -o "$$ORPHEUS_DATA_ROOT/models/mt_70.pt" "https://huggingface.co/tkinghorn/crow-vocalizations/resolve/main/mt_70.pt"; \
		echo "✓ mt_70.pt downloaded"; \
	fi
	@echo ""
	@echo "✅ Model download complete"

check-models:
	@echo "Checking AVES crow detection models..."
	@if [ -z "$$ORPHEUS_DATA_ROOT" ]; then \
		echo "❌ ERROR: ORPHEUS_DATA_ROOT environment variable not set"; \
		echo "   Set it to your data directory:"; \
		echo "   export ORPHEUS_DATA_ROOT=~/data/orpheus  # Laptop"; \
		echo "   export ORPHEUS_DATA_ROOT=/data/orpheus   # Jetson"; \
		exit 1; \
	fi
	@echo "Using ORPHEUS_DATA_ROOT: $$ORPHEUS_DATA_ROOT"
	@echo ""
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/aves-base-bio.pt" ]; then \
		SIZE=$$(du -h "$$ORPHEUS_DATA_ROOT/models/aves-base-bio.pt" | cut -f1); \
		echo "✓ aves-base-bio.pt ($$SIZE)"; \
	else \
		echo "✗ aves-base-bio.pt (missing)"; \
	fi
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/mt_70.pt" ]; then \
		SIZE=$$(du -h "$$ORPHEUS_DATA_ROOT/models/mt_70.pt" | cut -f1); \
		echo "✓ mt_70.pt ($$SIZE)"; \
	else \
		echo "✗ mt_70.pt (missing)"; \
	fi
	@echo ""
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/aves-base-bio.pt" ] && [ -f "$$ORPHEUS_DATA_ROOT/models/mt_70.pt" ]; then \
		echo "✅ All models present"; \
	else \
		echo "❌ Some models missing - run 'make download-models'"; \
	fi
