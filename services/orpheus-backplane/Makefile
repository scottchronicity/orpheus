# Orpheus Messaging Backplane Makefile
#
# Manages the broker that carries the Orpheus "stream of consciousness".
# Broker-agnostic: BACKPLANE_BROKER selects nats (default, NATS+JetStream) or
# mqtt (mosquitto, fallback). Cross-platform: Linux = systemd (production Jetson),
# macOS = a dev process managed via a pidfile (no systemd).

-include .env

# -- Component identity ------------------------------------------------------
SERVICE_NAME := orpheus-backplane
BACKPLANE_BROKER ?= nats

# -- Shared infrastructure ---------------------------------------------------
include ../../make/common_python.mk

# -- Platform + dev paths ----------------------------------------------------
UNAME_S := $(shell uname -s)
DEV_STORE ?= $(if $(ORPHEUS_DATA_ROOT),$(ORPHEUS_DATA_ROOT),/tmp/orpheus)/backplane/jetstream
DEV_PIDFILE := /tmp/orpheus-backplane-dev.pid
DEV_LOG := /tmp/orpheus-backplane-dev.log

.PHONY: help install install-service uninstall-service run \
        start stop restart status logs \
        service-start service-stop service-restart service-status service-logs \
        lint format install-python test test-python \
        health update

help:
	@echo "Orpheus Messaging Backplane ($(SERVICE_NAME))"
	@echo "Broker: $(BACKPLANE_BROKER)   Platform: $(UNAME_S)"
	@echo ""
	@echo "  make install     Install + start the broker (Linux: sudo+systemd; macOS: brew)"
	@echo "  make start       Start the broker"
	@echo "  make stop        Stop the broker"
	@echo "  make restart     Restart the broker"
	@echo "  make status      Show broker status"
	@echo "  make logs        Tail broker logs"
	@echo "  make run         (macOS dev) run the broker in the foreground"
	@echo "  make health      Quick health check"
	@echo ""
	@echo "  BACKPLANE_BROKER=mqtt make install   # use mosquitto instead of nats"

# ---------------------------------------------------------------------------
# Install (cross-platform; install.sh picks broker + platform)
# ---------------------------------------------------------------------------
install: install-service

ifeq ($(UNAME_S),Darwin)
install-service:
	@echo "Installing $(SERVICE_NAME) ($(BACKPLANE_BROKER)) for macOS dev..."
	@BACKPLANE_BROKER=$(BACKPLANE_BROKER) bash scripts/install.sh

uninstall-service:
	@echo "macOS dev broker is not a system service; nothing to uninstall."
	@echo "(brew uninstall nats-server / mosquitto to remove the binary.)"
else
install-service:
	@echo "Installing $(SERVICE_NAME) ($(BACKPLANE_BROKER))..."
	@sudo BACKPLANE_BROKER=$(BACKPLANE_BROKER) bash scripts/install.sh

uninstall-service:
	@if sudo systemctl list-unit-files | grep -q $(SERVICE_NAME).service; then \
		sudo systemctl stop $(SERVICE_NAME).service 2>/dev/null || true; \
		sudo systemctl disable $(SERVICE_NAME).service 2>/dev/null || true; \
		sudo rm -f /etc/systemd/system/$(SERVICE_NAME).service; \
		sudo systemctl daemon-reload; \
		echo "✓ $(SERVICE_NAME) uninstalled"; \
	else echo "$(SERVICE_NAME) is not installed"; fi
endif

# ---------------------------------------------------------------------------
# Service control — systemd on Linux, pidfile-managed dev process on macOS
# ---------------------------------------------------------------------------
ifeq ($(UNAME_S),Darwin)

run:
	@mkdir -p $(DEV_STORE)
	@echo "Running $(SERVICE_NAME) (nats) in foreground; Ctrl+C to stop..."
	@ORPHEUS_BACKPLANE_STORE=$(DEV_STORE) nats-server -c config/nats.conf

start:
	@mkdir -p $(DEV_STORE)
	@if [ -f $(DEV_PIDFILE) ] && kill -0 $$(cat $(DEV_PIDFILE)) 2>/dev/null; then \
		echo "$(SERVICE_NAME) already running (pid $$(cat $(DEV_PIDFILE)))"; \
	else \
		ORPHEUS_BACKPLANE_STORE=$(DEV_STORE) nohup nats-server -c config/nats.conf >$(DEV_LOG) 2>&1 & \
		echo $$! > $(DEV_PIDFILE); \
		sleep 1; echo "✓ started $(SERVICE_NAME) (dev), pid $$(cat $(DEV_PIDFILE)), log $(DEV_LOG)"; \
	fi

stop:
	@if [ -f $(DEV_PIDFILE) ] && kill -0 $$(cat $(DEV_PIDFILE)) 2>/dev/null; then \
		kill $$(cat $(DEV_PIDFILE)) && rm -f $(DEV_PIDFILE) && echo "✓ stopped"; \
	else echo "$(SERVICE_NAME) not running"; rm -f $(DEV_PIDFILE); fi

restart: stop start

status:
	@if [ -f $(DEV_PIDFILE) ] && kill -0 $$(cat $(DEV_PIDFILE)) 2>/dev/null; then \
		echo "$(SERVICE_NAME): running (pid $$(cat $(DEV_PIDFILE)))"; \
	else echo "$(SERVICE_NAME): not running"; fi

logs:
	@tail -f $(DEV_LOG)

else

run:
	@echo "On Linux $(SERVICE_NAME) runs under systemd. Use 'make start' / 'make install'."

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

endif

# Backward-compatible aliases
service-start: start
service-stop: stop
service-restart: restart
service-status: status
service-logs: logs

health:
	@echo "$(SERVICE_NAME) health ($(BACKPLANE_BROKER), $(UNAME_S))"
	@$(MAKE) --no-print-directory status

update:
	@echo "Updating $(SERVICE_NAME)..."
	@git pull
	@$(MAKE) install
	@$(MAKE) restart
	@echo "✓ $(SERVICE_NAME) updated"

# ---------------------------------------------------------------------------
# Python tooling (the broker is not Python, but the sanity test + lint are)
# ---------------------------------------------------------------------------
install-python: check-deps
	@$(PIP_INSTALL) --upgrade pip -q
	@$(PIP_INSTALL) -r requirements.txt -q
	@echo "✓ Dependencies installed"

lint: install-python
	@echo "Linting Python code with ruff..."
	@$(RUFF) check tests/
	@echo "✓ Static analysis complete"

format: install-python
	@$(RUFF) format tests/
	@$(RUFF) check --fix tests/

test-python: install-python
	@$(PYTHON) -m pytest tests/ -v

test: test-python
