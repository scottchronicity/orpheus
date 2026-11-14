# ADR 0024: Independent Python 3.12 runtimes for GPS and event correlation

**Status:** Accepted

**Date:** 2026-11-14

**Decider:** Scott

**Clarifies:** [ADR 0020](0020-portable-capabilities-and-runtime-boundaries.md)

## Context

Most Orpheus components still declare Python 3.9 because their dependency and
deployment combinations have not yet been migrated. That repository default
must not prevent a low-coupling service from using a supported runtime, or force
native inference stacks onto it. `orpheus-common` is source-compatible with
Python 3.9 and is also consumed by newer services, while its package metadata
had incorrectly prohibited all newer interpreters.

GPS and event correlation use portable Python dependencies and do not load the
vendor GPU stack. Their local development and systemd setup can therefore move
independently. The event-correlator also runs in the Simulacrum's generic agent
container and needs an explicit container runtime selection.

## Decision

The GPS service and event-correlator support Python 3.12 and 3.13. Each keeps
its own `venv-py312` development environment, package metadata and systemd
interpreter selection. Installers default to `python3.12` and accept
`PYTHON_BIN` for a compatible interpreter at another path. The event-correlator
installer replaces its existing Python 3.9 venv when it detects an incompatible
interpreter. The GPS installer already recreates its service environment.

`orpheus-common` declares compatibility from Python 3.9 through 3.13 and keeps
Python 3.9 source compatibility for its existing consumers. The shared Make
runtime check enforces the component's configured minimum version, and when
`uv` provisions an interpreter it uses the resolved interpreter path to create
the venv. The generic agent Dockerfile has a Python version build argument; the
Simulacrum selects 3.12 only for the event-correlator image. Other images retain
their current default.

The root Make default, existing agent runtimes, BirdNET and crow dependencies,
the audio-events service environment, and the isolated validated PANNs Python
3.8 CUDA worker are unchanged. No system Python is replaced. This migration does
not imply that untested components or Jetson hardware support Python 3.12.

Python 3.12 and 3.13 are in upstream security-support phases at adoption; see
the [official version status](https://devguide.python.org/versions/). Revisit
the supported range as dependencies and platform validation evolve.

## Consequences

- GPS and event correlation can move off the end-of-life Python 3.9 line without
  imposing a common runtime on model agents.
- Existing Python 3.9 component environments remain separately managed.
- CI tests GPS and the event-correlator with Python 3.12; the shared library
  remains tested by its existing Python 3.9 suite and imported from the 3.12
  component tests.
- Deployment environments must provide Python 3.12 or 3.13 for these services.
  No Jetson deployment or hardware compatibility is claimed by this ADR.
- BirdNET, crow, audio/video capture, the UI and other components remain future
  per-component migration candidates after dependency and service validation.
