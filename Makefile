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

.PHONY: help install test coverage-all lint format clean mbake venv-all \
	install-common install-ui install-gps install-audio-motion install-audio-playback install-audio-events install-video-motion install-video-snapshotter install-video-timelapser install-bird-detection install-crow-detection install-event-correlator install-backplane install-bluetooth \
	test-common test-ui test-gps test-audio-motion test-audio-playback test-audio-events test-video-motion test-video-snapshotter test-video-timelapser test-bird-detection test-crow-detection test-event-correlator \
	coverage-common coverage-ui coverage-gps coverage-audio-motion coverage-audio-playback coverage-audio-events coverage-video-motion coverage-video-snapshotter coverage-video-timelapser coverage-bird-detection coverage-crow-detection coverage-event-correlator \
	lint-common lint-ui lint-gps lint-audio-motion lint-audio-playback lint-audio-events lint-video-motion lint-video-snapshotter lint-video-timelapser lint-bird-detection lint-crow-detection lint-event-correlator lint-backplane \
	format-common format-ui format-gps format-audio-motion format-audio-playback format-audio-events format-video-motion format-video-snapshotter format-video-timelapser format-bird-detection format-crow-detection format-event-correlator format-backplane \
	clean-common clean-ui clean-gps clean-audio-motion clean-audio-playback clean-audio-events clean-video-motion clean-video-snapshotter clean-video-timelapser clean-bird-detection clean-crow-detection clean-event-correlator clean-backplane clean-bluetooth \
	services-install services-start services-stop services-restart \
	install-host install-backbone install-log-bounds upsert-backbone-env check-installable \
	update-services \
	sim-up sim-down sim-logs sim-status sim-fleet-up sim-validate \
	sim-distributed-up sim-distributed-validate sim-distributed-down \
	docs-build docs-serve docs-preview docs-pages \
	status-all update-all logs-all test-all deploy-all check-models download-models run-ui verify-deploy \
	backfill-root-event-ids backfill-root-event-ids-dry-run \
	backfill-entity-types backfill-entity-types-dry-run test-bdd test-bash sim-matrix-ci reconcile manifests guardrails \
	storage-report storage-sweep \
	show-deployed \
	dev-stack dev-stop dev-restart dev-status dev-logs

# Python projects in the monorepo
PYTHON_PROJECTS = platform/orpheus-common services/orpheus_ui services/orpheus-gps agents/orpheus-agent-audio-motion agents/orpheus-agent-audio-playback agents/orpheus-agent-audio-events agents/orpheus-agent-video-motion agents/orpheus-agent-video-snapshotter agents/orpheus-agent-video-timelapser agents/orpheus-agent-bird-detection agents/orpheus-agent-crow-detection agents/orpheus-agent-event-correlator
# All projects (including non-Python)
ALL_PROJECTS = $(PYTHON_PROJECTS) services/orpheus-backplane

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
	@echo "  make test-all        - Run all tests (continues on error; exits red if any suite failed)"
	@echo "  make coverage-all    - Run tests with coverage for all Python projects"
	@echo "  make lint            - Lint all code with ruff"
	@echo "  make format          - Format all code with ruff"
	@echo "  make mbake           - Format all Makefiles with mbake using uvx"
	@echo "  make clean           - Remove build artifacts and venvs"
	@echo "  make check-deps      - Validate dependency version consistency"
	@echo ""
	@echo "Individual Project Targets:"
	@echo "  make install-common           - Install orpheus-common"
	@echo "  make install-ui               - Install orpheus_ui (port 8080)"
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
	@echo "  make dev-logs                 - Tail all logs (or: make dev-logs SVC=ui)"
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
	@echo "  make install-log-bounds - Opt-in: bound host logs (persistent capped journal, no syslog mirror)"
	@echo "  make services-start     - Start all services"
	@echo "  make services-stop      - Stop all services"
	@echo "  make services-restart   - Restart all services"
	@echo "  make status-all         - Check status of all services"
	@echo "  make update-all         - Update all services and agents (with proper ordering)"
	@echo "  make logs-all           - Stream logs from all services"
	@echo "  make check-models       - Check if ML models are present"
	@echo "  make backfill-root-event-ids-dry-run - Preview root_event_id backfill on legacy rows"
	@echo "  make backfill-root-event-ids         - Backfill root_event_id on legacy detection rows"
	@echo "  make backfill-entity-types-dry-run   - Preview entity_type backfill on legacy entities"
	@echo "  make backfill-entity-types           - Backfill entity_type on legacy entities rows"
	@echo "  make test-bdd                        - Run the end-to-end BDD scenarios (tests/bdd)"
	@echo "  make test-bash                       - Run bash script tests (bats-core, tests/bats)"
	@echo "  make update-services    - Update all services (code + restart)"
	@echo "  make verify-deploy      - Read-only post-upgrade health check (venv imports + systemd units + models)"
	@echo ""
	@echo "Storage retention (one component owns every deletion):"
	@echo "  make storage-report     - What the sweep WOULD delete, deleting nothing"
	@echo "  make storage-sweep      - Run one sweep now, outside the timer's schedule"
	@echo ""
	@echo "Documentation site:"
	@echo "  make docs-serve         - Live-reload preview while writing (site root)"
	@echo "  make docs-preview       - Preview the BUILT site at the published path prefix"
	@echo "  make docs-build         - Strict build into ./site (what CI runs)"
	@echo "  make docs-pages         - Assemble the Pages artifact (root + docs/)"
	@echo ""

#==============================================================================
# Install Targets
#==============================================================================
install: install-common install-ui install-gps install-audio-motion install-audio-playback install-audio-events install-video-motion install-video-snapshotter install-video-timelapser install-bird-detection install-crow-detection install-event-correlator
	@echo "✅ All components installed"

install-common:
	@echo "Installing orpheus-common..."
	@$(MAKE) -C platform/orpheus-common install
	@echo "✅ orpheus-common installed"

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

install-audio-events: install-common
	@echo "Installing orpheus-agent-audio-events..."
	@$(MAKE) -C agents/orpheus-agent-audio-events install
	@echo "✅ orpheus-agent-audio-events installed"
	@echo "ℹ  Run 'make download-models' to fetch the PANNs Cnn14 checkpoint."

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

install-backplane:
	@echo "Installing orpheus-backplane dependencies (if any)..."
	@$(MAKE) -C services/orpheus-backplane install-python
	@echo "✅ orpheus-backplane installed"

#==============================================================================
# Per-host subset install (distributed deployment)
#   docs/designs/distributed-deployment.md — go host-to-host installing a SUBSET
#   of components, each pointing back at a movable backbone (Jetson or a NUC).
#   Single-host `make install` is unchanged; these are pure additions.
#==============================================================================

# Per-host env file (the one orpheus-gps already reads). Absent => loopback
# default => single-host byte-identical to today.
ORPHEUS_ENV_FILE ?= /opt/orpheus/config/.env

# Canonical short-name -> component dir map (the `-C <path>` each install-<name>
# rule already hardcodes, factored once). Single source for dir lookup AND the
# INSTALLABLE validation set, so they can't drift.
COMPONENT_DIRS := \
	common:platform/orpheus-common \
	ui:services/orpheus_ui \
	gps:services/orpheus-gps \
	bluetooth-autoconnect:services/orpheus-bluetooth-autoconnect \
	audio-motion:agents/orpheus-agent-audio-motion \
	audio-playback:agents/orpheus-agent-audio-playback \
	audio-events:agents/orpheus-agent-audio-events \
	video-motion:agents/orpheus-agent-video-motion \
	video-snapshotter:agents/orpheus-agent-video-snapshotter \
	video-timelapser:agents/orpheus-agent-video-timelapser \
	bird-detection:agents/orpheus-agent-bird-detection \
	crow-detection:agents/orpheus-agent-crow-detection \
	event-correlator:agents/orpheus-agent-event-correlator

# Installable short-names, derived from the map (no second list to keep in sync).
INSTALLABLE := $(foreach p,$(COMPONENT_DIRS),$(firstword $(subst :, ,$(p))))

# install-host COMPONENTS="crow-detection bird-detection ..." [BACKBONE=nats://host:4222]
#   Installs ONLY the named components on this host and (optionally) points them
#   at a remote backbone. Validate names first; run non-root dev installs; write
#   the backbone env only after (so a `sudo` slip trips the existing root
#   rejection before anything is written); then install the systemd units.
#   Do NOT run as root — the dev installs reject it (see install-common).
install-host:
	@test -n "$(COMPONENTS)" || { echo "ERROR: COMPONENTS=\"name ...\" required. Valid: $(INSTALLABLE)"; exit 2; }
	@for c in $(COMPONENTS); do \
	  case " $(INSTALLABLE) " in *" $$c "*) ;; \
	    *) echo "ERROR: unknown component '$$c'. Valid: $(INSTALLABLE)"; exit 2;; esac; \
	done
	@echo "Installing subset on this host: $(COMPONENTS)"
	@$(MAKE) install-common
	@for c in $(COMPONENTS); do \
	  case "$$c" in common|bluetooth-autoconnect) continue;; esac; \
	  $(MAKE) install-$$c || exit $$?; \
	done
	@if [ -n "$(BACKBONE)" ]; then $(MAKE) upsert-backbone-env BACKBONE="$(BACKBONE)"; fi
	@$(MAKE) -C platform/orpheus-common install-service
	@for c in $(COMPONENTS); do \
	  [ "$$c" = common ] && continue; \
	  d=$$(echo "$(COMPONENT_DIRS)" | tr ' ' '\n' | sed -n "s/^$$c://p"); \
	  $(MAKE) -C "$$d" install-service || exit $$?; \
	done
	@echo "✅ Installed subset: $(COMPONENTS)  (backbone: $${BACKBONE:-loopback default})"

# install-backbone [LISTEN=0.0.0.0:4222] [AUTH_FILE=/path/nats.auth]
#   Install the NATS/JetStream broker on this host (a NUC, or co-located on the
#   Jetson). Loopback default = today's posture. To serve OTHER hosts, pass LISTEN
#   (a LAN bind) + AUTH_FILE: the installer REFUSES a non-loopback listener without
#   auth (the one guardrail, ADR 0018), then deploys nats.distributed.conf (the
#   shipped loopback nats.conf is never edited). Monitoring stays loopback. TLS /
#   reverse proxy are owner-managed.
BACKPLANE_CONF_DIR ?= /etc/orpheus/backplane

install-log-bounds:   ## opt-in: bound this HOST's logs (journald persistent + capped, no syslog mirror)
	@echo "This writes /etc/systemd/journald.conf.d/10-orpheus.conf and restarts"
	@echo "systemd-journald. It is host-wide, not scoped to Orpheus units."
	@echo "Undo at any time: sudo rm the file and restart systemd-journald."
	@echo ""
	@sudo deploy/journald/install-log-bounds.sh

install-backbone:
	@# Safety gate FIRST (before any install, so a bad invocation fails fast):
	@# refuse to open a non-loopback listener without an auth file.
	@if [ -n "$(LISTEN)" ] && [ "$(LISTEN)" != "127.0.0.1:4222" ] && [ "$(LISTEN)" != "loopback" ]; then \
	  test -n "$(AUTH_FILE)" || { echo "ERROR: refusing to open broker listener '$(LISTEN)' without AUTH_FILE=/path/to/nats.auth — even a trusted LAN needs user/pass (ADR 0018)"; exit 2; }; \
	  test -f "$(AUTH_FILE)" || { echo "ERROR: AUTH_FILE '$(AUTH_FILE)' not found"; exit 2; }; \
	fi
	@echo "Installing orpheus-backplane (NATS/JetStream broker)..."
	@$(MAKE) -C services/orpheus-backplane install-python
	@$(MAKE) -C services/orpheus-backplane install-service
	@if [ -n "$(LISTEN)" ] && [ "$(LISTEN)" != "127.0.0.1:4222" ] && [ "$(LISTEN)" != "loopback" ]; then \
	  echo "Opening LAN listener $(LISTEN) via nats.distributed.conf (auth: $(AUTH_FILE))..."; \
	  sudo install -m 0644 services/orpheus-backplane/config/nats.distributed.conf $(BACKPLANE_CONF_DIR)/nats.conf; \
	  sudo install -m 0600 "$(AUTH_FILE)" $(BACKPLANE_CONF_DIR)/nats.auth; \
	  sudo sed -i "s|^listen:.*|listen: $(LISTEN)|" $(BACKPLANE_CONF_DIR)/nats.conf; \
	  echo "✅ backbone listening on $(LISTEN) with auth. Restart: make -C services/orpheus-backplane restart"; \
	else \
	  echo "✅ backbone installed (loopback default; open the LAN with LISTEN=0.0.0.0:4222 AUTH_FILE=...)"; \
	fi

# upsert-backbone-env — idempotently set the single backbone key in the per-host
#   env file. Reuses /opt/orpheus/config/.env (no new file). Rollback = remove the
#   key (or the file) + restart -> loopback default.
#   Mode 0640 (group orpheus where the group exists), NOT world-readable: on an
#   auth-gated backbone BACKBONE carries credentials (nats://user:pass@host:4222,
#   ADR 0018). systemd reads EnvironmentFile= as root before dropping privileges,
#   and the orpheus service user gets group read for manual CLI runs.
upsert-backbone-env:
	@test -n "$(BACKBONE)" || { echo "ERROR: BACKBONE=nats://host:port required"; exit 2; }
	@dir=$$(dirname "$(ORPHEUS_ENV_FILE)"); \
	 sudo mkdir -p "$$dir"; \
	 tmp=$$(mktemp); \
	 if [ -f "$(ORPHEUS_ENV_FILE)" ]; then \
	   grep -v '^ORPHEUS_EVENT_BUS__NATS_URL=' "$(ORPHEUS_ENV_FILE)" > "$$tmp" || true; \
	 fi; \
	 echo "ORPHEUS_EVENT_BUS__NATS_URL=$(BACKBONE)" >> "$$tmp"; \
	 if getent group orpheus >/dev/null 2>&1; then \
	   sudo install -m 0640 -g orpheus "$$tmp" "$(ORPHEUS_ENV_FILE)"; \
	 else \
	   sudo install -m 0640 "$$tmp" "$(ORPHEUS_ENV_FILE)"; \
	 fi; \
	 rm -f "$$tmp"; \
	 echo "✅ Set ORPHEUS_EVENT_BUS__NATS_URL=$(BACKBONE) in $(ORPHEUS_ENV_FILE) (mode 0640 — the URL may carry credentials)"

# check-installable — anti-rot guard (run in CI). Asserts the per-host install set
#   (COMPONENT_DIRS / INSTALLABLE) and the all-in-one `services-install` agree, so
#   a component added to one but not the other can't silently fall out of a
#   per-host install. Catches service-only members (e.g. bluetooth-autoconnect)
#   that have no dev install-<name> target. The broker is install-backbone, not a
#   per-host component, so it's excluded.
check-installable:
	@echo "Checking COMPONENT_DIRS/INSTALLABLE vs services-install..."
	@si_dirs=$$(sed -n '/^services-install:/,/^$$/p' $(firstword $(MAKEFILE_LIST)) | grep -oE '\-C [^ ]+' | awk '{print $$2}' | sort -u); \
	 cd_dirs=$$(echo "$(COMPONENT_DIRS)" | tr ' ' '\n' | sed 's/^[^:]*://' | sort -u); \
	 broker=services/orpheus-backplane; \
	 missing=""; \
	 for d in $$si_dirs; do \
	   [ "$$d" = "$$broker" ] && continue; \
	   echo "$$cd_dirs" | grep -qx "$$d" || missing="$$missing [in services-install, not COMPONENT_DIRS: $$d]"; \
	 done; \
	 for d in $$cd_dirs; do \
	   echo "$$si_dirs" | grep -qx "$$d" || missing="$$missing [in COMPONENT_DIRS, not services-install: $$d]"; \
	 done; \
	 if [ -n "$$missing" ]; then echo "ERROR: install-set drift:$$missing"; exit 1; fi; \
	 echo "✅ COMPONENT_DIRS/INSTALLABLE and services-install agree"

# guardrails — static drift checks for the mechanically-checkable non-negotiables
# (agent wiring #5, docs-site nav #12, non-negotiable count #11). Stdlib only, no
# venv — safe to run in pre-commit and CI. See scripts/check_guardrails.py.
guardrails:
	@python3 scripts/check_guardrails.py

#==============================================================================
# Test Targets
#==============================================================================
# Individual test targets for running specific component tests
# Use 'make test-all' to run all tests across the monorepo

test-common:
	@echo "Testing orpheus-common..."
	@$(MAKE) -C platform/orpheus-common test
	@echo "✅ orpheus-common tests passed"

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

test-audio-events:
	@echo "Testing orpheus-agent-audio-events..."
	@$(MAKE) -C agents/orpheus-agent-audio-events test
	@echo "✅ orpheus-agent-audio-events tests passed"

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
coverage-all: coverage-common coverage-ui coverage-gps coverage-audio-motion coverage-audio-playback coverage-audio-events coverage-video-motion coverage-video-snapshotter coverage-video-timelapser coverage-bird-detection coverage-crow-detection coverage-event-correlator
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

coverage-audio-events:
	@echo ""
	@echo "📊 Coverage for orpheus-agent-audio-events..."
	@echo "============================================"
	@cd agents/orpheus-agent-audio-events && \
		if [ -d venv ]; then \
			. venv/bin/activate && PYTHONPATH=src python -m pytest tests/ --cov=orpheus_agent_audio_events $(COV_REPORTS) --cov-fail-under=70; \
		else \
			echo "⚠️  No venv found. Run 'make install-audio-events' first."; \
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
lint: lint-common lint-ui lint-gps lint-audio-motion lint-audio-playback lint-audio-events lint-video-motion lint-video-snapshotter lint-video-timelapser lint-bird-detection lint-crow-detection lint-event-correlator lint-backplane
	@echo "✅ All linting complete"

lint-common:
	@echo "Linting orpheus-common..."
	@$(MAKE) -C platform/orpheus-common lint
	@echo "✅ orpheus-common linted"

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

lint-audio-events:
	@echo "Linting orpheus-agent-audio-events..."
	@$(MAKE) -C agents/orpheus-agent-audio-events lint
	@echo "✅ orpheus-agent-audio-events linted"

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

lint-backplane:
	@echo "Linting orpheus-backplane..."
	@$(MAKE) -C services/orpheus-backplane lint
	@echo "✅ orpheus-backplane linted"

#==============================================================================
# Format Targets
#==============================================================================
format: format-common format-ui format-gps format-audio-motion format-audio-playback format-audio-events format-video-motion format-video-snapshotter format-video-timelapser format-bird-detection format-crow-detection format-event-correlator format-backplane
	@echo "✅ All formatting complete"

mbake:
	@echo "Running mbake..."
	@find -L . -name 'Makefile' \
		-exec sh -c 'echo "→ $$1"; uvx mbake format "$$1"' _ {} \;

format-common:
	@echo "Formatting orpheus-common..."
	@$(MAKE) -C platform/orpheus-common format
	@echo "✅ orpheus-common formatted"

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

format-audio-events:
	@echo "Formatting orpheus-agent-audio-events..."
	@$(MAKE) -C agents/orpheus-agent-audio-events format
	@echo "✅ orpheus-agent-audio-events formatted"

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

format-backplane:
	@echo "Formatting orpheus-backplane..."
	@$(MAKE) -C services/orpheus-backplane format
	@echo "✅ orpheus-backplane formatted"

#==============================================================================
# Clean Targets
#==============================================================================
clean: clean-common clean-ui clean-gps clean-audio-motion clean-audio-playback clean-audio-events clean-video-motion clean-video-snapshotter clean-video-timelapser clean-bird-detection clean-crow-detection clean-event-correlator clean-backplane
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

clean-audio-events:
	@echo "Cleaning orpheus-agent-audio-events..."
	@$(MAKE) -C agents/orpheus-agent-audio-events clean 2>/dev/null || true
	@echo "✅ orpheus-agent-audio-events cleaned"

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

clean-backplane:
	@echo "Cleaning orpheus-backplane..."
	@rm -rf services/orpheus-backplane/venv 2>/dev/null || true
	@echo "✅ orpheus-backplane cleaned"

#==============================================================================
# Service Management (Production)
#==============================================================================
services-install:
	@echo "Installing system services..."
	@$(MAKE) -C platform/orpheus-common install-service
	@$(MAKE) -C services/orpheus-backplane install-service
	@$(MAKE) -C services/orpheus-gps install-service
	@$(MAKE) -C services/orpheus_ui install-service
	@$(MAKE) -C services/orpheus-bluetooth-autoconnect install-service
	@$(MAKE) -C agents/orpheus-agent-audio-motion install-service
	@$(MAKE) -C agents/orpheus-agent-audio-playback install-service
	@$(MAKE) -C agents/orpheus-agent-audio-events install-service
	@$(MAKE) -C agents/orpheus-agent-video-motion install-service
	@$(MAKE) -C agents/orpheus-agent-video-snapshotter install-service
	@$(MAKE) -C agents/orpheus-agent-video-timelapser install-service
	@$(MAKE) -C agents/orpheus-agent-bird-detection install-service
	@$(MAKE) -C agents/orpheus-agent-crow-detection install-service
	@$(MAKE) -C agents/orpheus-agent-event-correlator install-service
	@echo "✅ Services installed"

services-start:
	@echo "Starting Orpheus services..."
	@$(MAKE) -C services/orpheus-backplane service-start
	@sleep 2  # Wait for MQTT to be ready
	@$(MAKE) -C services/orpheus-gps service-start
	@$(MAKE) -C services/orpheus_ui service-start
	@$(MAKE) -C services/orpheus-bluetooth-autoconnect service-start
	@$(MAKE) -C agents/orpheus-agent-audio-motion service-start
	@$(MAKE) -C agents/orpheus-agent-audio-playback service-start
	@$(MAKE) -C agents/orpheus-agent-audio-events service-start
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
	@$(MAKE) -C agents/orpheus-agent-audio-events service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-audio-playback service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-audio-motion service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-bluetooth-autoconnect service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus_ui service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-backplane service-stop 2>/dev/null || true
	@echo "✅ Services stopped"

services-restart: services-stop services-start
	@echo "✅ Services restarted"

# ---------------------------------------------------------------------------
# Simulacrum — containerized environment to run the collective under test
# (no Jetson/hardware needed). sim-* (not dev-*, which drive the local
# dev-stack.sh). Backed by docker-compose.dev.yml.
# ---------------------------------------------------------------------------
COMPOSE ?= docker compose -f docker-compose.dev.yml

# SIM_MODE=replay make sim-up — replay the REAL clips in artifacts/audio-samples
# as audio.motion events instead of synthetic detections (make passes the env
# through to compose interpolation; the fleet profile then classifies real audio).
sim-up:
	@echo "Building + starting the Orpheus Simulacrum (demo: synthetic source)..."
	@$(COMPOSE) --profile demo up -d --build
	@echo "✅ Simulacrum up.  Logs: make sim-logs   Status: make sim-status   Stop: make sim-down"

sim-fleet-up:
	@echo "Building + starting the REAL detection fleet (bird/crow/audio-events + models)..."
	@echo "    (first build is heavy — torch/fairseq/onnx. Models mounted from artifacts/.)"
	@# The demo source emits corvid species.detected of its own. Left running, it
	@# satisfies the cascade assertion whether or not a single real model is up,
	@# so the fleet replaces it rather than joining it.
	@$(COMPOSE) --profile demo rm -sf orpheus-sim-source >/dev/null 2>&1 || true
	@$(COMPOSE) --profile fleet up -d --build
	@echo "✅ Fleet up.  Validate the real-audio cascade: make sim-validate   Stop: make sim-down"

# Real-audio end-to-end validation: inject one audio.motion (crow clip) into the
# running fleet and assert the cascade lands an EntityEvent. Needs sim-fleet-up.
#
# The assertion runs on the HOST (it injects over the broker), so it needs the
# platform venv — which is gitignored and which nothing in the README's
# five-minute block creates. Build it on demand rather than dying with "No such
# file or directory" at the step that is supposed to prove the system works.
SIM_VALIDATE_PYTHON := platform/orpheus-common/venv/bin/python

$(SIM_VALIDATE_PYTHON):
	@echo "Building the platform venv this check runs from (one-off)..."
	@$(MAKE) install-common

sim-validate: $(SIM_VALIDATE_PYTHON)
	@echo "Validating the real-audio cascade against the running fleet..."
	@ORPHEUS_E2E_REAL_AUDIO=1 $(SIM_VALIDATE_PYTHON) -m pytest tests/e2e_bdd -v -m real_audio

sim-down:
	@echo "Stopping the Orpheus Simulacrum (all profiles)..."
	@$(COMPOSE) --profile demo --profile fleet down -v

sim-logs:
	@$(COMPOSE) --profile demo --profile fleet logs -f

sim-status:
	@$(COMPOSE) --profile demo --profile fleet ps

# --- distributed-topology validation (docs/designs/distributed-deployment.md §3) ---
# Layer the distributed overlay over the dev compose: the backbone is reached by a
# stand-in hostname (backbone-nuc alias) via the production env seam, and
# cold-broker reconnect (E3) is exercised. This is how the per-host config gets
# "tested" without real hosts.
COMPOSE_DIST ?= docker compose -f docker-compose.dev.yml -f docker-compose.distributed.yml

sim-distributed-up:
	@echo "Starting the distributed Simulacrum (backbone via env seam + backbone-nuc alias)..."
	@$(COMPOSE_DIST) --profile demo up -d --build
	@echo "✅ Up. Validate: make sim-distributed-validate   Stop: make sim-distributed-down"

sim-distributed-validate:
	@bash docker/sim-distributed-validate.sh

sim-distributed-down:
	@$(COMPOSE_DIST) --profile demo --profile fleet down -v

#==============================================================================
# Docs site (MkDocs Material — in-repo, single-source over docs/)
#   Renders the existing docs/ tree as a searchable
#   site; agents keep reading the raw .md. uvx (ADR 0009) — no venv to manage.
#==============================================================================
DOCS_MKDOCS ?= uvx --with-requirements docs/requirements-docs.txt mkdocs
DOCS_PREVIEW_PORT ?= 8000

docs-build:   ## build the static docs site into ./site (gates broken nav via --strict)
	@$(DOCS_MKDOCS) build --strict

docs-serve:   ## live-reload preview at http://127.0.0.1:8000
	@$(DOCS_MKDOCS) serve

# The published layout is not the built site: the docs live one level down at
# /orpheus/docs/ so the Pages root stays free for whatever else goes there.
# This assembles that layout — the placeholder at the root, the site under
# docs/ — and it is the SAME target CI uploads, so preview and production
# cannot drift.
docs-pages: docs-build   ## assemble the Pages artifact (root placeholder + docs/)
	@rm -rf site-pages
	@mkdir -p site-pages/docs
	@cp deploy/pages/index.html site-pages/index.html
	@cp -R site/. site-pages/docs/
	@echo "✓ Pages artifact assembled in ./site-pages (root placeholder + docs/)"

# docs-serve answers at the site root; the published site lives under a path
# prefix, so link bases, the search index and asset URLs differ there. This
# serves the real artifact at the real prefix — use it before publishing.
docs-preview: docs-pages   ## preview the BUILT site exactly as it will be published
	@python3 tools/scripts/serve_docs_preview.py --dir site-pages --prefix /orpheus/ --port $(DOCS_PREVIEW_PORT)

update-services:
	@echo "Updating all services..."
	# Step 1: install the platform library FIRST. Every agent/service's
	# ``make deploy`` (see make/common_deploy.mk) reinstalls
	# orpheus-common from ``/opt/orpheus/platform/orpheus-common`` —
	# NOT from the git tree. So if we don't run platform/orpheus-common
	# install-service first, every deploy step below silently
	# reinstalls the STALE platform from /opt and the agents end up
	# running old code even though the source tree was pulled. This is
	# the bug that bit a user mid-deploy. ``update-all`` (Step 2)
	# already does this; ``update-services`` was missing it.
	@echo "Step 1: Updating platform library (orpheus-common)..."
	@$(MAKE) -C platform/orpheus-common install-service
	@echo "Step 2: Updating (or installing, if new) service code..."
	@# A component the OLD deploy never had (a NEW agent on this branch, e.g.
	@# audio-events / event-correlator) has no deploy dir yet, so `update` -> `deploy`
	@# would fail its _deploy-check. Install-or-update per component so new agents
	@# actually land instead of aborting the run or being silently skipped.
	@# Every deployed component, not just UI + agents: gps and
	@# bluetooth-autoconnect must ride the same upgrade or they keep running
	@# old code against a transport the upgrade may have replaced.
	@# `|| exit $$?` on both branches: a for-loop's exit status is its LAST
	@# iteration's, so without it a mid-loop failure still prints the
	@# success banner while a component runs stale code.
	@for c in services/orpheus_ui services/orpheus-gps services/orpheus-bluetooth-autoconnect $(filter agents/%,$(PYTHON_PROJECTS)); do \
		name=$$(basename $$c); \
		case "$$c" in \
			services/orpheus_ui) root="$(DEPLOY_PREFIX)/ui";; \
			services/*) root="$(DEPLOY_PREFIX)/services/$$name";; \
			*) root="$(DEPLOY_PREFIX)/agents/$$name";; \
		esac; \
		if [ -d "$$root" ]; then \
			echo "  updating $$name"; $(MAKE) -C $$c update || exit $$?; \
		else \
			echo "  $$name not installed at $$root - installing (new component)"; $(MAKE) -C $$c install-service || exit $$?; \
		fi; \
	done
	@echo "✅ All services updated"
	@echo "   Run 'make verify-deploy' to confirm the upgrade left a healthy system."

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
	@$(MAKE) -C agents/orpheus-agent-audio-events service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-audio-playback service-stop 2>/dev/null || true
	@$(MAKE) -C agents/orpheus-agent-audio-motion service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-bluetooth-autoconnect service-stop 2>/dev/null || true
	@$(MAKE) -C services/orpheus-backplane service-stop 2>/dev/null || true
	@echo ""
	@echo "Step 2: Updating orpheus-common library..."
	@cd platform/orpheus-common && $(MAKE) install-service
	@echo ""
	@echo "Step 3: Updating services (MQTT first, then others)..."
	@cd services/orpheus-backplane && $(MAKE) update || true
	@cd services/orpheus_ui && $(MAKE) update || true
	@cd services/orpheus-bluetooth-autoconnect && $(MAKE) update || true
	@echo ""
	@echo "Step 4: Updating agents..."
	@cd agents/orpheus-agent-audio-motion && $(MAKE) update || true
	@cd agents/orpheus-agent-audio-playback && $(MAKE) update || true
	@cd agents/orpheus-agent-audio-events && $(MAKE) update || true
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
	@echo "Checking ML models in $(ORPHEUS_DATA_ROOT)/models/..."
	@if [ -d "$(ORPHEUS_DATA_ROOT)/models" ]; then \
		found=0; \
		for f in "$(ORPHEUS_DATA_ROOT)"/models/*.pt "$(ORPHEUS_DATA_ROOT)"/models/*.pth \
		         "$(ORPHEUS_DATA_ROOT)"/models/*.onnx "$(ORPHEUS_DATA_ROOT)"/models/*.tflite; do \
			[ -e "$$f" ] || continue; \
			ls -lhL "$$f"; \
			found=1; \
		done; \
		[ "$$found" = "1" ] || echo "⚠️  No model files found"; \
	else \
		echo "⚠️  $(ORPHEUS_DATA_ROOT)/models/ directory not found"; \
		echo "    Defaults to /data/orpheus; on a dev machine set the data root:"; \
		echo "    make check-models ORPHEUS_DATA_ROOT=\$$HOME/data/orpheus"; \
	fi
	@echo ""
	@echo "Required models:"
	@echo "  - Bird detection (BirdNET):     birdnet.onnx — from 'git lfs pull' (artifacts/models/),"
	@echo "                                  or 'make -C agents/orpheus-agent-bird-detection download-models'"
	@echo "  - Crow detection (AVES + MT):   aves-base-bio.pt, mt_70.pt — see the crow-detection README"
	@echo "  - Audio events (PANNs SED):     panns_cnn14_decision_level_max.pth — 'make download-models'"
	@echo ""
	@echo "  'make dev-stack' symlinks whatever is in artifacts/models/ into the data root."

download-models:
	@echo "Downloading PANNs Cnn14 SED checkpoint for orpheus-agent-audio-events..."
	@$(MAKE) -C agents/orpheus-agent-audio-events download-models
	@echo ""
	@echo "ℹ  AVES/MT models for crow-detection are not automated yet —"
	@echo "    see agents/orpheus-agent-crow-detection/README.md for the manual"
	@echo "    download steps."

# verify-deploy — fast, READ-ONLY post-upgrade health check. Run on the box
# after 'make update-services' (or update-all) to answer "did the upgrade
# actually leave a healthy system?". Composes EXISTING checks, no new deps:
#   1. Venv import smoke. On a DEPLOYED host ($(DEPLOY_PREFIX) exists) this
#      checks the venvs systemd ACTUALLY RUNS (/opt/orpheus/{platform,agents,
#      services,ui}/*/venv), not the repo working-tree venvs `make install`
#      builds — and compares each venv's installed orpheus-common against the
#      repo's platform/orpheus-common/VERSION, catching the stale-code case
#      common_deploy.mk downgrades to a warning. On a dev box (no
#      $(DEPLOY_PREFIX)) it falls back to the working-tree venvs. Missing
#      venv = skip (per-host subset installs are legitimate); failed = ❌.
#   2. systemctl is-active over the installed orpheus-* units; units the
#      operator disabled are reported + skipped, not failed. Skipped
#      gracefully where systemd is absent (macOS dev boxes).
#   2b. Every installed unit's ExecStart binary must exist. Check 1 cannot see
#      this: a missing venv reads as "not installed on this host" and is
#      skipped, which is legitimate for a component that is genuinely absent
#      and wrong for one whose unit is installed and enabled. The gap is
#      widest for one-shots — they are idle between runs, so is-active says
#      nothing and a timer that has not fired yet reports amber, not red.
#      This shipped once: orpheus-storage-sweep named a platform venv no
#      installer built.
#   3. Event-bus broker probe (scripts/verify-broker.sh): the configured
#      backend's broker must answer, or the freshly-restarted agents are
#      crash-looping on connect(). Skipped when no deployed config exists.
#   4. 'make check-models' — cheap directory listing, informational only.
# Reports EVERY component before exiting; exits non-zero if anything failed.
DEPLOY_PREFIX ?= /opt/orpheus

# show-deployed - what is CURRENTLY deployed at DEPLOY_PREFIX? The #1
# upgrade-safety question: you cannot roll back to a point you cannot name.
# Run it BEFORE an upgrade and paste the output into your rollback note.
show-deployed:
	@echo "Deployed at $(DEPLOY_PREFIX):"
	@if [ -d "$(DEPLOY_PREFIX)/.git" ]; then \
		printf '  commit:        '; git -C "$(DEPLOY_PREFIX)" describe --tags --always --dirty 2>/dev/null || echo "(git describe failed)"; \
		printf '  branch:        '; git -C "$(DEPLOY_PREFIX)" rev-parse --abbrev-ref HEAD 2>/dev/null || true; \
	elif [ -d "$(DEPLOY_PREFIX)" ]; then \
		echo "  commit:        (no git checkout at $(DEPLOY_PREFIX) - rsync deploy, no git metadata)"; \
	else \
		echo "  (nothing deployed at $(DEPLOY_PREFIX) on this host)"; \
	fi
	@py="$(DEPLOY_PREFIX)/platform/orpheus-common/venv/bin/python"; \
	if [ -x "$$py" ]; then \
		ov=$$("$$py" -c "from importlib.metadata import version; print(version('orpheus-common'))" 2>/dev/null || echo "?"); \
		echo "  orpheus-common: $$ov"; \
	fi
	@src="$(DEPLOY_PREFIX)/platform/orpheus-common/src"; \
	if [ -e "$$src" ]; then \
		echo "  last synced:   $$(stat -c '%y' "$$src" 2>/dev/null || stat -f '%Sm' "$$src" 2>/dev/null || echo '?')"; \
	fi

verify-deploy:
	@echo "═══════════════════════════════════════════════════════════════"
	@echo "          Orpheus post-upgrade verification (read-only)"
	@echo "═══════════════════════════════════════════════════════════════"
	@fail=0; \
	echo ""; \
	if [ -d "$(DEPLOY_PREFIX)" ]; then \
		echo "Deployed venv import smoke ($(DEPLOY_PREFIX) — the venvs systemd runs):"; \
		expected=$$(cat platform/orpheus-common/VERSION 2>/dev/null || true); \
		for dir in $(PYTHON_PROJECTS); do \
			name=$$(basename $$dir); \
			mod=$$(echo "$$name" | tr '-' '_'); \
			case "$$dir" in \
				platform/*) dep="$(DEPLOY_PREFIX)/platform/$$name";; \
				services/orpheus_ui) dep="$(DEPLOY_PREFIX)/ui";; \
				services/*) dep="$(DEPLOY_PREFIX)/services/$$name";; \
				*) dep="$(DEPLOY_PREFIX)/agents/$$name";; \
			esac; \
			py="$$dep/venv/bin/python"; \
			if [ ! -x "$$py" ]; then \
				echo "  ⚠️  $$dep — no deployed venv (not installed on this host), skipped"; \
				continue; \
			fi; \
			if err=$$("$$py" -c "import $$mod" 2>&1 >/dev/null); then \
				echo "  ✅ $$dep ($$mod)"; \
			else \
				echo "  ❌ $$dep ($$mod): $$(echo "$$err" | tail -n 1 | sed 's/^[[:space:]]*//')"; \
				fail=1; \
			fi; \
			ov=$$("$$py" -c "from importlib.metadata import version; print(version('orpheus-common'))" 2>/dev/null || true); \
			if [ -n "$$ov" ] && [ -n "$$expected" ] && [ "$$ov" != "$$expected" ]; then \
				echo "  ❌ $$dep: stale orpheus-common $$ov (repo VERSION is $$expected) — the deploy-time venv reinstall likely failed"; \
				fail=1; \
			fi; \
		done; \
	else \
		echo "Venv import smoke (no $(DEPLOY_PREFIX) on this host — working-tree venvs):"; \
		for dir in $(PYTHON_PROJECTS); do \
			mod=$$(basename $$dir | tr '-' '_'); \
			py="$$dir/venv/bin/python"; \
			[ -x "$$py" ] || py="$$dir/backend/venv/bin/python"; \
			if [ ! -x "$$py" ]; then \
				echo "  ⚠️  $$dir — no venv (not installed on this host), skipped"; \
				continue; \
			fi; \
			if err=$$("$$py" -c "import $$mod" 2>&1 >/dev/null); then \
				echo "  ✅ $$dir ($$mod)"; \
			else \
				echo "  ❌ $$dir ($$mod): $$(echo "$$err" | tail -n 1 | sed 's/^[[:space:]]*//')"; \
				fail=1; \
			fi; \
		done; \
	fi; \
	echo ""; \
	echo "systemd services (systemctl is-active; disabled units skipped):"; \
	if command -v systemctl >/dev/null 2>&1; then \
		units=$$(systemctl list-unit-files 'orpheus-*.service' --no-legend 2>/dev/null | awk '{print $$1}'); \
		[ -n "$$units" ] || echo "  ⚠️  no orpheus-* units installed on this host"; \
		for u in $$units; do \
			if [ "$$(systemctl is-enabled "$$u" 2>/dev/null || true)" = "disabled" ]; then \
				echo "  ⚠️  $$u disabled — skipped (installed but intentionally off)"; \
				continue; \
			fi; \
			if [ "$$(systemctl show -p Type --value "$$u" 2>/dev/null || true)" = "oneshot" ]; then \
				echo "  ⏱  $$u one-shot — verified under timers below, not by is-active"; \
				continue; \
			fi; \
			state=$$(systemctl is-active "$$u" 2>/dev/null || true); \
			if [ "$$state" = "active" ]; then \
				echo "  ✅ $$u active"; \
			else \
				echo "  ❌ $$u $$state"; \
				fail=1; \
			fi; \
		done; \
	else \
		echo "  ⚠️  systemctl not found (not a systemd host) — service checks skipped"; \
	fi; \
	echo ""; \
	echo "Unit ExecStart binaries (the interpreter each unit actually runs):"; \
	if command -v systemctl >/dev/null 2>&1; then \
		execunits=$$(systemctl list-unit-files 'orpheus-*.service' --no-legend 2>/dev/null | awk '{print $$1}'); \
		[ -n "$$execunits" ] || echo "  ⚠️  no orpheus-* units installed on this host"; \
		for u in $$execunits; do \
			bin=$$(systemctl show -p ExecStart --value "$$u" 2>/dev/null | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -n 1); \
			if [ -z "$$bin" ]; then \
				echo "  ⚠️  $$u — could not read ExecStart"; \
			elif [ -x "$$bin" ]; then \
				echo "  ✅ $$u → $$bin"; \
			else \
				echo "  ❌ $$u → $$bin does not exist — this unit cannot start"; \
				fail=1; \
			fi; \
		done; \
	else \
		echo "  ⚠️  systemctl not found (not a systemd host) — ExecStart checks skipped"; \
	fi; \
	echo ""; \
	echo "systemd timers (the timer must be active; its one-shot is idle between runs):"; \
	if command -v systemctl >/dev/null 2>&1; then \
		timers=$$(systemctl list-unit-files 'orpheus-*.timer' --no-legend 2>/dev/null | awk '{print $$1}'); \
		[ -n "$$timers" ] || echo "  ⚠️  no orpheus-* timers installed on this host"; \
		for t in $$timers; do \
			if [ "$$(systemctl is-enabled "$$t" 2>/dev/null || true)" = "disabled" ]; then \
				echo "  ⚠️  $$t disabled — skipped (installed but intentionally off)"; \
				continue; \
			fi; \
			state=$$(systemctl is-active "$$t" 2>/dev/null || true); \
			if [ "$$state" != "active" ]; then \
				echo "  ❌ $$t $$state"; \
				fail=1; \
				continue; \
			fi; \
			unit=$$(systemctl show -p Unit --value "$$t" 2>/dev/null || true); \
			result=$$(systemctl show -p Result --value "$$unit" 2>/dev/null || true); \
			next=$$(systemctl list-timers "$$t" --no-legend 2>/dev/null | awk '{print $$1, $$2, $$3}'); \
			if [ "$$result" = "success" ]; then \
				echo "  ✅ $$t active (last $$unit run succeeded; next $$next)"; \
			elif [ -z "$$result" ]; then \
				echo "  ⚠️  $$t active but $$unit has not run yet (next $$next)"; \
			else \
				echo "  ❌ $$t active but $$unit last result=$$result — journalctl -u $$unit"; \
				fail=1; \
			fi; \
		done; \
	else \
		echo "  ⚠️  systemctl not found (not a systemd host) — timer checks skipped"; \
	fi; \
	echo ""; \
	echo "Event-bus broker probe (the transport the restarted agents connect to):"; \
	if out=$$(scripts/verify-broker.sh "$(DEPLOY_PREFIX)/config/orpheus.yaml" 2>&1); then \
		echo "$$out" | sed 's/^/  /'; \
	else \
		echo "$$out" | sed 's/^/  /'; \
		fail=1; \
	fi; \
	echo ""; \
	echo "Models (informational — make check-models):"; \
	$(MAKE) --no-print-directory check-models || true; \
	echo ""; \
	echo "Data-read smoke (proves the migrated DB still READS, not just imports):"; \
	db="$(ORPHEUS_DATA_ROOT)/detections/orpheus.db"; \
	if [ ! -f "$$db" ]; then \
		echo "  (no DB at $$db - fresh host? skipped)"; \
	elif ! command -v sqlite3 >/dev/null 2>&1; then \
		echo "  (sqlite3 not found - data-read smoke skipped)"; \
	else \
		dc=$$(sqlite3 "$$db" "SELECT count(*) FROM detections" 2>&1); \
		if echo "$$dc" | grep -qE '^[0-9]+$$'; then \
			ec=$$(sqlite3 "$$db" "SELECT count(*) FROM entities" 2>/dev/null || echo "n/a"); \
			echo "  OK  detections=$$dc  entities=$$ec - old data reads after migration"; \
		else \
			echo "  FAIL detections read failed: $$dc"; \
			fail=1; \
		fi; \
	fi; \
	echo ""; \
	echo "Host disk and log bounds (the system disk, not the data volume):"; \
	rootfree=$$(df -Pk / 2>/dev/null | awk 'NR==2 {printf "%.1f", $$4/1048576}'); \
	rootpct=$$(df -Pk / 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$$5); print 100-$$5}'); \
	echo "  root filesystem: $${rootfree:-?} GB free ($${rootpct:-?}% of capacity)"; \
	if [ -n "$$rootpct" ] && [ "$$rootpct" -lt 10 ] 2>/dev/null; then \
		echo "  ⚠️  under 10% free on / — a log flood has very little room to work with"; \
	fi; \
	if command -v systemctl >/dev/null 2>&1; then \
		unbounded=""; \
		for u in $$(systemctl list-unit-files --no-legend 'orpheus-*.service' 2>/dev/null | awk '{print $$1}'); do \
			burst=$$(systemctl show -p LogRateLimitBurst --value "$$u" 2>/dev/null); \
			case "$$burst" in ""|0) unbounded="$$unbounded $$u";; esac; \
		done; \
		if [ -n "$$unbounded" ]; then \
			echo "  ⚠️  units with no log rate limit in effect:$$unbounded"; \
			echo "      (re-run the component's install-service to pick up the shipped unit)"; \
		else \
			echo "  OK  every installed orpheus unit carries a log rate limit"; \
		fi; \
		storage=$$(systemd-analyze cat-config systemd/journald.conf 2>/dev/null | grep -iE '^\s*Storage=' | tail -1 | cut -d= -f2); \
		if [ ! -d /var/log/journal ] && [ "$$storage" != "persistent" ]; then \
			echo "  ⚠️  the journal is in RAM (no /var/log/journal): it is lost on every reboot,"; \
			echo "      so a crash takes its own evidence with it, and any SystemMaxUse is inert"; \
		fi; \
		if [ -f /etc/systemd/journald.conf.d/10-orpheus.conf ]; then \
			echo "  OK  host log bounds installed (journald persistent + capped, no syslog mirror)"; \
		else \
			echo "  ⚠️  host log bounds NOT installed — /var/log/syslog is bounded by rotation"; \
			echo "      schedule, not size, so a flooding service can fill the system disk."; \
			echo "      Opt in with:  make install-log-bounds     (undo: rm the drop-in, restart journald)"; \
		fi; \
	else \
		echo "  (not a systemd host — unit and journal checks skipped)"; \
	fi; \
	echo ""; \
	if [ "$$fail" = "0" ]; then \
		echo "✅ verify-deploy: all checks passed"; \
	else \
		echo "❌ verify-deploy: FAILURES above — the upgrade left an unhealthy component"; \
		exit 1; \
	fi

# Backfill root_event_id on legacy detection rows (cross-classifier identity,
# ADR 0011 / detectallanimals). Named specifically so future one-off
# migrations get their own target rather than colliding on a generic name.
# Runs the maintenance script with a deployed agent venv's Python (which has
# orpheus_common + its deps), so you don't have to remember the interpreter
# path or the ORPHEUS_DATA_ROOT env var. Overridable:
#   make backfill-root-event-ids                              # live run, /data/orpheus
#   make backfill-root-event-ids-dry-run                      # preview, no writes
#   make backfill-root-event-ids ORPHEUS_DATA_ROOT=~/data/orpheus   # laptop/dev
#   make backfill-root-event-ids BACKFILL_VENV=/path/to/python      # different venv
BACKFILL_VENV      ?= /opt/orpheus/agents/orpheus-agent-event-correlator/venv/bin/python
ORPHEUS_DATA_ROOT  ?= /data/orpheus

backfill-root-event-ids:
	@PY="$(BACKFILL_VENV)"; \
	if [ ! -x "$$PY" ]; then \
		echo "❌ Interpreter not found: $$PY"; \
		echo "   Set BACKFILL_VENV to a deployed agent venv's python (one that has orpheus_common installed)."; \
		exit 1; \
	fi; \
	case "$(BACKFILL_ARGS)" in *--dry-run*) MODE="DRY-RUN (no writes)";; *) MODE="LIVE";; esac; \
	echo "Backfilling root_event_id (ORPHEUS_DATA_ROOT=$(ORPHEUS_DATA_ROOT)) [$$MODE]..."; \
	ORPHEUS_DATA_ROOT="$(ORPHEUS_DATA_ROOT)" "$$PY" tools/maintenance/backfill_root_event_ids.py $(BACKFILL_ARGS)

backfill-root-event-ids-dry-run:
	@$(MAKE) backfill-root-event-ids BACKFILL_ARGS=--dry-run

# Backfill entity_type on legacy entities rows ([ARCH] entity taxonomy).
backfill-entity-types:
	@PY="$(BACKFILL_VENV)"; \
	if [ ! -x "$$PY" ]; then \
		echo "❌ Interpreter not found: $$PY"; \
		echo "   Set BACKFILL_VENV to a deployed agent venv's python (one that has orpheus_common installed)."; \
		exit 1; \
	fi; \
	case "$(BACKFILL_ARGS)" in *--dry-run*) MODE="DRY-RUN (no writes)";; *) MODE="LIVE";; esac; \
	echo "Backfilling entity_type (ORPHEUS_DATA_ROOT=$(ORPHEUS_DATA_ROOT)) [$$MODE]..."; \
	ORPHEUS_DATA_ROOT="$(ORPHEUS_DATA_ROOT)" "$$PY" tools/maintenance/backfill_entity_types.py $(BACKFILL_ARGS)

backfill-entity-types-dry-run:
	@$(MAKE) backfill-entity-types BACKFILL_ARGS=--dry-run

# End-to-end BDD scenarios (tests/bdd/) — drives the correlation loop in-process
# via the event-correlator venv (which has behave + orpheus-common). See
# docs/TESTING.md.
BDD_BEHAVE ?= agents/orpheus-agent-event-correlator/venv/bin/behave
BDD_PYTEST ?= agents/orpheus-agent-event-correlator/venv/bin/pytest
test-bdd:
	@if [ ! -x "$(BDD_BEHAVE)" ]; then \
		echo "❌ behave not found at $(BDD_BEHAVE) — run 'make install-event-correlator' (adds the dev extras)."; \
		exit 1; \
	fi
	@echo "Running end-to-end BDD scenarios (tests/bdd)..."
	@$(BDD_BEHAVE) tests/bdd

# sim-matrix-ci — the GENERATED failure matrix (full powerset) through the real
# correlator in-process (no models, no docker). docs/designs/sim-test-matrix.md.
# The on-demand docker/real-model full matrix (sim-matrix) is a later slice.
sim-matrix-ci:
	@if [ ! -x "$(BDD_PYTEST)" ]; then \
		echo "❌ pytest not found at $(BDD_PYTEST) — run 'make install-event-correlator'."; \
		exit 1; \
	fi
	@echo "Running the generated in-process test matrix (tests/bdd/test_matrix_generated.py)..."
	@$(BDD_PYTEST) tests/bdd/test_matrix_generated.py -q

# test-bash — bats-core suites for the repo's shell scripts (tests/bats/*.bats).
# DELIBERATE DEVIATION from the backlog item's git-submodule suggestion:
# submodules add clone friction for every contributor and CI job forever
# (--recurse-submodules or a second fetch step, and they rot silently) for what
# are three read-only test-time deps. Instead, bootstrap pinned release tags
# via shallow clones into the GITIGNORED tests/bats/lib/ on first run.
# Idempotent — present => skipped. Rollback/reset: rm -rf tests/bats/lib.
# (Clone lands in <dest>.tmp then moves, so an interrupted bootstrap can't
# leave a half-clone that later runs mistake for done.)
BATS_LIB_DIR     := tests/bats/lib
BATS_CORE_TAG    ?= v1.12.0
BATS_SUPPORT_TAG ?= v0.3.0
BATS_ASSERT_TAG  ?= v2.2.4
BATS_BIN         := $(BATS_LIB_DIR)/bats-core/bin/bats

test-bash:
	@for spec in bats-core=$(BATS_CORE_TAG) bats-support=$(BATS_SUPPORT_TAG) bats-assert=$(BATS_ASSERT_TAG); do \
		name=$${spec%%=*}; tag=$${spec#*=}; dest="$(BATS_LIB_DIR)/$$name"; \
		if [ ! -d "$$dest" ]; then \
			echo "Bootstrapping $$name @ $$tag into $$dest..."; \
			rm -rf "$$dest.tmp"; \
			git -c advice.detachedHead=false clone --quiet --depth 1 --branch "$$tag" "https://github.com/bats-core/$$name.git" "$$dest.tmp" || exit 1; \
			mv "$$dest.tmp" "$$dest"; \
		fi; \
	done
	@echo "Running bash script tests (tests/bats/*.bats)..."
	@"$(BATS_BIN)" tests/bats/*.bats

# reconcile — event-sourcing shadow reconciliation (determinism contract §3.3):
# compare the durable domain stream vs the SQLite DB by event_id. ARGS passes flags
# (e.g. ARGS="--detection-type audio.motion"). Needs the orpheus-common venv.
reconcile:
	@platform/orpheus-common/venv/bin/python -m orpheus_common.reconcile $(ARGS)

# manifests — generate deployment manifests from orpheus.yaml so the topology stays in
# sync with the config. TARGET=systemd|docker-compose; ARGS for --config/--output.
manifests:
	@platform/orpheus-common/venv/bin/python -m orpheus_common.manifest_gen --target $(TARGET) $(ARGS)

# The sweep binary these targets run. On a deployed host that is the console
# script orpheus-storage-sweep.service names, so `make storage-report` answers
# for the code that will actually do the deleting rather than for the working
# tree, which may be several commits ahead of what is installed. Falls back to
# the working-tree venv on a dev box with no $(DEPLOY_PREFIX).
#
# The console script rather than `python -m orpheus_common.storage.sweep`: the
# package __init__ imports the module, so -m imports it twice and runpy warns.
SWEEP_BIN = $(shell \
	if [ -x "$(DEPLOY_PREFIX)/platform/orpheus-common/venv/bin/orpheus-storage-sweep" ]; then \
		echo "$(DEPLOY_PREFIX)/platform/orpheus-common/venv/bin/orpheus-storage-sweep"; \
	else \
		echo "platform/orpheus-common/venv/bin/orpheus-storage-sweep"; \
	fi)

# storage-report — what the retention sweep would delete, without deleting it.
#
# The whole safety story of a component that removes recordings rests on
# being able to ask it first, so this is a dry run: it decides exactly what a
# real sweep would and touches nothing. Run it before enabling the timer on a
# station that already holds a lot of data, and any time the ceilings change.
# ARGS passes flags (e.g. ARGS=--json).
storage-report:
	@$(SWEEP_BIN) --dry-run $(ARGS)

# storage-sweep — run one real sweep now, outside the timer's schedule. Takes
# the same lock the timer's run does, so a hand-run during a scheduled sweep
# backs off instead of the two planning against each other.
storage-sweep:
	@$(SWEEP_BIN) $(ARGS)

logs-all:
	@echo "Streaming logs from all Orpheus services (Ctrl+C to exit)..."
	@journalctl -u "orpheus-*" -f

# Alias: the contributing docs tell newcomers to run `make test`.
test: test-all

test-all:
	@echo "══════════════════════════════════════════════════════════════"
	@echo "  Running All Tests (continues on error to show all failures)"
	@echo "══════════════════════════════════════════════════════════════"
	@failed=""; \
	for dir in platform/orpheus-common services/orpheus_ui services/orpheus-gps agents/orpheus-agent-*; do \
		if [ -f "$$dir/Makefile" ]; then \
			echo ""; \
			echo "Testing $$dir..."; \
			(cd "$$dir" && $(MAKE) test) || failed="$$failed $$dir"; \
		fi; \
	done; \
	echo ""; \
	echo "══════════════════════════════════════════════════════════════"; \
	if [ -n "$$failed" ]; then \
		echo "❌ Suites FAILED:$$failed"; \
		echo "══════════════════════════════════════════════════════════════"; \
		exit 1; \
	fi; \
	echo "✅ All suites passed"; \
	echo "══════════════════════════════════════════════════════════════"

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
