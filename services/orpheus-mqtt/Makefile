# Orpheus MQTT Broker Makefile
#
# This Makefile provides convenient commands for managing the Orpheus MQTT
# message broker service.

# Load local overrides from .env if present
-include .env
export

# -- Component identity ------------------------------------------------------
SERVICE_NAME := orpheus-mqtt

# -- Shared infrastructure ---------------------------------------------------
include ../../make/common_python.mk

# -- Extra tool paths --------------------------------------------------------
UVICORN ?= $(PYTHON_DIR)uvicorn

.PHONY: help install run clean dry-run \
        install-service uninstall-service \
        start stop restart status logs \
        service-start service-stop service-restart service-status service-logs service-logs-static \
        update \
        check-root check-installed lint format \
        enable disable health show-config validate-config logs-follow \
        test test-python test-deprecated check-python-version

help:
	@echo "Orpheus MQTT Broker Management"
	@echo "==============================="
	@echo ""
	@echo "Local development (no sudo):"
	@echo "  make test            Test broker connectivity"
	@echo "  make dry-run         Validate Python 3.9.5 venv + imports (no deploy)"
	@echo ""
	@echo "Edge deployment (sudo required):"
	@echo "  make install         Install Mosquitto broker and configure service"
	@echo "  make install-service Install systemd service (alias for install)"
	@echo "  make start           Start the broker service"
	@echo "  make stop            Stop the broker service"
	@echo "  make restart         Restart the broker service"
	@echo "  make status          Show service status"
	@echo "  make logs            Tail broker logs (follow)"
	@echo "  make update          git pull + reinstall + restart"
	@echo "  make uninstall-service Remove systemd service"
	@echo ""
	@echo "Diagnostics:"
	@echo "  make health          Quick health check"
	@echo "  make show-config     Show current Mosquitto configuration"
	@echo "  make validate-config Validate configuration file"
	@echo "  make enable          Enable service to start on boot"
	@echo "  make disable         Disable service from starting on boot"
	@echo ""
	@echo "Examples:"
	@echo "  sudo make install       # Initial setup"
	@echo "  make test               # Verify it works"
	@echo "  make logs               # Monitor activity"

lint: install-python
	@echo "Running static code analysis..."
	@echo "Linting Python code with ruff..."
	@$(RUFF) check tests/
	@echo "✓ Static analysis complete"

format: install-python
	@echo "Formatting and fixing code..."
	@$(RUFF) format tests/
	@$(RUFF) check --fix tests/
	@echo "✓ Code formatting complete"

install-python: check-deps
	@echo "Installing dependencies..."
	$(PIP_INSTALL) --upgrade pip
	$(PIP_INSTALL) -r requirements.txt
	@echo "✓ Dependencies installed"

test-python: install-python
	@echo "Running tests with: $(PYTHON)"
	$(PYTHON) -m pytest tests/ -v

test: test-python

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
	@$(DRYRUN_PYTHON) -c "import paho.mqtt.client; print('  ✓ paho.mqtt.client')"
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

install-service:
	@echo "Installing Orpheus MQTT broker..."
	@sudo chmod +x scripts/install.sh
	@sudo ./scripts/install.sh

install: install-service

uninstall-service:
	@if sudo systemctl list-unit-files | grep -q orpheus-mqtt.service; then \
		printf "Removing Orpheus MQTT broker systemd service...\n"; \
		sudo systemctl stop orpheus-mqtt.service 2>/dev/null || true; \
		sudo systemctl disable orpheus-mqtt.service 2>/dev/null || true; \
		sudo rm -f /etc/systemd/system/orpheus-mqtt.service; \
		sudo systemctl daemon-reload; \
		sudo systemctl reset-failed orpheus-mqtt.service 2>/dev/null || true; \
		echo "✓ Service uninstalled"; \
	else \
		echo "Orpheus MQTT broker service is not installed"; \
	fi

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

# Check if broker is installed
check-installed:
	@if ! systemctl list-unit-files | grep -q orpheus-mqtt.service; then \
		echo "ERROR: Orpheus MQTT broker is not installed"; \
		echo "Run: sudo make install"; \
		exit 1; \
	fi

# Follow logs in real-time (legacy alias)
logs-follow: check-installed
	@echo "Following MQTT broker logs (Ctrl+C to exit):"
	@echo "============================================="
	@sudo journalctl -u orpheus-mqtt.service -f

# Enable service (start on boot)
enable: check-installed
	@echo "Enabling Orpheus MQTT broker to start on boot..."
	@sudo systemctl enable orpheus-mqtt.service
	@echo "✓ Service enabled"

# Disable service (don't start on boot)
disable: check-installed
	@echo "Disabling Orpheus MQTT broker from starting on boot..."
	@sudo systemctl disable orpheus-mqtt.service
	@echo "✓ Service disabled"

# Quick health check
health: check-installed
	@echo "Orpheus MQTT Broker Health Check"
	@echo "=================================="
	@printf "Service Status:     "
	@sudo systemctl is-active orpheus-mqtt.service && echo "✓ Running" || echo "✗ Not running"
	@printf "Enabled on boot:    "
	@sudo systemctl is-enabled orpheus-mqtt.service >/dev/null 2>&1 && echo "✓ Yes" || echo "✗ No"
	@printf "Configuration:      "
	@[ -f /etc/orpheus/mqtt/mosquitto.conf ] && echo "✓ Present" || echo "✗ Missing"
	@printf "Persistence dir:    "
	@[ -d /var/lib/orpheus/mqtt ] && echo "✓ Present" || echo "✗ Missing"
	@printf "Recent errors:      "
	@ERROR_COUNT=$$(sudo journalctl -u orpheus-mqtt.service --since "1 hour ago" -p err --no-pager 2>/dev/null | wc -l); \
	if [ $$ERROR_COUNT -eq 0 ]; then \
		echo "✓ None"; \
	else \
		echo "✗ $$ERROR_COUNT error(s) in last hour"; \
	fi

# Show configuration
show-config: check-installed
	@echo "Current Mosquitto Configuration:"
	@echo "================================="
	@sudo cat /etc/orpheus/mqtt/mosquitto.conf

# Validate configuration
validate-config: check-installed
	@echo "Validating Mosquitto configuration..."
	@if sudo mosquitto -c /etc/orpheus/mqtt/mosquitto.conf -t 2>&1 | grep -q "Error"; then \
		echo "✗ Configuration has errors"; \
		sudo mosquitto -c /etc/orpheus/mqtt/mosquitto.conf -t; \
		exit 1; \
	else \
		echo "✓ Configuration is valid"; \
	fi

# Clean up (remove service and configuration) - USE WITH CAUTION
clean:
	@echo "WARNING: This will remove the MQTT broker service and configuration"
	@echo "NOTE: Shared directories (/etc/orpheus, /var/lib/orpheus) will NOT be removed"
	@read -p "Are you sure? (y/N) " -n 1 -r; \
	echo; \
	if [ "$$REPLY" = "y" ] || [ "$$REPLY" = "Y" ]; then \
		echo "Stopping and removing Orpheus MQTT broker..."; \
		sudo systemctl stop orpheus-mqtt.service 2>/dev/null || true; \
		sudo systemctl disable orpheus-mqtt.service 2>/dev/null || true; \
		sudo rm -f /etc/systemd/system/orpheus-mqtt.service; \
		sudo systemctl daemon-reload; \
		echo "✓ Systemd service removed"; \
		if [ -d /etc/orpheus/mqtt ]; then \
			sudo rm -rf /etc/orpheus/mqtt; \
			echo "✓ MQTT configuration removed (/etc/orpheus/mqtt/)"; \
		fi; \
		echo "✓ Shared parent directory preserved (/etc/orpheus/)"; \
		echo ""; \
		echo "NOTE: The following were NOT removed:"; \
		echo "  • Mosquitto package (run: sudo apt remove mosquitto mosquitto-clients)"; \
		echo "  • MQTT persistence data (/var/lib/orpheus/mqtt/)"; \
		echo "  • Shared root directories (/etc/orpheus/, /var/lib/orpheus/)"; \
		echo "  • Logs (run: sudo journalctl --rotate && sudo journalctl --vacuum-time=1s)"; \
		echo ""; \
		echo "To completely remove MQTT data:"; \
		echo "  sudo rm -rf /var/lib/orpheus/mqtt"; \
		echo ""; \
		echo "To remove Orpheus entirely (after uninstalling all services):"; \
		echo "  sudo rm -rf /etc/orpheus /var/lib/orpheus"; \
	else \
		echo "Clean cancelled"; \
	fi

test-deprecated:
	@echo "Testing MQTT broker connection..."
	@if ! command -v python3 >/dev/null 2>&1; then \
		echo "ERROR: python3 is not installed"; \
		exit 1; \
	fi
	@if ! python3 -c "import paho.mqtt.client" 2>/dev/null; then \
		echo "Installing paho-mqtt package..."; \
		pip3 install paho-mqtt; \
	fi
	@chmod +x scripts/test-connection.py
	@python3 scripts/test-connection.py
