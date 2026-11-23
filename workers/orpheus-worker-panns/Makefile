# Deliberately does NOT include common_python.mk/common_deploy.mk: Python 3.8,
# no orpheus-common, no services, and never part of the default install.
PYTHON38 ?= python3.8
GPU_VENV ?= $(ORPHEUS_DATA_ROOT)/venvs/panns-gpu
NVIDIA_TORCH_WHEEL ?=

.PHONY: install test lint
install:
	@test -n "$(ORPHEUS_DATA_ROOT)" || (echo 'Set ORPHEUS_DATA_ROOT'; exit 1)
	@test -f "$(NVIDIA_TORCH_WHEEL)" || (echo 'Set NVIDIA_TORCH_WHEEL to the verified cp38 aarch64 wheel'; exit 1)
	$(PYTHON38) -c 'import platform, sys; assert sys.version_info[:2] == (3,8) and platform.system() == "Linux" and platform.machine() == "aarch64", "Requires Jetson Python 3.8"'
	$(PYTHON38) -c 'import hashlib; from pathlib import Path; p=Path("$(NVIDIA_TORCH_WHEEL)"); assert hashlib.sha256(p.read_bytes()).hexdigest() == "5112e2ef5051f1003ae2ffb545ae596377df66979d62a954d774f18009064dbe", "NVIDIA wheel hash mismatch"'
	$(PYTHON38) -m venv "$(GPU_VENV)"
	"$(GPU_VENV)/bin/python" -m pip install 'pip==25.0.1' 'setuptools==75.3.2' 'wheel==0.45.1'
	# Every artifact must be one of the tested wheels (wheels.sha256).
	$(PYTHON38) requirements_hashed.py "$(NVIDIA_TORCH_WHEEL)" > "$(GPU_VENV)/requirements-hashed.txt"
	"$(GPU_VENV)/bin/python" -m pip install --require-hashes --only-binary=:all: -r "$(GPU_VENV)/requirements-hashed.txt"
	"$(GPU_VENV)/bin/python" -m pip install --no-build-isolation --no-deps ../../platform/orpheus-inference .
	"$(GPU_VENV)/bin/python" -m pip check

test lint:
	$(MAKE) -C ../../platform/orpheus-inference $@
