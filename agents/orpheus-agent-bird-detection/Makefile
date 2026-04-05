# Makefile for Orpheus Bird Detection agent

SERVICE_NAME := orpheus-agent-bird-detection
DEPLOY_ROOT  := /opt/orpheus/agents/$(SERVICE_NAME)

include ../../make/common_python.mk
include ../../make/common_lint.mk
include ../../make/common_service.mk
include ../../make/common_deploy.mk

.PHONY: help venv install reinstall run test coverage clean update dry-run \
        download-labels download-models pull-models check-models

help:
	@echo "Orpheus Bird Detection"
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
	@echo "  make dry-run          Validate Python 3.9.5 venv + imports (no deploy)"
	@echo "  make download-models  Download BirdNET models to \$$ORPHEUS_DATA_ROOT/models/"
	@echo "  make pull-models      Pull models from Git LFS"
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
		set -a && . .env && set +a && PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_bird_detection.main $(ARGS); \
	else \
		PYTHONPATH=$(SRC_DIR) $(PYTHON) -m orpheus_agent_bird_detection.main $(ARGS); \
	fi

test: check-deps
	@echo "Running pytest..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v

coverage: check-deps
	@echo "Running pytest with coverage..."
	@PYTHONPATH=$(SRC_DIR) $(PYTEST) $(TEST_DIR) -v --cov=orpheus_agent_bird_detection --cov-report=term-missing

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
	@PYTHONPATH=$(SRC_DIR) $(DRYRUN_PYTHON) -c "from orpheus_agent_bird_detection.config import BirdDetectionConfig; print('  ✓ orpheus_agent_bird_detection.config')"
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

download-labels:
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/labels.json" ]; then \
		echo "✓ labels.json already exists, skipping download"; \
	else \
		echo "Downloading BirdNET labels from Hugging Face..."; \
		curl -L -o /tmp/labels.txt "https://huggingface.co/justinchuby/BirdNET-onnx/raw/main/BirdNET_GLOBAL_6K_V2.4_Labels.txt"; \
		$(PYTHON_SYSTEM) -c "import json; labels = [line.strip() for line in open('/tmp/labels.txt') if line.strip()]; json.dump(labels, open('$$ORPHEUS_DATA_ROOT/models/labels.json', 'w'), indent=2)"; \
		rm /tmp/labels.txt; \
		echo "✓ labels.json created"; \
	fi

download-models:
	@echo "Downloading BirdNET models..."
	@if [ -z "$$ORPHEUS_DATA_ROOT" ]; then \
		echo "❌ ERROR: ORPHEUS_DATA_ROOT environment variable not set"; \
		echo "   Set it to your data directory:"; \
		echo "   export ORPHEUS_DATA_ROOT=~/data/orpheus  # Laptop"; \
		echo "   export ORPHEUS_DATA_ROOT=/data/orpheus   # Jetson"; \
		exit 1; \
	fi
	@echo "Using ORPHEUS_DATA_ROOT: $$ORPHEUS_DATA_ROOT"
	@mkdir -p "$$ORPHEUS_DATA_ROOT/models"
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/birdnet.onnx" ]; then \
		echo "✓ birdnet.onnx already exists, skipping download"; \
	else \
		echo "Downloading BirdNET ONNX model (FP32)..."; \
		curl -L -o "$$ORPHEUS_DATA_ROOT/models/birdnet.onnx" "https://huggingface.co/onnx-community/BirdNET/resolve/main/model.onnx"; \
		echo "✓ birdnet.onnx downloaded"; \
	fi
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/birdnet_meta.tflite" ]; then \
		echo "✓ birdnet_meta.tflite already exists, skipping download"; \
	else \
		echo "Downloading BirdNET Meta Model (TFLite FP16)..."; \
		echo "   Source: BirdNET-Pi community repository (mcguirepr89/BirdNET-Pi)"; \
		curl -L -o "$$ORPHEUS_DATA_ROOT/models/birdnet_meta.tflite" "https://github.com/mcguirepr89/BirdNET-Pi/raw/main/model/BirdNET_GLOBAL_6K_V2.4_MData_Model_FP16.tflite"; \
		echo "✓ birdnet_meta.tflite downloaded"; \
	fi
	$(MAKE) download-labels
	@echo ""
	@echo "✅ Model download complete"

pull-models:
	@echo "Pulling models from Git LFS..."
	@git lfs pull
	@echo "✅ Models pulled from Git LFS. Check in <repo_root>/artifacts/models/ for the files."
	@echo "If you want to use them, copy them to <ORPHEUS_DATA_ROOT>/models/: $$ORPHEUS_DATA_ROOT/models"

check-models:
	@echo "Checking BirdNET models..."
	@if [ -z "$$ORPHEUS_DATA_ROOT" ]; then \
		echo "❌ ERROR: ORPHEUS_DATA_ROOT environment variable not set"; \
		echo "   Set it to your data directory:"; \
		echo "   export ORPHEUS_DATA_ROOT=~/data/orpheus  # Laptop"; \
		echo "   export ORPHEUS_DATA_ROOT=/data/orpheus   # Jetson"; \
		exit 1; \
	fi
	@echo "Using ORPHEUS_DATA_ROOT: $$ORPHEUS_DATA_ROOT"
	@echo ""
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/birdnet.onnx" ]; then \
		SIZE=$$(du -h "$$ORPHEUS_DATA_ROOT/models/birdnet.onnx" | cut -f1); \
		echo "✓ birdnet.onnx ($$SIZE)"; \
	else \
		echo "✗ birdnet.onnx (missing)"; \
	fi
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/birdnet_meta.tflite" ]; then \
		SIZE=$$(du -h "$$ORPHEUS_DATA_ROOT/models/birdnet_meta.tflite" | cut -f1); \
		echo "✓ birdnet_meta.tflite ($$SIZE)"; \
	else \
		echo "✗ birdnet_meta.tflite (missing)"; \
	fi
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/labels.json" ]; then \
		SIZE=$$(du -h "$$ORPHEUS_DATA_ROOT/models/labels.json" | cut -f1); \
		COUNT=$$($(PYTHON_SYSTEM) -c "import json; print(len(json.load(open('$$ORPHEUS_DATA_ROOT/models/labels.json'))))"); \
		echo "✓ labels.json ($$SIZE, $$COUNT species)"; \
	else \
		echo "✗ labels.json (missing)"; \
	fi
	@echo ""
	@if [ -f "$$ORPHEUS_DATA_ROOT/models/birdnet.onnx" ] && [ -f "$$ORPHEUS_DATA_ROOT/models/birdnet_meta.tflite" ] && [ -f "$$ORPHEUS_DATA_ROOT/models/labels.json" ]; then \
		echo "✅ All models present"; \
	else \
		echo "❌ Some models missing - run 'make download-models'"; \
	fi
