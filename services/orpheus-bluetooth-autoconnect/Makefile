# Orpheus Bluetooth Auto-Connect Makefile
#
# This Makefile provides convenient commands for managing the Orpheus Bluetooth
# auto-connect service that ensures Bluetooth speakers automatically connect.

# Load local overrides from .env if present
-include .env
export

# -- Component identity ------------------------------------------------------
SERVICE_NAME := orpheus-bluetooth-autoconnect

# Bluetooth configuration
BLUETOOTH_SPEAKER_MAC ?= FC:58:FA:02:AF:28

# -- Shared infrastructure ---------------------------------------------------
include ../../make/common_python.mk

.PHONY: help install run dry-run \
        install-service uninstall-service \
        start stop restart status logs \
        service-start service-stop service-restart service-status service-logs service-logs-static \
        update \
        uninstall check-installed lint format \
        enable disable health logs-follow \
        test test-python test-bash check-python-version clean

help:
	@echo "Orpheus Bluetooth Auto-Connect Management"
	@echo "=========================================="
	@echo ""
	@echo "Local development (no sudo):"
	@echo "  make test            Test Bluetooth connectivity"
	@echo "  make dry-run         Validate Python 3.9+ venv + imports (no deploy)"
	@echo ""
	@echo "Edge deployment (sudo required):"
	@echo "  make install         Install Bluetooth auto-connect service"
	@echo "  make install-service Install systemd service (alias for install)"
	@echo "  make start           Start the service"
	@echo "  make stop            Stop the service"
	@echo "  make restart         Restart the service"
	@echo "  make status          Show service status"
	@echo "  make logs            Tail service logs (follow)"
	@echo "  make update          git pull + reinstall + restart"
	@echo "  make uninstall       Remove service"
	@echo "  make uninstall-service Remove service (alias for uninstall)"
	@echo ""
	@echo "Diagnostics:"
	@echo "  make health          Quick health check"
	@echo "  make enable          Enable service to start on boot"
	@echo "  make disable         Disable service from starting on boot"
	@echo ""
	@echo "Configuration:"
	@echo "  BLUETOOTH_SPEAKER_MAC=$(BLUETOOTH_SPEAKER_MAC)"
	@echo ""
	@echo "Examples:"
	@echo "  sudo make install              # Initial setup"
	@echo "  make test                      # Verify it works"
	@echo "  make logs                      # Monitor activity"
	@echo "  BLUETOOTH_SPEAKER_MAC=XX:XX:XX:XX:XX:XX sudo make install  # Custom device"

lint: check-deps
	@echo "Running static code analysis..."
	@echo "Linting Python code with ruff..."
	$(RUFF) check tests/ scripts/ || true
	@echo "✓ Static analysis complete"

format: check-deps
	@echo "Formatting and fixing code..."
	@echo "Formatting Python tests with ruff..."
	$(RUFF) format tests/ scripts/
	@echo "Fixing Python tests with ruff..."
	$(RUFF) check --fix tests/ scripts/ || true
	@echo "✓ Code formatting complete"

install-python: check-deps
	@echo "Installing dependencies with $(PIP)..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "✓ Dependencies installed"

test-python: install-python
	@echo "Running tests with: $(PYTHON)"
	$(PYTHON) -m pytest tests/ -v

test-bash:
	@echo "Running bash script tests..."
	@chmod +x tests/test_connection.sh
	@./tests/test_connection.sh

test: test-python test-bash

# This service does not have a standalone run mode; use 'make start' instead
run:
	@echo "$(SERVICE_NAME) is a system service managed by systemd."
	@echo "Use 'make start' to start it, or 'make install' for initial setup."

# Dry-run: Create a test venv with Python 3.9+, install deps, validate imports
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
	@echo "Installing dependencies..."
	@$(DRYRUN_PIP_INSTALL) --upgrade pip -q
	@$(DRYRUN_PIP_INSTALL) -r requirements.txt -q
	@echo "✓ Dependencies installed"
	@echo ""
	@echo "Validating Python version in venv..."
	@$(DRYRUN_PYTHON) -c "import sys; print('  Venv Python: ' + f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
	@echo ""
	@echo "Validating imports..."
	@$(DRYRUN_PYTHON) -c "import subprocess; print('  ✓ subprocess')"
	@$(DRYRUN_PYTHON) -c "import time; print('  ✓ time')"
	@echo ""
	@echo "Cleaning up dry-run venv..."
	@rm -rf $(DRYRUN_VENV_PATH)
	@echo ""
	@echo "=========================================="
	@echo "✅ DRY-RUN PASSED: Python 3.9+ compatible"
	@echo "=========================================="

# ---------------------------------------------------------------------------
# Edge deployment targets
# ---------------------------------------------------------------------------

install:
	@echo "Installing Orpheus Bluetooth Auto-Connect service..."
	@sudo chmod +x scripts/install.sh
	@sudo BLUETOOTH_SPEAKER_MAC=$(BLUETOOTH_SPEAKER_MAC) ./scripts/install.sh

install-service: install

uninstall:
	@if sudo systemctl list-unit-files | grep -q orpheus-bluetooth-autoconnect.service; then \
		printf "Removing Orpheus Bluetooth Auto-Connect systemd service...\n"; \
		sudo systemctl stop orpheus-bluetooth-autoconnect.service 2>/dev/null || true; \
		sudo systemctl disable orpheus-bluetooth-autoconnect.service 2>/dev/null || true; \
		sudo rm -f /etc/systemd/system/orpheus-bluetooth-autoconnect.service; \
		sudo systemctl daemon-reload; \
		sudo systemctl reset-failed orpheus-bluetooth-autoconnect.service 2>/dev/null || true; \
		echo "✓ Service uninstalled"; \
	else \
		echo "Orpheus Bluetooth Auto-Connect service is not installed"; \
	fi

uninstall-service: uninstall

start:
	@sudo systemctl start $(SERVICE_NAME)

stop:
	@sudo systemctl stop $(SERVICE_NAME)

restart:
	@sudo systemctl restart $(SERVICE_NAME)

status:
	@sudo systemctl status $(SERVICE_NAME) --no-pager || true

logs:
	@sudo journalctl -u $(SERVICE_NAME) -f

# Backward-compatible aliases (delegating to canonical short targets above)
service-start: start
service-stop: stop
service-restart: restart
service-status: status
service-logs: logs

service-logs-static:
	@sudo journalctl -u $(SERVICE_NAME) -n 100 --no-pager

update:
	@echo "Updating $(SERVICE_NAME)..."
	git pull
	$(MAKE) install
	$(MAKE) restart
	@echo "✓ $(SERVICE_NAME) updated and restarted"

# ---------------------------------------------------------------------------
# Diagnostics and management
# ---------------------------------------------------------------------------

# Check if service is installed
check-installed:
	@if ! systemctl list-unit-files | grep -q orpheus-bluetooth-autoconnect.service; then \
		echo "ERROR: Orpheus Bluetooth Auto-Connect service is not installed"; \
		echo "Run: sudo make install"; \
		exit 1; \
	fi

# Follow logs in real-time (legacy alias)
logs-follow: check-installed
	@echo "Following Bluetooth Auto-Connect logs (Ctrl+C to exit):"
	@echo "========================================================"
	@sudo journalctl -u orpheus-bluetooth-autoconnect.service -f

# Enable service (start on boot)
enable: check-installed
	@echo "Enabling Orpheus Bluetooth Auto-Connect service to start on boot..."
	@sudo systemctl enable orpheus-bluetooth-autoconnect.service
	@echo "✓ Service enabled"

# Disable service (don't start on boot)
disable: check-installed
	@echo "Disabling Orpheus Bluetooth Auto-Connect service from starting on boot..."
	@sudo systemctl disable orpheus-bluetooth-autoconnect.service
	@echo "✓ Service disabled"

# Quick health check
health: check-installed
	@echo "Orpheus Bluetooth Auto-Connect Health Check"
	@echo "============================================"
	@printf "Service Status:     "
	@sudo systemctl is-active orpheus-bluetooth-autoconnect.service && echo "✓ Running" || echo "✗ Not running"
	@printf "Enabled on boot:    "
	@sudo systemctl is-enabled orpheus-bluetooth-autoconnect.service >/dev/null 2>&1 && echo "✓ Yes" || echo "✗ No"
	@printf "Recent errors:      "
	@ERROR_COUNT=$$(sudo journalctl -u orpheus-bluetooth-autoconnect.service --since "1 hour ago" -p err --no-pager 2>/dev/null | wc -l); \
	if [ $$ERROR_COUNT -eq 0 ]; then \
		echo "✓ None"; \
	else \
		echo "✗ $$ERROR_COUNT error(s) in last hour"; \
	fi

# Clean up (remove service and configuration) - USE WITH CAUTION
clean:
	@echo "WARNING: This will remove the Bluetooth Auto-Connect service and configuration"
	@read -p "Are you sure? (y/N) " -n 1 -r; \
	echo; \
	if [ "$$REPLY" = "y" ] || [ "$$REPLY" = "Y" ]; then \
		echo "Stopping and removing Orpheus Bluetooth Auto-Connect service..."; \
		sudo systemctl stop orpheus-bluetooth-autoconnect.service 2>/dev/null || true; \
		sudo systemctl disable orpheus-bluetooth-autoconnect.service 2>/dev/null || true; \
		sudo rm -f /etc/systemd/system/orpheus-bluetooth-autoconnect.service; \
		sudo systemctl daemon-reload; \
		echo "✓ Systemd service removed"; \
		if [ -d /etc/orpheus/bluetooth-autoconnect ]; then \
			sudo rm -rf /etc/orpheus/bluetooth-autoconnect; \
			echo "✓ Bluetooth Auto-Connect configuration removed (/etc/orpheus/bluetooth-autoconnect/)"; \
		fi; \
		echo "✓ Shared parent directory preserved (/etc/orpheus/)"; \
		echo ""; \
		echo "To remove logs:"; \
		echo "  sudo journalctl --rotate && sudo journalctl --vacuum-time=1s"; \
	else \
		echo "Clean cancelled"; \
	fi
