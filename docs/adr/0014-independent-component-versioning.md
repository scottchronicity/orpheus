# ADR 0014: Independent Component Versioning (VERSION-file single source of truth)

**Status:** Accepted

**Date:** 2026-06-21

**Deciders:** Scott, Development Team

**Compatibility matrix:** [`docs/version-compat-matrix.md`](../version-compat-matrix.md)

## Context

Every component (`platform/orpheus-common`, `services/orpheus_ui/backend`,
`services/orpheus-gps`, and the nine `agents/orpheus-agent-*`) carried a
hardcoded `version` string, and `orpheus-common` carried it **three times**
(its `pyproject.toml`, its `setup.py`, and `__init__.__version__`). These
drift: the UI's `setup.py` still said `0.1.0` while its `pyproject.toml` said
`0.2.2`. There was no per-component release signal — a fix to `orpheus-common`
forced consumers to track repo HEAD, and a breaking change in one component had
no version to express it.

This is the prerequisite for publishing components to PyPI and for an automated
per-component release pipeline (both downstream backlog items): a package can't
be published or depended-on cleanly without a stable, independent version.

## Decision

1. **One `VERSION` file per component** (strict SemVer `MAJOR.MINOR.PATCH`) is
   the single source of truth, sitting next to that component's
   `pyproject.toml`.

2. **`pyproject.toml` reads it dynamically.** Each component declares
   `dynamic = ["version"]` in `[project]` and
   ```toml
   [tool.setuptools.dynamic]
   version = {file = "VERSION"}
   ```
   Build-backend stays `setuptools.build_meta`; `requires` is raised to
   `setuptools>=61.0` (the floor for file-based dynamic version). The two
   components that keep a legacy `setup.py` drop their `version=` keyword so the
   pyproject dynamic value is the only source.

3. **`__version__` resolves from installed metadata**, not a duplicated string:
   ```python
   from importlib.metadata import PackageNotFoundError, version as _pkg_version
   try:
       __version__ = _pkg_version("<dist-name>")
   except (ImportError, PackageNotFoundError):
       __version__ = "0.0.0+unknown"
   ```
   so the runtime version always equals what was built from `VERSION`.

4. **Dependents declare a minimum, open-ended `orpheus-common` floor**
   (`orpheus-common>=0.2.0`, no upper bound). In the monorepo this is satisfied
   by the editable path install in each component's `requirements.txt`
   (`-e ../../platform/orpheus-common`), so it never triggers a PyPI lookup
   during `make install`; it becomes load-bearing once components are published.

5. **`scripts/bump-version.sh <component-path> <major|minor|patch>`** bumps the
   `VERSION` file and prepends a dated `CHANGELOG.md` stub.

## Governance (proposed default — tune as the project grows)

- A maintainer bumps a component with `scripts/bump-version.sh` as part of the
  change that warrants it; the bump and its CHANGELOG stub land in the same PR.
- SemVer intent: **major** = a breaking change to a component's public API
  (for `orpheus-common`, anything importers rely on); **minor** = additive,
  backwards-compatible; **patch** = fixes with no API change.
- When `orpheus-common` takes a **major** bump, raise the `orpheus-common>=`
  floor in affected dependents and update the compatibility matrix in the same
  PR. Minor/patch bumps need no dependent changes (open upper bound).

This policy is deliberately lightweight for a solo/small-team repo; revisit if
contributor count or the release cadence grows.

## Consequences

- **Unblocks** the PyPI Publishing Pipeline and Automated Release Workflows
  backlog items (independent, buildable versions per component).
- **No behavior change at runtime** and no data/schema/config/MQTT impact —
  this is build-metadata only. The previous binary reads the same DB untouched.
- **Verified**: `make install` (editable) builds every component with the
  version resolved from `VERSION`, and `python -m build` produces correctly
  versioned wheels.
- **Reversible**: `git revert` restores the hardcoded versions; nothing is
  published or deployed by this change.
- **Cost**: a new `setuptools>=61.0` build-time floor (already met by the
  toolchain) and one `VERSION` file per component to keep current via the
  bump script.
