# Makefile for Orpheus Audio Events Detection agent

SERVICE_NAME := orpheus-agent-audio-events
DEPLOY_ROOT  := /opt/orpheus/agents/$(SERVICE_NAME)

include ../../make/common_python.mk
include ../../make/common_lint.mk
include ../../make/common_service.mk
include ../../make/common_deploy.mk

.PHONY: help venv install reinstall run test coverage clean update dry-run \
        download-models check-models

help:
	@echo "Orpheus Audio Events Detection"
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
	@echo "  make download-models  Download PANNs Cnn14 SED checkpoint to \$$ORPHEUS_DATA_ROOT/models/"
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
		set -a && . .env && set +a && PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_audio_events.main $(ARGS); \
	else \
		PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_audio_events.main $(ARGS); \
	fi

test: check-deps
	@echo "Running pytest..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v

coverage: check-deps
	@echo "Running pytest with coverage..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v --cov=orpheus_agent_audio_events --cov-report=term-missing

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
	@# Provision the PANNs SED checkpoint into $ORPHEUS_DATA_ROOT/models/ if
	@# it isn't there yet. Reuses download-models (idempotent — skips when
	@# already present) so the model lands automatically on deploy instead
	@# of being copied by hand. Defaults the data root to the Jetson path and
	@# is non-fatal: a model hiccup must never block the code restart.
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
	@PYTHONPATH=$(SRC_DIR) $(DRYRUN_PYTHON) -c "from orpheus_agent_audio_events.config import AudioEventsConfig; print('  ✓ orpheus_agent_audio_events.config')"
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

# PANNs Cnn14_DecisionLevelMax checkpoint (Kong et al., 2020, MIT licensed).
# Zenodo permanent URL — the canonical release.
PANNS_SED_URL := https://zenodo.org/record/3987831/files/Cnn14_DecisionLevelMax_mAP%3D0.385.pth?download=1
PANNS_SED_FILE := panns_cnn14_decision_level_max.pth

# In-repo Git-LFS copy of the same checkpoint. The Makefile lives at
# agents/orpheus-agent-audio-events/, so the repo root is two levels up.
# CURDIR is the agent dir whether invoked directly or via `make -C` from root.
PANNS_SED_ARTIFACT := $(CURDIR)/../../artifacts/models/$(PANNS_SED_FILE)

download-models:
	@echo "Downloading PANNs Cnn14 SED checkpoint..."
	@if [ -z "$$ORPHEUS_DATA_ROOT" ]; then \
		echo "❌ ERROR: ORPHEUS_DATA_ROOT environment variable not set"; \
		echo "   Set it to your data directory:"; \
		echo "   export ORPHEUS_DATA_ROOT=~/data/orpheus  # Laptop"; \
		echo "   export ORPHEUS_DATA_ROOT=/data/orpheus   # Jetson"; \
		exit 1; \
	fi
	@echo "Using ORPHEUS_DATA_ROOT: $$ORPHEUS_DATA_ROOT"
	@mkdir -p "$$ORPHEUS_DATA_ROOT/models"
	@dest="$$ORPHEUS_DATA_ROOT/models/$(PANNS_SED_FILE)"; \
	artifact="$(PANNS_SED_ARTIFACT)"; \
	if [ -f "$$dest" ]; then \
		echo "✓ $(PANNS_SED_FILE) already provisioned, skipping (already exists)"; \
	elif [ -f "$$artifact" ] && [ "$$(wc -c < "$$artifact")" -gt 10485760 ]; then \
		echo "Copying from in-repo LFS artifact: $$artifact"; \
		cp "$$artifact" "$$dest"; \
		echo "✓ $(PANNS_SED_FILE) copied from in-repo LFS artifact"; \
	elif [ -f "$$artifact" ]; then \
		echo "⚠️  In-repo artifact present but not materialized (LFS pointer):"; \
		echo "     $$artifact"; \
		echo "   To use the pinned local copy, run:"; \
		echo "     git lfs pull --include=\"artifacts/models/$(PANNS_SED_FILE)\""; \
		echo "   Falling back to Zenodo download..."; \
		curl -L -o "$$dest" "$(PANNS_SED_URL)"; \
		echo "✓ $(PANNS_SED_FILE) downloaded"; \
	else \
		echo "Downloading from Zenodo..."; \
		curl -L -o "$$dest" "$(PANNS_SED_URL)"; \
		echo "✓ $(PANNS_SED_FILE) downloaded"; \
	fi
	@echo ""
	@echo "✅ Model download complete"

check-models:
	@echo "Checking PANNs SED models..."
	@if [ -z "$$ORPHEUS_DATA_ROOT" ]; then \
		echo "❌ ERROR: ORPHEUS_DATA_ROOT environment variable not set"; \
		exit 1; \
	fi
	@echo "Using ORPHEUS_DATA_ROOT: $$ORPHEUS_DATA_ROOT"
	@echo ""
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/$(PANNS_SED_FILE)" ]; then \
		SIZE=$$(du -h "$$ORPHEUS_DATA_ROOT/models/$(PANNS_SED_FILE)" | cut -f1); \
		echo "✓ $(PANNS_SED_FILE) present ($$SIZE)"; \
	else \
		echo "✗ $(PANNS_SED_FILE) missing"; \
		echo "  Run 'make download-models' to fetch the PANNs SED checkpoint."; \
	fi
