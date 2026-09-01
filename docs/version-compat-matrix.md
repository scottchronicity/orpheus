# Component version & compatibility matrix

Each component carries its own `VERSION` file (SemVer) — the single source of
truth read at build time via setuptools `[tool.setuptools.dynamic]`. See
[`adr/0014-independent-component-versioning.md`](adr/0014-independent-component-versioning.md).

Bump a component with `scripts/bump-version.sh <component-path> <major|minor|patch>`.

## Current (2026-08-26)

| Component | Path | Version | Requires `orpheus-common` |
|---|---|---|---|
| orpheus-common | `platform/orpheus-common` | 0.4.0 | — (it *is* the shared lib) |
| orpheus-ui (backend) | `services/orpheus_ui/backend` | 0.4.0 | via `requirements.txt` editable path |
| orpheus-gps | `services/orpheus-gps` | 0.2.0 | `>=0.2.0` |
| orpheus-agent-audio-motion | `agents/orpheus-agent-audio-motion` | 0.3.0 | `>=0.2.0` |
| orpheus-agent-audio-playback | `agents/orpheus-agent-audio-playback` | 0.2.0 | `>=0.2.0` |
| orpheus-agent-audio-events | `agents/orpheus-agent-audio-events` | 0.2.0 | `>=0.2.0` |
| orpheus-agent-video-motion | `agents/orpheus-agent-video-motion` | 0.3.0 | `>=0.2.0` |
| orpheus-agent-video-snapshotter | `agents/orpheus-agent-video-snapshotter` | 0.3.0 | `>=0.2.0` |
| orpheus-agent-video-timelapser | `agents/orpheus-agent-video-timelapser` | 0.2.0 | `>=0.2.0` |
| orpheus-agent-bird-detection | `agents/orpheus-agent-bird-detection` | 0.2.0 | `>=0.2.0` |
| orpheus-agent-crow-detection | `agents/orpheus-agent-crow-detection` | 0.2.0 | `>=0.2.0` |
| orpheus-agent-event-correlator | `agents/orpheus-agent-event-correlator` | 0.2.0 | `>=0.2.0` |

## Compatibility rule

Dependents declare a **minimum** `orpheus-common` version with an **open upper
bound** (`>=X.Y.Z`, no `<`). The bound is raised only when a real breaking
change in orpheus-common's public API forces it (which is also a `major` bump
of orpheus-common). Until then, any newer orpheus-common is assumed compatible.

In the monorepo, agents resolve `orpheus-common` from the editable path install
in their `requirements.txt` (`-e ../../platform/orpheus-common`), so the `>=`
constraint is satisfied locally and never triggers a PyPI lookup. The pin
becomes load-bearing once components are published (see the PyPI Publishing
Pipeline backlog item).
