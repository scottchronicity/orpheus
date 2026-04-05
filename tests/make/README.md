# Makefile Include Tests

Shell-based tests for the shared Makefile includes in `make/`.

## Running

```bash
bash tests/make/test_shared_make.sh
```

No dependencies beyond `bash`, `make`, and `rsync`.

## What's tested

- **common_deploy.mk** — rsync source files, copy extra files, stale file cleanup, custom `DEPLOY_SRC_DIR`, missing `DEPLOY_ROOT` error
- **common_python.mk** — default variable values, variable override behavior
- **common_service.mk** — expected target definitions
- **Makefile integration** — all 12 component Makefiles parse without errors, all 11 deployable components have a `deploy` target

## How it works

Tests create temporary fixture directories with minimal Makefiles that include the shared `.mk` files. A `sudo` stub ensures tests run without privilege escalation. Each test validates a specific behavior and reports pass/fail.

## CI

These tests run automatically in the `test-shared-make` job in `.github/workflows/pr-tests.yml` when files under `make/` or `tests/make/` change.
