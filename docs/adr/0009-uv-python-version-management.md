# ADR 0009: uv for Python Version Management

**Status:** Accepted

**Date:** 2026-04-04

**Deciders:** Scott, Development Team

## Context

Orpheus locks Python to 3.9.5 to match the system Python on Jetson JetPack. macOS developers previously relied on `pyenv` to install and pin this version. This worked, but had pain points:

- pyenv compiles Python from source on every install (slow, fragile on Apple Silicon, requires Xcode CLI tools + brew dependencies like openssl and readline)
- New contributors frequently hit build failures during `pyenv install 3.9.5`, especially on ARM Macs
- pyenv's shim system occasionally caused confusion when `python3` resolved to the wrong version
- The project already uses `uv` (via `uvx`) for Makefile formatting (`make mbake`), so it is already in the dependency graph

Meanwhile, [uv](https://docs.astral.sh/uv/) (by Astral, the ruff authors) gained the ability to install and manage Python interpreters via pre-built standalone distributions ([python-build-standalone](https://github.com/astral-sh/python-build-standalone)). Key capabilities:

- `uv python install 3.9.5` — downloads a pre-built CPython 3.9.5 in ~3 seconds (no compilation)
- `uv venv --python 3.9.5` — creates a venv pinned to the exact micro version
- `uv pip install` — faster dependency resolution and installs than pip
- Reads `.python-version` files natively

### Research

A spike confirmed that uv's python-build-standalone distribution of CPython 3.9.5 works correctly on Apple Silicon macOS with all Orpheus dependencies (numpy, scipy, sounddevice, onnxruntime, torch). See `research-uv-migration.md` at the repo root for the full assessment.

### Constraints

- On Jetson, the system Python from JetPack (3.9.5) must always be used — it carries CUDA/cuDNN bindings that a standalone distribution would not have
- The existing `?=` override pattern in `common_python.mk` must be preserved so that `PYTHON_SYSTEM`, `PYTHON_REQUIRED_VERSION`, and `VENV` remain overridable per-component and at deploy time (e.g. in container images or a k8s cluster)
- CI uses `actions/setup-python` and is unaffected

## Decision

Replace `pyenv` with `uv` as the **recommended** (not required) Python version manager for macOS development, and integrate uv acceleration into the shared Makefile infrastructure.

### Changes

**`make/common_python.mk`** — the core change:

- Add `HAS_UV` detection variable (auto-detected, no platform guard — uv works everywhere)
- Rewrite `check-python-version` as pure validation with no side effects. Check order: `PYTHON_SYSTEM` on PATH → `uv python find` → fail with instructions
- Add `assure-python-version` target: if check fails and uv is available, runs `uv python install`; if no uv, fails with install instructions
- `$(VENV)/bin/activate` now depends on `assure-python-version` instead of `check-python-version`, and uses `uv venv --python` when uv is available
- Add `PIP_INSTALL` helper variable: resolves to `uv pip install` when uv is present, else `$(PIP) install` — opt-in for components

**`.python-version`** — new file at repo root containing `3.9.5`. Read by uv and documents the project's Python version. Tracked in git (removed from `.gitignore`).

**`scripts/dev-stack.sh`** — Python discovery updated to try `python3.9` → `uv python find 3.9.5` → fail with uv install instructions.

**`docs/MACOS_QUICKSTART.md`** — rewritten with uv-first workflow. pyenv preserved as a documented alternative in a collapsed section.

**`CONTRIBUTING.md`** — updated to recommend uv over pyenv.

**`make/README.md`** — documents `HAS_UV`, `PIP_INSTALL`, `assure-python-version`, and override examples.

### What did NOT change

- Agent and service Makefiles — they inherit from `common_python.mk` automatically
- `*/systemd/install-service.sh` scripts — Jetson-only, use system Python
- CI workflows — use `actions/setup-python`
- Root `Makefile` — only delegates to component Makefiles
- Existing ADRs
- The `PYTHON_SYSTEM ?= python3.9` default — unchanged, preserving existing Jetson behavior

### Design principles

1. **System Python preferred** — uv interpreter provisioning is a fallback, not the default
2. **uv acceleration everywhere** — `uv venv` and `uv pip install` are used on any platform where uv is present (they're just faster, no platform risk)
3. **All overrides preserved** — `PYTHON_SYSTEM`, `PYTHON_REQUIRED_VERSION`, `VENV` use `?=` and can be set from env, component Makefile, or deploy config
4. **No hard dependency on uv** — everything still works with just `python3.9` on PATH

## Consequences

### Positive

- New contributor setup reduced from "install pyenv + brew deps + compile Python (~5 min, error-prone)" to "install uv + `uv python install 3.9.5` (~5 sec, pre-built)"
- `assure-python-version` auto-installs the right Python — `make install` just works on a fresh macOS
- Faster venv creation and pip installs on developer machines
- `.python-version` file documents the project's Python version at the repo root
- uv is already in the project's toolchain (used for `uvx mbake`)
- No CUDA/Jetson risk — system Python is always preferred; uv install is a fallback

### Negative

- uv is a newer tool; contributors unfamiliar with it may need to learn a new command
- python-build-standalone distributions are not identical to Homebrew or system Python (e.g., no `_tkinter`), though this is irrelevant for Orpheus's headless agents
- pyenv users who already have a working setup need to learn nothing — pyenv still works, just isn't documented as the primary path

### Neutral

- Contributors can still use pyenv, conda, system Python, or any other method — the Makefiles only care about `PYTHON_SYSTEM` resolving to a valid interpreter
- The `HAS_UV` detection adds trivial overhead (one `command -v` shell call at Make parse time)
- uv's interpreter management and venv/pip acceleration are independent features; either can be used without the other
