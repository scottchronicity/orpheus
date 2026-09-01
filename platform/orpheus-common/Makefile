# Orpheus Common Library - Makefile

# Load local overrides from .env if present
-include .env
export

.PHONY: help install install-dev test clean lint format check deploy-config update force-update-config install-service dry-run

# -- Component identity ------------------------------------------------------
SERVICE_NAME := orpheus-common

# -- Component-specific configuration ----------------------------------------
CONFIG_INSTALL_DIR ?= /opt/orpheus/config

# -- Shared infrastructure ---------------------------------------------------
include ../../make/common_python.mk

help:
	@echo "Orpheus Common Library Makefile"
	@echo ""
	@echo "Development:"
	@echo "  make install       - Install package and dependencies"
	@echo "  make install-dev   - Install with development dependencies"
	@echo "  make test          - Run tests"
	@echo "  make lint          - Run static code analysis"
	@echo "  make format        - Format code"
	@echo "  make clean         - Remove build artifacts"
	@echo "  make dry-run       - Validate Python 3.9.5 venv + imports (no deploy)"
	@echo ""
	@echo "Deployment:"
	@echo "  make install-service - Install orpheus-common platform library (preserves config)"
	@echo "  make deploy-config   - Deploy config files (preserves existing config)"
	@echo "  make update          - Reinstall library + FORCE update config + restart services"
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
	@echo "Installing orpheus-common and dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .
	@echo "✓ Package installed in editable mode"

install-dev: check-deps
	@echo "Installing orpheus-common with development dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt
	$(PIP) install -e .
	@echo "✓ Package installed in development mode"

test: check-deps
	@echo "Running tests..."
	$(PYTEST) tests/ -v
	@echo "✓ Tests complete"

coverage: check-deps
	@echo "Running tests with coverage..."
	$(PYTEST) tests/ -v --cov=orpheus_common --cov-report=term-missing
	@echo "✓ Coverage complete"

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
	@echo "Formatting and fixing code..."
	@echo "Formatting Python code with ruff..."
	@FAILED=0; \
	$(RUFF) format src/ tests/ || FAILED=1; \
	echo "Fixing Python code with ruff..."; \
	$(RUFF) check --fix src/ tests/ || FAILED=1; \
	if [ $$FAILED -ne 0 ]; then \
		echo "❌ Formatting completed with errors"; \
		exit 1; \
	fi; \
	echo "✓ Code formatting complete"

check: check-deps
	@echo "Checking code formatting..."
	@command -v ruff >/dev/null 2>&1 && ruff check src/ || echo "⚠ ruff not installed"
	@echo "✓ Check complete"
clean:
	rm -rf $(VENV)
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	@echo "✓ Cleaned build artifacts"

install-service:
	@echo "Installing orpheus-common platform library..."
	@sudo ./systemd/install.sh
	@echo "✓ Platform library installed"

deploy-config:
	@echo "Deploying configuration files to $(CONFIG_INSTALL_DIR)..."
	@sudo mkdir -p $(CONFIG_INSTALL_DIR)
	@if [ -f ../../config/orpheus.example.yaml ]; then sudo cp ../../config/orpheus.example.yaml $(CONFIG_INSTALL_DIR)/; fi
	@if [ -f ../../config/orpheus.yaml ]; then \
		sudo cp ../../config/orpheus.yaml $(CONFIG_INSTALL_DIR)/orpheus.yaml.default; \
		if [ ! -f "$(CONFIG_INSTALL_DIR)/orpheus.yaml" ]; then \
			sudo cp ../../config/orpheus.yaml $(CONFIG_INSTALL_DIR)/orpheus.yaml; \
			echo "✓ Installed default config at $(CONFIG_INSTALL_DIR)/orpheus.yaml"; \
			echo "⚠️  Update $(CONFIG_INSTALL_DIR)/orpheus.yaml with deployment settings"; \
		else \
			echo "✓ Existing config at $(CONFIG_INSTALL_DIR)/orpheus.yaml (unchanged)"; \
			echo "✓ New default at $(CONFIG_INSTALL_DIR)/orpheus.yaml.default"; \
		fi; \
	elif [ -f "$(CONFIG_INSTALL_DIR)/orpheus.yaml" ]; then \
		echo "✓ Existing config at $(CONFIG_INSTALL_DIR)/orpheus.yaml (unchanged)"; \
	else \
		echo "❌ No orpheus.yaml found!"; \
		echo "   Copy your config: cp /your/orpheus.yaml config/orpheus.yaml (repo root)"; \
		echo "   Or copy the example: cp config/orpheus.example.yaml config/orpheus.yaml"; \
		exit 1; \
	fi
	@echo "✓ Configuration files deployed"

update: install-service force-update-config
	@echo "Restarting services to pick up new configuration..."
	@sudo systemctl restart orpheus-ui 2>/dev/null || echo "⚠ orpheus-ui not running"
	@sudo systemctl restart orpheus-agent-audio-motion 2>/dev/null || echo "⚠ orpheus-agent-audio-motion not running"
	@echo "✓ Services restarted"

force-update-config:
	@echo "⚠️  FORCE updating configuration files to $(CONFIG_INSTALL_DIR)..."
	@echo "⚠️  This will OVERWRITE your existing config!"
	@sudo mkdir -p $(CONFIG_INSTALL_DIR)
	@sudo cp config/orpheus.yaml $(CONFIG_INSTALL_DIR)/orpheus.yaml.backup-$$(date +%Y%m%d-%H%M%S)
	@sudo cp config/orpheus.yaml $(CONFIG_INSTALL_DIR)/orpheus.yaml
	@sudo cp ../../config/orpheus.example.yaml $(CONFIG_INSTALL_DIR)/
	@echo "✓ Configuration FORCE updated (backup saved)"

# Dry-run: Create a test venv with Python 3.9.5, install deps, and validate imports
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
	@echo "Installing dependencies..."
	@$(DRYRUN_PIP_INSTALL) --upgrade pip -q
	@$(DRYRUN_PIP_INSTALL) -r requirements.txt -q
	@$(DRYRUN_PIP_INSTALL) -e . -q
	@echo "✓ Dependencies installed"
	@echo ""
	@echo "Validating Python version in venv..."
	@$(DRYRUN_PYTHON) -c "import sys; print('  Venv Python: ' + f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
	@echo ""
	@echo "Validating imports..."
	@$(DRYRUN_PYTHON) -c "from orpheus_common import OrpheusConfig; print('  ✓ orpheus_common.OrpheusConfig')"
	@$(DRYRUN_PYTHON) -c "from orpheus_common.mqtt import MQTTClient; print('  ✓ orpheus_common.mqtt.MQTTClient')"
	@$(DRYRUN_PYTHON) -c "from orpheus_common.logging import setup_logging; print('  ✓ orpheus_common.logging.setup_logging')"
	@$(DRYRUN_PYTHON) -c "from orpheus_common.storage import get_data_root; print('  ✓ orpheus_common.storage.get_data_root')"
	@echo ""
	@echo "Cleaning up dry-run venv..."
	@rm -rf $(DRYRUN_VENV_PATH)
	@echo ""
	@echo "=========================================="
	@echo "✅ DRY-RUN PASSED: Python 3.9.5 compatible"
	@echo "=========================================="