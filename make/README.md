# Shared Makefile Includes

Reusable GNU Make logic included by component Makefiles across the monorepo. See [ADR 0008](../docs/adr/0008-shared-makefile-deploy-logic.md) for the rationale.

## Files

| File | Purpose | Key Variables |
|------|---------|---------------|
| `common_python.mk` | Python venv creation, version checks, tool paths, uv acceleration, dry-run helpers | `PYTHON_SYSTEM`, `PYTHON_REQUIRED_VERSION`, `VENV`, `SRC_DIR`, `TEST_DIR`, `HAS_UV`, `PIP_INSTALL`, `DRYRUN_VENV_PATH`, `CREATE_DRYRUN_VENV`, `DRYRUN_PIP_INSTALL`, `DRYRUN_PYTHON` |
| `common_lint.mk` | Ruff lint, format, and check targets | (requires `common_python.mk`) |
| `common_deploy.mk` | Deploy source code to `/opt/orpheus/` production paths | `SERVICE_NAME`, `DEPLOY_ROOT`, `DEPLOY_SRC_DIR`, `DEPLOY_EXTRA_FILES` |
| `common_service.mk` | Systemd service management (start, stop, restart, logs, etc.) | `SERVICE_NAME` |

## Usage

Component Makefiles set identity variables, then include the shared files:

```makefile
SERVICE_NAME := orpheus-agent-audio-motion
DEPLOY_ROOT  := /opt/orpheus/agents/$(SERVICE_NAME)

include ../../make/common_python.mk
include ../../make/common_lint.mk
include ../../make/common_service.mk
include ../../make/common_deploy.mk
```

All variables use `?=` (conditional assignment), so component-level overrides set before the `include` always win.

## uv integration

When [uv](https://docs.astral.sh/uv/) is installed, `common_python.mk` detects it automatically (`HAS_UV`) and uses it to:

- **Create venvs** — `uv venv --python <version>` instead of `python -m venv` (faster, and can find uv-managed interpreters)
- **Install packages** — `PIP_INSTALL` resolves to `uv pip install --python <path>` (faster dependency resolution)
- **Provision Python** — if `PYTHON_SYSTEM` is not on PATH, `assure-python-version` can install the required version via `uv python install`

System/existing Python is always preferred; uv interpreter provisioning is a fallback.

### Additional targets

| Target | Purpose |
|--------|---------|
| `check-python-version` | Pure validation — checks for a suitable interpreter without side effects |
| `assure-python-version` | Ensures a suitable interpreter exists; installs via `uv python install` if needed |

### Dry-run helpers

Component `dry-run` targets create a disposable venv to validate installs and imports. The following variables are provided so components don't need to hard-code venv commands:

| Variable | With `uv` | Without `uv` |
|----------|-----------|---------------|
| `DRYRUN_VENV_PATH` | `.venv-dry-run` | `.venv-dry-run` |
| `CREATE_DRYRUN_VENV` | `uv venv --python <version> .venv-dry-run` | `python3.9 -m venv .venv-dry-run` |
| `DRYRUN_PIP_INSTALL` | `uv pip install --python .venv-dry-run/bin/python` | `.venv-dry-run/bin/pip install` |
| `DRYRUN_PYTHON` | `.venv-dry-run/bin/python` | `.venv-dry-run/bin/python` |

### Override examples

```bash
# Use a specific Python in a container image
PYTHON_SYSTEM=/usr/local/bin/python3.9 make install

# Use a different Python version for a component
PYTHON_REQUIRED_VERSION=3.11.0 PYTHON_SYSTEM=python3.11 make install

# Disable uv acceleration (force stdlib venv + pip)
HAS_UV= make install
```

## Which includes to use

| Component type | python | lint | service | deploy |
|---------------|--------|------|---------|--------|
| Standard Python agent | yes | yes | yes | yes |
| Service with custom linting (e.g., prettier) | yes | no | yes | yes |
| Delegating Makefile (e.g., orpheus_ui root) | no | no | yes | yes |
| Node.js frontend | no | no | no | no |

## Testing

Tests live at `tests/make/test_shared_make.sh` — run with:

```bash
bash tests/make/test_shared_make.sh
```

These tests also run in CI when files under `make/` or `tests/make/` change.
