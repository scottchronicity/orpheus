# Orpheus UI Service - Root Makefile
# Modern React/FastAPI UI following monorepo patterns
#
# Structure:
#   backend/   - Python FastAPI application
#   frontend/  - React TypeScript application
#   e2e/       - Playwright end-to-end tests
#   systemd/   - Service installation files
#
# This Makefile delegates to backend/ and frontend/ Makefiles

# -- Component identity ------------------------------------------------------
SERVICE_NAME       := orpheus-ui
DEPLOY_ROOT        := /opt/orpheus/ui
DEPLOY_SRC_DIR     := backend/src/
DEPLOY_EXTRA_FILES := backend/pyproject.toml backend/requirements.txt backend/setup.py

# -- Shared infrastructure ---------------------------------------------------
# NOTE: common_python.mk and common_lint.mk intentionally NOT included —
#       this Makefile delegates to backend/ and frontend/ sub-Makefiles.
include ../../make/common_service.mk
include ../../make/common_deploy.mk

# -- Phony declarations (component-specific only) ----------------------------
.PHONY: help install install-backend install-frontend install-e2e \
	run run-backend run-frontend \
	test test-all test-backend test-frontend test-e2e \
	coverage lint format check clean clean-node \
	build build-frontend \
	update

help:
	@echo "Orpheus UI Service"
	@echo ""
	@echo "Directory Structure:"
	@echo "  backend/   - Python FastAPI (port 8082)"
	@echo "  frontend/  - React TypeScript (port 5173 dev)"
	@echo "  e2e/       - Playwright integration tests"
	@echo "  systemd/   - Service files"
	@echo ""
	@echo "Local development (no sudo):"
	@echo "  make install          Install all dependencies"
	@echo "  make install-backend  Install Python backend only"
	@echo "  make install-frontend Install Node frontend only"
	@echo "  make install-e2e      Install Playwright for e2e tests"
	@echo "  make run              Run backend (port 8082)"
	@echo "  make run-frontend     Run frontend dev server (port 5173)"
	@echo "  make test             Run unit tests (backend + frontend)"
	@echo "  make test-all         Run all tests (unit + e2e)"
	@echo "  make test-backend     Run Python unit tests"
	@echo "  make test-frontend    Run TypeScript unit tests"
	@echo "  make test-e2e         Run Playwright e2e tests"
	@echo "  make coverage         Run backend tests with coverage"
	@echo "  make lint             Lint all code"
	@echo "  make format           Format all code"
	@echo "  make build            Build frontend for production"
	@echo "  make clean            Remove all build artifacts"
	@echo "  make clean-node       Remove local Node.js installation"
	@echo ""
	@echo "Edge deployment (sudo required):"
	@echo "  make install-service  Install systemd service"
	@echo "  make start            Start systemd service"
	@echo "  make stop             Stop systemd service"
	@echo "  make restart          Restart systemd service"
	@echo "  make status           Show service status"
	@echo "  make logs             Tail service logs (follow)"
	@echo "  make update           git pull + reinstall + build + restart"

#==============================================================================
# Install Targets
#==============================================================================
install: install-backend install-frontend install-e2e
	@echo "✓ All dependencies installed"

install-backend:
	@echo "Installing backend dependencies..."
	@$(MAKE) -C backend install
	@echo "✓ Backend installed"

install-frontend:
	@echo "Installing frontend dependencies..."
	@$(MAKE) -C frontend install
	@echo "✓ Frontend installed"

install-e2e:
	@echo "Installing Playwright for e2e tests..."
	@cd e2e && npm install && npx playwright install chromium
	@echo "✓ Playwright installed"

#==============================================================================
# Run Targets
#==============================================================================
run: run-backend

run-backend:
	@$(MAKE) -C backend run

run-frontend:
	@$(MAKE) -C frontend dev

#==============================================================================
# Test Targets
#==============================================================================
test: test-backend test-frontend
	@echo "✓ All unit tests complete"

test-all: test-backend test-frontend test-e2e
	@echo "✓ All tests complete (unit + e2e)"

test-backend:
	@echo "Running backend tests..."
	@$(MAKE) -C backend test

test-frontend:
	@echo "Running frontend tests..."
	@$(MAKE) -C frontend test

test-e2e:
	@echo "Running Playwright e2e tests..."
	@cd e2e && npx playwright test

coverage:
	@echo "Running backend tests with coverage..."
	@$(MAKE) -C backend coverage

#==============================================================================
# Lint and Format Targets
#==============================================================================
lint:
	@echo "Linting all code..."
	@$(MAKE) -C backend lint
	@$(MAKE) -C frontend lint
	@echo "✓ All linting complete"

format:
	@echo "Formatting all code..."
	@$(MAKE) -C backend format
	@$(MAKE) -C frontend format
	@echo "✓ All formatting complete"

check:
	@echo "Checking code formatting..."
	@$(MAKE) -C backend check
	@echo "✓ All code properly formatted"

#==============================================================================
# Build Targets
#==============================================================================
build: build-frontend
	@echo "✓ Build complete"

build-frontend:
	@echo "Building frontend for production..."
	@$(MAKE) -C frontend build
	@echo "✓ Frontend built to frontend/dist/"

#==============================================================================
# Clean Targets
#==============================================================================
clean:
	@echo "Cleaning all artifacts..."
	@$(MAKE) -C backend clean
	@$(MAKE) -C frontend clean
	@rm -rf e2e/node_modules e2e/playwright-report e2e/test-results
	@echo "✓ All cleaned"

clean-node:
	@echo "Removing local Node.js installation..."
	@rm -rf .node
	@echo "✓ Local Node.js removed"
	@echo "Run 'make install-service' to reinstall Node.js"

#==============================================================================
# Update
#==============================================================================
update:
	@echo "Updating $(SERVICE_NAME)..."
	git pull
	$(MAKE) install
	$(MAKE) build
	$(MAKE) deploy
	$(MAKE) restart
	@echo "✓ $(SERVICE_NAME) updated and restarted"
