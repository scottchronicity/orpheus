# Orpheus Monorepo Master Makefile
# This Makefile provides a consistent interface for the entire monorepo
#
# Usage:
#   make help           - Show this help message
#   make install        - Install all components
#   make test           - Run all tests
#   make coverage-all   - Run tests with coverage across all Python projects
#   make lint           - Lint all Python code
#   make format         - Format all code
#   make clean          - Remove build artifacts

.PHONY: help install coverage-all lint format clean mbake venv-all \
	install-common install-dashboard install-ui install-gps install-audio-motion install-audio-playback install-video-motion install-video-snapshotter install-video-timelapser install-bird-detection install-crow-detection install-event-correlator install-mqtt install-bluetooth \
	test-common test-dashboard test-ui test-gps test-audio-motion test-audio-playback test-video-motion test-video-snapshotter test-video-timelapser test-bird-detection test-crow-detection test-event-correlator \
	coverage-common coverage-dashboard coverage-ui coverage-gps coverage-audio-motion coverage-audio-playback coverage-video-motion coverage-video-snapshotter coverage-video-timelapser coverage-bird-detection coverage-crow-detection coverage-event-correlator \
	lint-common lint-dashboard lint-ui lint-gps lint-audio-motion lint-audio-playback lint-video-motion lint-video-snapshotter lint-video-timelapser lint-bird-detection lint-crow-detection lint-event-correlator lint-mqtt \
	format-common format-dashboard format-ui format-gps format-audio-motion format-audio-playback format-video-motion format-video-snapshotter format-video-timelapser format-bird-detection format-crow-detection format-event-correlator format-mqtt \
	clean-common clean-dashboard clean-ui clean-gps clean-audio-motion clean-audio-playback clean-video-motion clean-video-snapshotter clean-video-timelapser clean-bird-detection clean-crow-detection clean-event-correlator clean-mqtt clean-bluetooth \
	services-install services-start services-stop services-restart \
	update-services \
	status-all update-all logs-all test-all deploy-all check-models run-ui \
	dev-stack dev-stop dev-restart dev-status dev-logs

# Python projects in the monorepo
PYTHON_PROJECTS = platform/orpheus-common services/orpheus-dashboard services/orpheus_ui services/orpheus-gps agents/orpheus-agent-audio-motion agents/orpheus-agent-audio-playback agents/orpheus-agent-video-motion agents/orpheus-agent-video-snapshotter agents/orpheus-agent-video-timelapser agents/orpheus-agent-bird-detection agents/orpheus-agent-crow-detection agents/orpheus-agent-event-correlator
# All projects (including non-Python)
ALL_PROJECTS = $(PYTHON_PROJECTS) services/orpheus-mqtt

# Default Python system interpreter (can be overridden via env or .env)
PYTHON_SYSTEM ?= python3.9

# Coverage threshold for CI (percentage)
COVERAGE_THRESHOLD ?= 80

# Coverage reports (can be overridden, e.g., COV_REPORTS="--cov-report=xml")
COV_REPORTS ?= --cov-report=term-missing

#==============================================================================
# Help
#==============================================================================
help:
	@echo "Orpheus - Wildlife Monitoring & Cross-Species Communication Platform"
	@echo ""
	@echo "Development:"
	@echo "  make install         - Install all Python components with venvs"
	@echo "  make test-all        - Run all tests (continues on error to show all failures)"
	@echo "  make coverage-all    - Run tests with coverage for all Python projects"
	@echo "  make lint            - Lint all code with ruff"
	@echo "  make format          - Format all code with ruff"
	@echo "  make mbake           - Format all Makefiles with mbake using uvx"
	@echo "  make clean           - Remove build artifacts and venvs"
	@echo "  make check-deps      - Validate dependency version consistency"
	@echo ""
	@echo "Individual Project Targets:"
	@echo "  make install-common           - Install orpheus-common"
	@echo "  make install-dashboard        - Install orpheus-dashboard (legacy, port 8081)"
	@echo "  make install-ui               - Install orpheus_ui (new UI, port 8080)"
	@echo "  make install-audio-motion     - Install orpheus-agent-audio-motion"
	@echo "  make install-bird-detection   - Install orpheus-agent-bird-detection"
	@echo "  make install-crow-detection   - Install orpheus-agent-crow-detection"
	@echo "  make install-event-correlator - Install orpheus-agent-event-correlator"
	@echo ""
	@echo "macOS Development:"
	@echo "  make dev-stack                - Start Observe stack in background"
	@echo "  make dev-stop                 - Stop all running services"
	@echo "  make dev-restart              - Restart all (or: make dev-restart SVC=bird-detection)"
	@echo "  make dev-status               - Show running/stopped status"
	@echo "  make dev-logs                 - Tail all logs (or: make dev-logs SVC=dashboard)"
	@echo ""
	@echo "Running Services:"
	@echo "  make run-ui                   - Run new Orpheus UI backend on port 8082"
	@echo "  make install-video-motion     - Install orpheus-agent-video-motion"
	@echo "  make test-<project>           - Run tests for a specific project"
	@echo "  make coverage-<project>       - Run coverage for a specific project"
	@echo ""
	@echo "Production:"
	@echo "  make deploy-all         - Full deployment (install + services-install + start)"
	@echo "  make services-install   - Install system services"
	@echo "  make services-start     - Start all services"
	@echo "  make services-stop      - Stop all services"
	@echo "  make services-restart   - Restart all services"
	@echo "  make status-all         - Check status of all services"
	@echo "  make update-all         - Update all services and agents (with proper ordering)"
	@echo "  make logs-all           - Stream logs from all services"
	@echo "  make check-models       - Check if ML models are present"
	@echo "  make update-services    - Update all services (code + restart)"
	@echo ""

#==============================================================================
# Install Targets
#==============================================================================
install: install-common install-dashboard install-ui install-gps install-audio-motion install-audio-playback install-video-motion install-video-snapshotter install-video-timelapser install-bird-detection install-crow-detection install-event-correlator
	@echo "✅ All components installed"

install-common:
	@echo "Installing orpheus-common..."
	@$(MAKE) -C platform/orpheus-common install
	@echo "✅ orpheus-common installed"

install-dashboard: install-common
	@echo "Installing orpheus-dashboard (legacy)..."
	@$(MAKE) -C services/orpheus-dashboard install
	@echo "✅ orpheus-dashboard installed"

install-ui: install-common
	@echo "Installing orpheus_ui (new UI)..."
	@$(MAKE) -C services/orpheus_ui install
	@echo "✅ orpheus_ui installed"

install-gps: install-common
	@echo "Installing orpheus-gps..."
	@$(MAKE) -C services/orpheus-gps install
	@echo "✅ orpheus-gps installed"

install-audio-motion: install-common
	@echo "Installing orpheus-agent-audio-motion..."
	@$(MAKE) -C agents/orpheus-agent-audio-motion install
	@echo "✅ orpheus-agent-audio-motion installed"

install-audio-playback: install-common
	@echo "Installing orpheus-agent-audio-playback..."
	@$(MAKE) -C agents/orpheus-agent-audio-playback install
	@echo "✅ orpheus-agent-audio-playback installed"

install-video-motion: install-common
	@echo "Installing orpheus-agent-video-motion..."
	@$(MAKE) -C agents/orpheus-agent-video-motion install
	@echo "✅ orpheus-agent-video-motion installed"

install-video-snapshotter: install-common
	@echo "Installing orpheus-agent-video-snapshotter..."
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter install
	@echo "✅ orpheus-agent-video-snapshotter installed"

install-video-timelapser: install-common
	@echo "Installing orpheus-agent-video-timelapser..."
	@$(MAKE) -C agents/orpheus-agent-video-timelapser install
	@echo "✅ orpheus-agent-video-timelapser installed"

install-bird-detection: install-common
	@echo "Installing orpheus-agent-bird-detection..."
	@$(MAKE) -C agents/orpheus-agent-bird-detection install
	@echo "✅ orpheus-agent-bird-detection installed"

install-crow-detection: install-common
	@echo "Installing orpheus-agent-crow-detection..."
	@$(MAKE) -C agents/orpheus-agent-crow-detection install
	@echo "✅ orpheus-agent-crow-detection installed"

install-event-correlator: install-common
	@echo "Installing orpheus-agent-event-correlator..."
	@$(MAKE) -C agents/orpheus-agent-event-correlator install
	@echo "✅ orpheus-agent-event-correlator installed"

install-mqtt:
	@echo "Installing orpheus-mqtt dependencies (if any)..."
	@$(MAKE) -C services/orpheus-mqtt install-python
	@echo "✅ orpheus-mqtt installed"

#==============================================================================
# Test Targets
#==============================================================================
# Individual test targets for running specific component tests
# Use 'make test-all' to run all tests across the monorepo

test-common:
	@echo "Testing orpheus-common..."
	@$(MAKE) -C platform/orpheus-common test
	@echo "✅ orpheus-common tests passed"

test-dashboard:
	@echo "Testing orpheus-dashboard..."
	@$(MAKE) -C services/orpheus-dashboard test
	@echo "✅ orpheus-dashboard tests passed"

test-ui:
	@echo "Testing orpheus_ui..."
	@$(MAKE) -C services/orpheus_ui test
	@echo "✅ orpheus_ui tests passed"

test-gps:
	@echo "Testing orpheus-gps..."
	@$(MAKE) -C services/orpheus-gps test
	@echo "✅ orpheus-gps tests passed"

test-audio-motion:
	@echo "Testing orpheus-agent-audio-motion..."
	@$(MAKE) -C agents/orpheus-agent-audio-motion test
	@echo "✅ orpheus-agent-audio-motion tests passed"

test-audio-playback:
	@echo "Testing orpheus-agent-audio-playback..."
	@$(MAKE) -C agents/orpheus-agent-audio-playback test
	@echo "✅ orpheus-agent-audio-playback tests passed"

test-video-motion:
	@echo "Testing orpheus-agent-video-motion..."
	@$(MAKE) -C agents/orpheus-agent-video-motion test
	@echo "✅ orpheus-agent-video-motion tests passed"

test-video-snapshotter:
	@echo "Testing orpheus-agent-video-snapshotter..."
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter test
	@echo "✅ orpheus-agent-video-snapshotter tests passed"

test-video-timelapser:
	@echo "Testing orpheus-agent-video-timelapser..."
	@$(MAKE) -C agents/orpheus-agent-video-timelapser test
	@echo "✅ orpheus-agent-video-timelapser tests passed"

test-bird-detection:
	@echo "Testing orpheus-agent-bird-detection..."
	@$(MAKE) -C agents/orpheus-agent-bird-detection test
	@echo "✅ orpheus-agent-bird-detection tests passed"

test-crow-detection:
	@echo "Testing orpheus-agent-crow-detection..."
	@$(MAKE) -C agents/orpheus-agent-crow-detection test
	@echo "✅ orpheus-agent-crow-detection tests passed"

test-event-correlator:
	@echo "Testing orpheus-agent-event-correlator..."
	@$(MAKE) -C agents/orpheus-agent-event-correlator test
	@echo "✅ orpheus-agent-event-correlator tests passed"

#==============================================================================
# Coverage Targets
#==============================================================================
coverage-all: coverage-common coverage-dashboard coverage-ui coverage-gps coverage-audio-motion coverage-audio-playback coverage-video-motion coverage-video-snapshotter coverage-video-timelapser coverage-bird-detection coverage-crow-detection coverage-event-correlator
	@echo ""
	@echo "============================================"
	@echo "✅ Coverage reports generated for all projects"
	@echo "============================================"

coverage-common:
	@echo ""
	@echo "📊 Coverage for orpheus-common..."
	@echo "============================================"
	@cd platform/orpheus-common && \
		if [ -d venv ]; then \
			. venv/bin/activate && python -m pytest tests/ --cov=orpheus_common $(COV_REPORTS) --cov-fail-under=$(COVERAGE_THRESHOLD); \
		else \
			echo "⚠️  No venv found. Run 'make install-common' first."; \
			exit 1; \
		fi

coverage-dashboard:
	@echo ""
	@echo "📊 Coverage for orpheus-dashboard..."
	@echo "============================================"
	@cd services/orpheus-dashboard && \
		if [ -d venv ]; then \
			. venv/bin/activate && python -m pytest tests/ --cov=src $(COV_REPORTS) --cov-fail-under=$(COVERAGE_THRESHOLD); \
		else \
			echo "⚠️  No venv found. Run 'make install-dashboard' first."; \
			exit 1; \
		fi

coverage-ui:
	@echo ""
	@echo "📊 Coverage for orpheus_ui..."
	@echo "============================================"
	@cd services/orpheus_ui/backend && \
		if [ -d venv ]; then \
			. venv/bin/activate && python -m pytest tests/ --cov=src $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-ui' first."; \
			exit 1; \
		fi

coverage-gps:
	@echo ""
	@echo "📊 Coverage for orpheus-gps..."
	@echo "============================================"
	@cd services/orpheus-gps && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_gps $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-gps' first."; \
			exit 1; \
		fi

coverage-audio-motion:
	@echo ""
	@echo "📊 Coverage for orpheus-agent-audio-motion..."
	@echo "============================================"
	@cd agents/orpheus-agent-audio-motion && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_agent_audio_motion $(COV_REPORTS) --cov-fail-under=$(COVERAGE_THRESHOLD); \
		else \
			echo "⚠️  No venv found. Run 'make install-audio-motion' first."; \
			exit 1; \
		fi

coverage-audio-playback:
	@echo ""
	@echo "📊 Coverage for orpheus-agent-audio-playback..."
	@echo "============================================"
	@cd agents/orpheus-agent-audio-playback && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_agent_audio_playback $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-audio-playback' first."; \
			exit 1; \
		fi

coverage-video-motion:
	@echo ""
	@echo "📊 Coverage for orpheus-agent-video-motion..."
	@echo "============================================"
	@cd agents/orpheus-agent-video-motion && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_agent_video_motion $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-video-motion' first."; \
			exit 1; \
		fi

coverage-video-snapshotter:
	@echo ""
	@echo "📊 Coverage for orpheus-agent-video-snapshotter..."
	@echo "============================================"
	@cd agents/orpheus-agent-video-snapshotter && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_agent_video_snapshotter $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-video-snapshotter' first."; \
			exit 1; \
		fi

coverage-video-timelapser:
	@echo ""
	@echo "📊 Coverage for orpheus-agent-video-timelapser..."
	@echo "============================================"
	@cd agents/orpheus-agent-video-timelapser && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_agent_video_timelapser $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-video-timelapser' first."; \
			exit 1; \
		fi

coverage-bird-detection:
	@echo ""
	@echo "📊 Coverage for orpheus-agent-bird-detection..."
	@echo "============================================"
	@cd agents/orpheus-agent-bird-detection && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_agent_bird_detection $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-bird-detection' first."; \
			exit 1; \
		fi

coverage-crow-detection:
	@echo ""
	@echo "📊 Coverage for orpheus-agent-crow-detection..."
	@echo "============================================"
	@cd agents/orpheus-agent-crow-detection && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_agent_crow_detection $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-crow-detection' first."; \
			exit 1; \
		fi

coverage-event-correlator:
	@echo ""
	@echo "📊 Coverage for orpheus-agent-event-correlator..."
	@echo "============================================"
	@cd agents/orpheus-agent-event-correlator && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_agent_event_correlator $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-event-correlator' first."; \
			exit 1; \
		fi

#==============================================================================
# Lint Targets
#==============================================================================
lint: lint-common lint-dashboard lint-ui lint-gps lint-audio-motion lint-audio-playback lint-video-motion lint-video-snapshotter lint-video-timelapser lint-bird-detection lint-crow-detection lint-event-correlator lint-mqtt
	@echo "✅ All linting complete"

lint-common:
	@echo "Linting orpheus-common..."
	@$(MAKE) -C platform/orpheus-common lint
	@echo "✅ orpheus-common linted"

lint-dashboard:
	@echo "Linting orpheus-dashboard..."
	@$(MAKE) -C services/orpheus-dashboard lint
	@echo "✅ orpheus-dashboard linted"

lint-ui:
	@echo "Linting orpheus_ui..."
	@$(MAKE) -C services/orpheus_ui lint
	@echo "✅ orpheus_ui linted"

lint-gps:
	@echo "Linting orpheus-gps..."
	@$(MAKE) -C services/orpheus-gps lint
	@echo "✅ orpheus-gps linted"

lint-audio-motion:
	@echo "Linting orpheus-agent-audio-motion..."
	@$(MAKE) -C agents/orpheus-agent-audio-motion lint
	@echo "✅ orpheus-agent-audio-motion linted"

lint-audio-playback:
	@echo "Linting orpheus-agent-audio-playback..."
	@$(MAKE) -C agents/orpheus-agent-audio-playback lint
	@echo "✅ orpheus-agent-audio-playback linted"

lint-video-motion:
	@echo "Linting orpheus-agent-video-motion..."
	@$(MAKE) -C agents/orpheus-agent-video-motion lint
	@echo "✅ orpheus-agent-video-motion linted"

lint-video-snapshotter:
	@echo "Linting orpheus-agent-video-snapshotter..."
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter lint
	@echo "✅ orpheus-agent-video-snapshotter linted"

lint-video-timelapser:
	@echo "Linting orpheus-agent-video-timelapser..."
	@$(MAKE) -C agents/orpheus-agent-video-timelapser lint
	@echo "✅ orpheus-agent-video-timelapser linted"

lint-bird-detection:
	@echo "Linting orpheus-agent-bird-detection..."
	@$(MAKE) -C agents/orpheus-agent-bird-detection lint
	@echo "✅ orpheus-agent-bird-detection linted"

lint-crow-detection:
	@echo "Linting orpheus-agent-crow-detection..."
	@$(MAKE) -C agents/orpheus-agent-crow-detection lint
	@echo "✅ orpheus-agent-crow-detection linted"

lint-event-correlator:
	@echo "Linting orpheus-agent-event-correlator..."
	@$(MAKE) -C agents/orpheus-agent-event-correlator lint
	@echo "✅ orpheus-agent-event-correlator linted"

lint-mqtt:
	@echo "Linting orpheus-mqtt..."
	@$(MAKE) -C services/orpheus-mqtt lint
	@echo "✅ orpheus-mqtt linted"

#==============================================================================
# Format Targets
#==============================================================================
format: format-common format-dashboard format-ui format-gps format-audio-motion format-audio-playback format-video-motion format-video-snapshotter format-video-timelapser format-bird-detection format-crow-detection format-event-correlator format-mqtt
	@echo "✅ All formatting complete"

mbake:
	@echo "Running mbake..."
	@find -L . -name 'Makefile' \
		-exec sh -c 'echo "→ $$1"; uvx mbake format "$$1"' _ {} \;

format-common:
	@echo "Formatting orpheus-common..."
	@$(MAKE) -C platform/orpheus-common format
	@echo "✅ orpheus-common formatted"

format-dashboard:
	@echo "Formatting orpheus-dashboard..."
	@$(MAKE) -C services/orpheus-dashboard format
	@echo "✅ orpheus-dashboard formatted"

format-ui:
	@echo "Formatting orpheus_ui..."
	@$(MAKE) -C services/orpheus_ui format
	@echo "✅ orpheus_ui formatted"

format-gps:
	@echo "Formatting orpheus-gps..."
	@$(MAKE) -C services/orpheus-gps format
	@echo "✅ orpheus-gps formatted"

format-audio-motion:
	@echo "Formatting orpheus-agent-audio-motion..."
	@$(MAKE) -C agents/orpheus-agent-audio-motion format
	@echo "✅ orpheus-agent-audio-motion formatted"

format-audio-playback:
	@echo "Formatting orpheus-agent-audio-playback..."
	@$(MAKE) -C agents/orpheus-agent-audio-playback format
	@echo "✅ orpheus-agent-audio-playback formatted"

format-video-motion:
	@echo "Formatting orpheus-agent-video-motion..."
	@$(MAKE) -C agents/orpheus-agent-video-motion format
	@echo "✅ orpheus-agent-video-motion formatted"

format-video-snapshotter:
	@echo "Formatting orpheus-agent-video-snapshotter..."
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter format
	@echo "✅ orpheus-agent-video-snapshotter formatted"

format-video-timelapser:
	@echo "Formatting orpheus-agent-video-timelapser..."
	@$(MAKE) -C agents/orpheus-agent-video-timelapser format
	@echo "✅ orpheus-agent-video-timelapser formatted"

format-bird-detection:
	@echo "Formatting orpheus-agent-bird-detection..."
	@$(MAKE) -C agents/orpheus-agent-bird-detection format
	@echo "✅ orpheus-agent-bird-detection formatted"

format-crow-detection:
	@echo "Formatting orpheus-agent-crow-detection..."
	@$(MAKE) -C agents/orpheus-agent-crow-detection format
	@echo "✅ orpheus-agent-crow-detection formatted"

format-event-correlator:
	@echo "Formatting orpheus-agent-event-correlator..."
	@$(MAKE) -C agents/orpheus-agent-event-correlator format
	@echo "✅ orpheus-agent-event-correlator formatted"

format-mqtt:
	@echo "Formatting orpheus-mqtt..."
	@$(MAKE) -C services/orpheus-mqtt format
	@echo "✅ orpheus-mqtt formatted"

#==============================================================================
# Clean Targets
#==============================================================================
clean: clean-common clean-dashboard clean-ui clean-gps clean-audio-motion clean-audio-playback clean-video-motion clean-video-snapshotter clean-video-timelapser clean-bird-detection clean-crow-detection clean-event-correlator clean-mqtt
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Clean complete"

clean-common:
	@echo "Cleaning orpheus-common..."
	@$(MAKE) -C platform/orpheus-common clean 2>/dev/null || true
	@echo "✅ orpheus-common cleaned"

clean-dashboard:
	@echo "Cleaning orpheus-dashboard..."
	@$(MAKE) -C services/orpheus-dashboard clean 2>/dev/null || true
	@echo "✅ orpheus-dashboard cleaned"

clean-ui:
	@echo "Cleaning orpheus_ui..."
	@$(MAKE) -C services/orpheus_ui clean 2>/dev/null || true
	@echo "✅ orpheus_ui cleaned"

clean-gps:
	@echo "Cleaning orpheus-gps..."
	@$(MAKE) -C services/orpheus-gps clean 2>/dev/null || true
	@echo "✅ orpheus-gps cleaned"

clean-audio-motion:
	@echo "Cleaning orpheus-agent-audio-motion..."
	@$(MAKE) -C agents/orpheus-agent-audio-motion clean 2>/dev/null || true
	@echo "✅ orpheus-agent-audio-motion cleaned"

clean-audio-playback:
	@echo "Cleaning orpheus-agent-audio-playback..."
	@$(MAKE) -C agents/orpheus-agent-audio-playback clean 2>/dev/null || true
	@echo "✅ orpheus-agent-audio-playback cleaned"

clean-video-motion:
	@echo "Cleaning orpheus-agent-video-motion..."
	@$(MAKE) -C agents/orpheus-agent-video-motion clean 2>/dev/null || true
	@echo "✅ orpheus-agent-video-motion cleaned"

clean-video-snapshotter:
	@echo "Cleaning orpheus-agent-video-snapshotter..."
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter clean 2>/dev/null || true
	@echo "✅ orpheus-agent-video-snapshotter cleaned"

clean-video-timelapser:
	@echo "Cleaning orpheus-agent-video-timelapser..."
	@$(MAKE) -C agents/orpheus-agent-video-timelapser clean 2>/dev/null || true
	@echo "✅ orpheus-agent-video-timelapser cleaned"

clean-bird-detection:
	@echo "Cleaning orpheus-agent-bird-detection..."
	@$(MAKE) -C agents/orpheus-agent-bird-detection clean 2>/dev/null || true
	@echo "✅ orpheus-agent-bird-detection cleaned"

clean-crow-detection:
	@echo "Cleaning orpheus-agent-crow-detection..."
	@$(MAKE) -C agents/orpheus-agent-crow-detection clean 2>/dev/null || true
	@echo "✅ orpheus-agent-crow-detection cleaned"

clean-event-correlator:
	@echo "Cleaning orpheus-agent-event-correlator..."
	@$(MAKE) -C agents/orpheus-agent-event-correlator clean 2>/dev/null || true
	@echo "✅ orpheus-agent-event-correlator cleaned"

clean-mqtt:
	@echo "Cleaning orpheus-mqtt..."
	@rm -rf services/orpheus-mqtt/venv 2>/dev/null || true
	@echo "✅ orpheus-mqtt cleaned"

#==============================================================================
# Service Management (Production)
#==============================================================================
services-install:
	@echo "Installing system services..."
	@$(MAKE) -C platform/orpheus-common install-service
	@$(MAKE) -C services/orpheus-mqtt install-service
	@$(MAKE) -C services/orpheus-gps install-service
	@$(MAKE) -C services/orpheus-dashboard install-service
	@$(MAKE) -C services/orpheus_ui install-service
	@$(MAKE) -C services/orpheus-bluetooth-autoconnect install-service
	@$(MAKE) -C agents/orpheus-agent-audio-motion install-service
	@$(MAKE) -C agents/orpheus-agent-audio-playback install-service
	@$(MAKE) -C agents/orpheus-agent-video-motion install-service
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter install-service
	@$(MAKE) -C agents/orpheus-agent-video-timelapser install-service
	@$(MAKE) -C agents/orpheus-agent-bird-detection install-service
	@$(MAKE) -C agents/orpheus-agent-crow-detection install-service
	@$(MAKE) -C agents/orpheus-agent-event-correlator install-service
	@echo "✅ Services installed"

services-start:
	@echo "Starting Orpheus services..."
	@$(MAKE) -C services/orpheus-mqtt service-start
	@sleep 2  # Wait for MQTT to be ready
	@$(MAKE) -C services/orpheus-gps service-start
	@$(MAKE) -C services/orpheus-dashboard service-start
	@$(MAKE) -C services/orpheus_ui service-start
	@$(MAKE) -C services/orpheus-bluetooth-autoconnect service-start
	@$(MAKE) -C agents/orpheus-agent-audio-motion service-start
	@$(MAKE) -C agents/orpheus-agent-audio-playback service-start
	@$(MAKE) -C agents/orpheus-agent-video-motion service-start
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter service-start
	@$(MAKE) -C agents/orpheus-agent-video-timelapser service-start
	@$(MAKE) -C agents/orpheus-agent-bird-detection service-start
	@$(MAKE) -C agents/orpheus-agent-crow-detection service-start
	@$(MAKE) -C agents/orpheus-agent-event-correlator service-start
	@echo "✅ Services started"

services-stop:
	@echo "Stopping Orpheus services..."
	@$(MAKE) -C agents/orpheus-agent-event-correlator service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-crow-detection service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-bird-detection service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-video-timelapser service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-video-motion service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-audio-playback service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-audio-motion service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-bluetooth-autoconnect service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus_ui service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-dashboard service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-mqtt service-stop 2>/dev/null || true
	@echo "✅ Services stopped"

services-restart: services-stop services-start
	@echo "✅ Services restarted"

update-services:
	@echo "Updating all services..."
	@$(MAKE) -C services/orpheus-dashboard update
	@$(MAKE) -C services/orpheus_ui update
	@$(MAKE) -C agents/orpheus-agent-audio-motion update
	@$(MAKE) -C agents/orpheus-agent-audio-playback update
	@$(MAKE) -C agents/orpheus-agent-video-motion update
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter update
	@$(MAKE) -C agents/orpheus-agent-video-timelapser update
	@$(MAKE) -C agents/orpheus-agent-bird-detection update
	@$(MAKE) -C agents/orpheus-agent-crow-detection update
	@$(MAKE) -C agents/orpheus-agent-event-correlator update
	@echo "✅ All services updated"

#==============================================================================
# Orchestration Targets
#==============================================================================

status-all:
	@echo "═══════════════════════════════════════════════════════════════"
	@echo "                    Orpheus Service Status"
	@echo "═══════════════════════════════════════════════════════════════"
	@systemctl list-units --type=service 'orpheus-*' --no-pager || \
		echo "Could not query systemd. Is it installed and are you on the Jetson?"
	@echo "═══════════════════════════════════════════════════════════════"

update-all:
	@echo "════════════════════════════════════════════════════════════════"
	@echo "                Updating All Orpheus Components"
	@echo "════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Step 1: Stopping all agents and services..."
	@$(MAKE) -C agents/orpheus-agent-event-correlator service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-crow-detection service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-bird-detection service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-video-timelapser service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-video-motion service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-audio-playback service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-audio-motion service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-bluetooth-autoconnect service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-dashboard service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-mqtt service-stop 2>/dev/null || true
	@echo ""
	@echo "Step 2: Updating orpheus-common library..."
	@cd platform/orpheus-common && $(MAKE) install-service
	@echo ""
	@echo "Step 3: Updating services (MQTT first, then others)..."
	@cd services/orpheus-mqtt && $(MAKE) update || true
	@cd services/orpheus-dashboard && $(MAKE) update || true
	@cd services/orpheus_ui && $(MAKE) update || true
	@cd services/orpheus-bluetooth-autoconnect && $(MAKE) update || true
	@echo ""
	@echo "Step 4: Updating agents..."
	@cd agents/orpheus-agent-audio-motion && $(MAKE) update || true
	@cd agents/orpheus-agent-audio-playback && $(MAKE) update || true
	@cd agents/orpheus-agent-video-motion && $(MAKE) update || true
	@cd agents/orpheus-agent-video-snapshotter && $(MAKE) update || true
	@cd agents/orpheus-agent-video-timelapser && $(MAKE) update || true
	@cd agents/orpheus-agent-bird-detection && $(MAKE) update || true
	@cd agents/orpheus-agent-crow-detection && $(MAKE) update || true
	@cd agents/orpheus-agent-event-correlator && $(MAKE) update || true
	@echo ""
	@echo "Step 5: Restarting services in dependency order..."
	@$(MAKE) services-start
	@echo ""
	@echo "════════════════════════════════════════════════════════════════"
	@echo "✅ All services updated and restarted"
	@echo "════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Run 'make status-all' to verify all services are running."

deploy-all: services-install services-start
	@echo ""
	@echo "✅ Deployment complete. Run 'make status-all' to verify."

check-models:
	@echo "Checking ML models in /data/orpheus/models/..."
	@if [ -d /data/orpheus/models ]; then \
		ls -lh /data/orpheus/models/*.pt 2>/dev/null || echo "⚠️  No .pt model files found"; \
	else \
		echo "⚠️  /data/orpheus/models/ directory not found"; \
		echo "   Crow detection requires aves-base-bio.pt and mt_70.pt"; \
	fi

logs-all:
	@echo "Streaming logs from all Orpheus services (Ctrl+C to exit)..."
	@journalctl -u "orpheus-*" -f

test-all:
	@echo "══════════════════════════════════════════════════════════════"
	@echo "  Running All Tests (continues on error to show all failures)"
	@echo "══════════════════════════════════════════════════════════════"
	@echo ""
	@echo "Testing platform/orpheus-common..."
	@cd platform/orpheus-common && $(MAKE) test || true
	@echo ""
	@echo "Testing services..."
	@for dir in services/orpheus-dashboard services/orpheus_ui; do \
		if [ -f "$$dir/Makefile" ]; then \
			echo ""; \
			echo "Testing $$dir..."; \
			(cd "$$dir" && $(MAKE) test) || true; \
		fi; \
	done
	@echo ""
	@echo "Testing agents (dynamic discovery)..."
	@for dir in agents/orpheus-agent-*; do \
		if [ -f "$$dir/Makefile" ]; then \
			echo ""; \
			echo "Testing $$dir..."; \
			(cd "$$dir" && $(MAKE) test) || true; \
		fi; \
	done
	@echo ""
	@echo "══════════════════════════════════════════════════════════════"
	@echo "✅ All tests complete (check output above for any failures)"
	@echo "══════════════════════════════════════════════════════════════"

#==============================================================================
# Dependency Management
#==============================================================================
# All version constraints are centralized in requirements-constraints.txt
# Individual projects should use matching versions.

check-deps:
	@echo "Checking dependency consistency across monorepo..."
	@python3 tools/scripts/check_dependency_consistency.py

# Alias for CI
validate-deps: check-deps

#==============================================================================
# Legacy/Compatibility Targets
#==============================================================================
# Keep these for backwards compatibility with existing scripts

# Generic shared venv updater - works on any system
update_shared_venv:
	@echo "Updating shared virtual environment at $(VENV_PATH)..."
	@if [ -z "$(VENV_PATH)" ]; then \
		echo "ERROR: VENV_PATH is required"; \
		echo "Usage: make update_shared_venv VENV_PATH=/path/to/venv"; \
		exit 1; \
	fi
	@$(VENV_PATH)/bin/pip install --upgrade pip
	@$(VENV_PATH)/bin/pip install -c requirements-constraints.txt -e platform/orpheus-common
	@$(VENV_PATH)/bin/pip install -c requirements-constraints.txt -e services/orpheus-dashboard
	@$(VENV_PATH)/bin/pip install -c requirements-constraints.txt -e services/orpheus_ui
	@$(VENV_PATH)/bin/pip install -c requirements-constraints.txt -e agents/orpheus-agent-audio-motion
	@echo "✅ Shared venv updated with consistent dependency versions"

#==============================================================================
# Run Targets
#==============================================================================
run-ui:
	@echo "Starting Orpheus UI backend on http://0.0.0.0:8082"
	@$(MAKE) -C services/orpheus_ui run

#==============================================================================
# macOS Development Stack
#==============================================================================
dev-stack:
	@./scripts/dev-stack.sh start $(SVC)

dev-stop:
	@./scripts/dev-stack.sh stop $(SVC)

dev-restart:
	@./scripts/dev-stack.sh restart $(SVC)

dev-status:
	@./scripts/dev-stack.sh status

dev-logs:
	@./scripts/dev-stack.sh logs $(SVC)
