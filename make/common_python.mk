# Common Python venv and version-check logic for Orpheus components.
#
# Include this from a component Makefile after setting:
#
#   SERVICE_NAME             (required)
#   PYTHON_REQUIRED_VERSION  (optional, default: 3.9.5)
#   PYTHON_SYSTEM            (optional, default: python3.9)
#   VENV                     (optional, default: venv)
#   SRC_DIR                  (optional, default: src)
#   TEST_DIR                 (optional, default: tests)
#
# Provides variables: PYTHON, PYTHON_DIR, PIP, PIP_INSTALL, PYTEST, RUFF, HAS_UV
# Provides targets:   check-python-version, assure-python-version,
#                     check-deps, $(VENV)/bin/activate
#
# uv integration:
#   When uv is available, it is used to accelerate venv creation and pip
#   installs on any platform. If the required Python version is not found on
#   PATH, uv can provision it automatically (assure-python-version).
#   All variables use ?= so they can be overridden per-component, per-env,
#   or at deploy time (e.g. in a container image).

# -- Defaults -----------------------------------------------------------------

PYTHON_SYSTEM           ?= python3.9
PYTHON_REQUIRED_VERSION ?= 3.9.5
VENV                    ?= venv
SRC_DIR                 ?= src
TEST_DIR                ?= tests

# -- uv detection -------------------------------------------------------------
# Detect whether uv is available. Used to accelerate venv creation and pip
# installs on any platform, and to provision the Python interpreter as a
# fallback when PYTHON_SYSTEM is not on PATH.

HAS_UV := $(shell command -v uv >/dev/null 2>&1 && echo yes)

# -- Derived ------------------------------------------------------------------

PYTHON     ?= $(VENV)/bin/python
PYTHON_DIR := $(dir $(PYTHON))
PIP        ?= $(PYTHON_DIR)pip
PYTEST     ?= $(PYTHON_DIR)pytest
RUFF       ?= $(PYTHON_DIR)ruff

# PIP_INSTALL: drop-in replacement for "$(PIP) install" that uses uv when
# available for faster installs.  Components can opt in:
#   $(PIP_INSTALL) -r requirements.txt
ifdef HAS_UV
PIP_INSTALL ?= uv pip install --python $(PYTHON)
else
PIP_INSTALL ?= $(PIP) install
endif

# -- Targets ------------------------------------------------------------------

.PHONY: check-python-version assure-python-version check-deps

# check-python-version: Pure validation — no side effects.
# Check order: PYTHON_SYSTEM on PATH → uv-managed Python → fail.
# Validates that the found interpreter meets PYTHON_REQUIRED_VERSION.
check-python-version:
	@echo "Checking Python version..."
	@FOUND_PYTHON=""; \
	if command -v $(PYTHON_SYSTEM) >/dev/null 2>&1; then \
		FOUND_PYTHON="$(PYTHON_SYSTEM)"; \
	elif [ "$(HAS_UV)" = "yes" ]; then \
		UV_PYTHON=$$(uv python find $(PYTHON_REQUIRED_VERSION) 2>/dev/null || true); \
		if [ -n "$$UV_PYTHON" ]; then \
			FOUND_PYTHON="$$UV_PYTHON"; \
		fi; \
	fi; \
	if [ -z "$$FOUND_PYTHON" ]; then \
		echo "❌ Python interpreter '$(PYTHON_SYSTEM)' not found."; \
		if [ "$(HAS_UV)" = "yes" ]; then \
			echo "   Run: uv python install $(PYTHON_REQUIRED_VERSION)"; \
		else \
			echo "   Install uv (https://docs.astral.sh/uv/), then run:"; \
			echo "     uv python install $(PYTHON_REQUIRED_VERSION)"; \
			echo "   Or set PYTHON_SYSTEM=path/to/python3.9"; \
		fi; \
		exit 1; \
	fi; \
	PYTHON_VER=$$($$FOUND_PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"); \
	MAJOR=$$(echo $$PYTHON_VER | cut -d. -f1); \
	MINOR=$$(echo $$PYTHON_VER | cut -d. -f2); \
	MICRO=$$(echo $$PYTHON_VER | cut -d. -f3); \
	if [ "$$MAJOR" != "3" ] || [ "$$MINOR" -lt "9" ]; then \
		echo "❌ Python $(PYTHON_REQUIRED_VERSION)+ required, found $$PYTHON_VER"; \
		echo "   Set PYTHON_SYSTEM=path/to/python3.9"; \
		exit 1; \
	fi; \
	if [ "$$MINOR" = "9" ] && [ "$$MICRO" -lt 5 ]; then \
		echo "❌ Python $(PYTHON_REQUIRED_VERSION)+ required, found $$PYTHON_VER (micro version too low)"; \
		exit 1; \
	fi; \
	echo "✓ Python version $$PYTHON_VER OK (requires $(PYTHON_REQUIRED_VERSION)+)"

# assure-python-version: Ensures a suitable interpreter exists.
# If check-python-version would fail and uv is available, installs the
# required version via uv python install.  If uv is not available, fails
# with instructions.
assure-python-version:
	@FOUND_PYTHON=""; \
	if command -v $(PYTHON_SYSTEM) >/dev/null 2>&1; then \
		FOUND_PYTHON="$(PYTHON_SYSTEM)"; \
	elif [ "$(HAS_UV)" = "yes" ]; then \
		UV_PYTHON=$$(uv python find $(PYTHON_REQUIRED_VERSION) 2>/dev/null || true); \
		if [ -n "$$UV_PYTHON" ]; then \
			FOUND_PYTHON="$$UV_PYTHON"; \
		fi; \
	fi; \
	if [ -z "$$FOUND_PYTHON" ]; then \
		if [ "$(HAS_UV)" = "yes" ]; then \
			echo "Python $(PYTHON_REQUIRED_VERSION) not found — installing via uv..."; \
			uv python install $(PYTHON_REQUIRED_VERSION); \
			echo "✓ Python $(PYTHON_REQUIRED_VERSION) installed via uv"; \
		else \
			echo "❌ Python $(PYTHON_REQUIRED_VERSION) not found and uv is not installed."; \
			echo "   Install uv (https://docs.astral.sh/uv/), then run:"; \
			echo "     uv python install $(PYTHON_REQUIRED_VERSION)"; \
			echo "   Or install Python $(PYTHON_REQUIRED_VERSION) manually and set PYTHON_SYSTEM."; \
			exit 1; \
		fi; \
	fi
	@$(MAKE) check-python-version

# $(VENV)/bin/activate: Create a virtual environment.
# Uses uv for faster venv creation when available, else falls back to
# the standard library venv module.
$(VENV)/bin/activate: assure-python-version
ifdef HAS_UV
	@echo "Creating virtual environment at $(VENV) via uv..."
	@uv venv --seed --python $(PYTHON_SYSTEM) $(VENV)
else
	@echo "Creating virtual environment at $(VENV) with $(PYTHON_SYSTEM)..."
	@$(PYTHON_SYSTEM) -m venv $(VENV)
endif
	@echo "✓ Virtual environment created"

check-deps:
	@if [ ! -f "$(PYTHON)" ]; then \
		if [ "$(VENV)" = "venv" ]; then \
			echo "Virtual environment not found, creating..."; \
			$(MAKE) $(VENV)/bin/activate; \
		else \
			echo "❌ Python not found at $(PYTHON)"; \
			echo "   Run 'make install' or set VENV to an existing venv"; \
			exit 1; \
		fi \
	fi

# -- Dry-run helpers ----------------------------------------------------------
# Used by dry-run targets in component Makefiles.  When uv is available, the
# temporary venv and package installs are accelerated.  Components reference
# these in their dry-run recipes instead of hard-coding $(PYTHON_SYSTEM) -m venv.

DRYRUN_VENV_PATH ?= .venv-dry-run
DRYRUN_PYTHON     = $(DRYRUN_VENV_PATH)/bin/python

ifdef HAS_UV
CREATE_DRYRUN_VENV  = uv venv --python $(PYTHON_REQUIRED_VERSION) $(DRYRUN_VENV_PATH)
DRYRUN_PIP_INSTALL  = uv pip install --python $(DRYRUN_PYTHON)
else
CREATE_DRYRUN_VENV  = $(PYTHON_SYSTEM) -m venv $(DRYRUN_VENV_PATH)
DRYRUN_PIP_INSTALL  = $(DRYRUN_VENV_PATH)/bin/pip install
endif
