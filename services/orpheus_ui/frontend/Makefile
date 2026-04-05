# Orpheus UI Frontend - React/TypeScript
# This Makefile manages the React frontend for orpheus_ui

.PHONY: help install build dev test test-coverage lint format clean

# Detect and prefer local Node.js installation over system npm
# The install-service.sh script downloads Node.js v20.18.0 to ../.node/
# This ensures consistent Node.js versions between development and production
NODE_LOCAL_DIR := ../.node
NODE_LOCAL := $(wildcard $(NODE_LOCAL_DIR)/bin/node)
ifdef NODE_LOCAL
NPM := $(NODE_LOCAL_DIR)/bin/npm
$(info Using local Node.js: $(shell $(NODE_LOCAL_DIR)/bin/node --version))
else
NPM := npm
$(info Using system npm - consider running 'make install-service' to install local Node.js)
endif

help:
	@echo "Orpheus UI Frontend Makefile"
	@echo ""
	@echo "Development:"
	@echo "  make install       - Install npm dependencies"
	@echo "  make dev           - Run Vite dev server (port 5173)"
	@echo "  make build         - Build for production"
	@echo "  make test          - Run Vitest unit tests"
	@echo "  make test-coverage - Run tests with coverage"
	@echo "  make lint          - Run ESLint"
	@echo "  make format        - Run ESLint with --fix"
	@echo "  make clean         - Remove node_modules and dist"

install:
	@echo "Installing frontend dependencies..."
	$(NPM) install
	@echo "✓ Frontend dependencies installed"

build:
	@echo "Building React frontend..."
	$(NPM) run build
	@echo "✓ Frontend built to dist/"

dev:
	@echo "Starting Vite dev server on http://localhost:5173"
	@echo "Note: API requests are proxied to backend on port 8082"
	$(NPM) run dev

test:
	@echo "Running frontend unit tests..."
	$(NPM) run test
	@echo "Running TypeScript type checking..."
	$(NPM) run type-check

test-coverage:
	@echo "Running frontend tests with coverage..."
	$(NPM) run test:coverage

lint:
	@echo "Linting frontend code..."
	$(NPM) run lint
	@echo "✓ Linting complete"

format:
	@echo "Formatting frontend code..."
	$(NPM) run lint -- --fix
	@echo "✓ Formatting complete"

clean:
	rm -rf node_modules dist coverage
	@echo "✓ Cleaned frontend artifacts"
