# Orpheus Audio Output Manager Makefile
#
# Keeps the configured audio output (output device + audio server) ready for
# orpheus-agent-audio-playback. Replaces orpheus-bluetooth-autoconnect.

-include .env
export

SERVICE_NAME := orpheus-audio-output
DEPLOY_ROOT  := /opt/orpheus/services/$(SERVICE_NAME)

include ../../make/common_python.mk
include ../../make/common_lint.mk
include ../../make/common_service.mk
include ../../make/common_deploy.mk

.PHONY: help install run test coverage clean dry-run update health check-config rollback

help:
	@echo "Orpheus Audio Output Manager"
	@echo ""
	@echo "Local development (no sudo):"
	@echo "  make install          Install dependencies into ./venv"
	@echo "  make test             Run the isolated test suite (no hardware, no broker)"
	@echo "  make coverage         Tests with a coverage report"
	@echo "  make lint             Static analysis"
	@echo "  make check-config     Validate the audio_output section of orpheus.yaml"
	@echo ""
	@echo "Edge deployment (sudo required):"
	@echo "  make install-service  Install, retire orpheus-bluetooth-autoconnect, start"
	@echo "  make uninstall-service  Remove the service and undo its host changes"
	@echo "  make rollback         Same, and restore orpheus-bluetooth-autoconnect"
	@echo "  make status | logs | restart | health"
	@echo "  make update           git pull + reinstall + restart"

install: $(VENV)/bin/activate
	@echo "Installing dependencies..."
	$(PIP) install --upgrade pip
	$(PIP) install -e ../../platform/orpheus-common
	$(PIP) install -r ../../platform/orpheus-common/requirements.txt
	$(PIP) install -r requirements.txt
	@echo "✓ Installation complete"

run: check-deps
	$(PYTHON) -m orpheus_audio_output.main

check-config: check-deps
	@$(PYTHON) -m orpheus_audio_output.main check

test: check-deps
	@echo "Running tests..."
	$(PYTEST) tests/ -v

coverage: check-deps
	$(PYTEST) tests/ -v --cov=orpheus_audio_output --cov-report=term-missing

dry-run: check-deps
	$(PYTHON) -c "import sys; print(f'Python {sys.version}')"
	$(PYTHON) -c "import orpheus_audio_output.main; print('✓ orpheus_audio_output imports')"
	$(PYTHON) -c "import orpheus_common; print('✓ orpheus_common imports')"

clean:
	rm -rf $(VENV) build dist *.egg-info .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Last health snapshot written by the running service.
health:
	@if [ -x $(DEPLOY_ROOT)/venv/bin/python ]; then \
		$(DEPLOY_ROOT)/venv/bin/python -m orpheus_audio_output.main status; \
	else \
		cat /run/orpheus-audio-output/health.json 2>/dev/null || echo "not installed"; \
	fi

rollback:
	@echo "Rolling back to orpheus-bluetooth-autoconnect..."
	@sudo RESTORE_LEGACY=1 bash systemd/uninstall-service.sh

update:
	@echo "Updating $(SERVICE_NAME)..."
	git pull
	$(MAKE) install-service
	@echo "✓ $(SERVICE_NAME) updated and restarted"
