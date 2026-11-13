# Development uses Python 3.9; the runtime package itself supports 3.8 without deps.
SERVICE_NAME := orpheus-inference
include ../../make/common_python.mk
include ../../make/common_lint.mk

.PHONY: install test coverage
install: $(VENV)/bin/activate
	$(PIP_INSTALL) -e . 'pytest==8.3.5' 'pytest-cov>=5,<7' 'ruff==0.15.20' 'numpy>=1.24,<2'

test: check-deps
	PYTHONPATH=src:../../workers/orpheus-worker-panns/src $(PYTEST) tests ../../workers/orpheus-worker-panns/tests

coverage: check-deps
	PYTHONPATH=src:../../workers/orpheus-worker-panns/src $(PYTEST) tests ../../workers/orpheus-worker-panns/tests --cov=orpheus_inference --cov=orpheus_worker_panns --cov-report=term-missing --cov-fail-under=80

lint: lint-worker
lint-worker:
	$(RUFF) check ../../workers/orpheus-worker-panns/src ../../workers/orpheus-worker-panns/tests --config ../../workers/orpheus-worker-panns/pyproject.toml

format: format-worker
format-worker:
	$(RUFF) format ../../workers/orpheus-worker-panns/src ../../workers/orpheus-worker-panns/tests --config ../../workers/orpheus-worker-panns/pyproject.toml
	$(RUFF) check --fix ../../workers/orpheus-worker-panns/src ../../workers/orpheus-worker-panns/tests --config ../../workers/orpheus-worker-panns/pyproject.toml
