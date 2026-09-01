# ADR 0008: Shared Makefile Includes for Deploy, Python, Lint, and Service Management

**Status:** Accepted

Component inventory below is as of the decision. `orpheus-dashboard` has since
been retired in favour of `orpheus_ui`, and a ninth agent (event-correlator) was
added.

**Date:** 2026-03-22

**Deciders:** Scott, Development Team

## Context

After adding a new Diagnostics page to the Orpheus UI, `make update` on the Jetson appeared to succeed but the page never appeared. Investigation revealed that **every component's `update` target was broken**: it ran `git pull` + `make install` (local venv) + `make restart`, but never deployed the updated source code to the production paths under `/opt/orpheus/`. The systemd services were restarting with stale code.

This affected all 11 deployable components:

- 8 agents (`/opt/orpheus/agents/{name}/`)
- orpheus-ui (`/opt/orpheus/ui/`)
- orpheus-dashboard (`/opt/orpheus/dashboard/`)
- orpheus-gps (`/opt/orpheus/services/orpheus-gps/`)

Each component's `install-service.sh` script had the correct rsync/copy logic for initial deployment, but there was no lightweight mechanism to re-deploy source code without re-running the full install script.

### Problems with inline solutions

When we first added `deploy` targets, each of the 11 Makefiles contained its own copy of the deploy logic (~12 lines each). Reviewing the broader Makefile landscape revealed the same problem across other target categories:

- **Deploy logic** — identical rsync + copy + pip-install duplicated 11 times
- **Python venv setup** — `check-deps`, `check-python-version`, venv creation, and tool paths (`PYTHON`, `PIP`, `PYTEST`, `RUFF`) duplicated in every Python component
- **Lint/format targets** — identical `ruff check`, `ruff format`, `ruff format --check` targets in every Python component
- **Systemd management** — `start`, `stop`, `restart`, `status`, `logs`, `install-service` targets copy-pasted across all deployable components

Individual component Makefiles ranged from 200–330 lines, with the majority being boilerplate.

## Decision

Introduce four shared Makefile includes under `make/`:

| Include | Variables | Targets Provided |
| --------- | ----------- | ----------------- |
| `common_python.mk` | `PYTHON_SYSTEM`, `PYTHON_REQUIRED_VERSION`, `VENV`, `SRC_DIR`, `TEST_DIR` → derives `PYTHON`, `PIP`, `PYTEST`, `RUFF` | `check-python-version`, `check-deps`, `$(VENV)/bin/activate` |
| `common_lint.mk` | (requires `common_python.mk` first) | `lint`, `format`, `check` |
| `common_deploy.mk` | `SERVICE_NAME`, `DEPLOY_ROOT`, `DEPLOY_SRC_DIR`, `DEPLOY_EXTRA_FILES` | `deploy`, `_deploy-check` |
| `common_service.mk` | `SERVICE_NAME` | `install-service`, `uninstall-service`, `start`, `stop`, `restart`, `status`, `logs`, plus `service-*` aliases |

Each component Makefile now sets its identity variables and includes the relevant shared files:

```makefile
SERVICE_NAME := orpheus-agent-audio-motion
DEPLOY_ROOT  := /opt/orpheus/agents/$(SERVICE_NAME)

include ../../make/common_python.mk
include ../../make/common_lint.mk
include ../../make/common_service.mk
include ../../make/common_deploy.mk
```

Components that don't fit the standard pattern include only what applies:

- **orpheus-dashboard** skips `common_lint.mk` (uses prettier instead of ruff)
- **orpheus_ui root** skips `common_python.mk` and `common_lint.mk` (delegates to backend/frontend sub-Makefiles)
- **orpheus_ui/backend** uses `common_python.mk` and `common_lint.mk` at depth `../../../make/`
- **orpheus_ui/frontend** is Node.js-based and uses no shared includes

### Deploy target behavior

The shared `deploy` target:

1. Validates the deploy root exists (fails with a helpful error if `install-service` hasn't been run)
2. Rsyncs source with `--delete` to remove stale files
3. Copies configurable extra files (`pyproject.toml`, `requirements.txt`, optionally `setup.py`)
4. Runs `pip install` in the deploy venv if one exists
5. Sets ownership to `orpheus:orpheus` via `chown -R` (not rsync `--chown`, which is unavailable on macOS)

### Testing

A shell-based test suite at `tests/make/test_common_deploy.sh` validates:

- Deploy rsync behavior (source files, stale file cleanup, custom source dirs)
- Deploy failure when `DEPLOY_ROOT` is missing
- `common_python.mk` default variables and override behavior
- `common_service.mk` target definitions
- All 12 component Makefiles parse without errors
- All 11 deployable Makefiles have a `deploy` target

This test runs in CI when files under `make/` or `tests/make/` change.

## Consequences

### Positive

- Single source of truth for deploy, venv, lint, and service management logic
- Component Makefiles reduced from 200–330 lines to 80–200 lines (component-specific targets only)
- `make update` now actually deploys code to production paths
- Adding a new component is a few lines of identity variables + includes
- Cross-cutting changes (e.g., adding a new rsync flag) happen in one file
- Shell tests catch regressions in shared logic before they reach production

### Negative

- Components gain a dependency on `../../make/*.mk` — standalone use outside the monorepo would need adjustment
- The `include` path assumes a fixed directory depth (2 levels from repo root for most, 3 for `orpheus_ui/backend`)
- Shared includes add a layer of indirection — contributors must read the `.mk` files to understand available targets

### Neutral

- `make install-service` remains the mechanism for first-time provisioning (creates venv, user, systemd unit); `make deploy` only handles code sync
- Bluetooth autoconnect and MQTT are unaffected — they use different deployment patterns
- The GNU Make `?=` operator ensures component-level overrides always take precedence over shared defaults
