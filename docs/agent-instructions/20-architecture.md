# 20 — Architecture

For the full design narrative, read
[`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) and
[`docs/designs/`](../designs/README.md). This file is the orientation shortcut.
Read the [architecture contract](../ARCHITECTURE.md#architecture-contract) and
[ADR 0020](../adr/0020-portable-capabilities-and-runtime-boundaries.md) before
changing boundaries, configuration, runtimes or deployment. Configure the capability,
not the machine. The canonical page owns that contract; this shortcut does not
define a separate one.

## Holonic agents

Orpheus is a distributed system of autonomous agents, each a "holon"
(autonomous whole that's also part of a larger system). Each agent
runs in its own process, owns its own data, and communicates with
others via the event bus (NATS + JetStream by default; MQTT fallback —
ADR 0017). **No agent depends on internal state of another.**

Run on platforms supported by the selected backend and dependencies. Jetson and
Mac are validated deployments, not an exhaustive architecture boundary.

## Components

```
platform/orpheus-common/      Shared library: config, EventBus (NATS/JetStream),
                              Detection / Entity / TaxonomyRef models,
                              equivalence graph, structlog, schema migrations
platform/orpheus-inference/   Dependency-free local IPC + process supervision
workers/orpheus-worker-panns/ Optional, separately pinned Jetson CUDA model runtime
services/
  orpheus-backplane/          Messaging backplane (NATS + JetStream; legacy mqtt fallback)
  orpheus_ui/                 FastAPI + React UI (port 8082)
  orpheus-gps/                GPS time + location service
  orpheus-dashboard/          DEAD — superseded by orpheus_ui. Not in
                              COMPONENT_DIRS, not built, not tested. Don't extend it.
  orpheus-audio-output/           Audio-out readiness (output device, audio server, reconnect)
agents/
  orpheus-agent-audio-motion/      Layer 1: detect audio events from mic
  orpheus-agent-video-motion/      Layer 1: detect video events from camera
  orpheus-agent-video-snapshotter/ Periodic camera snapshots
  orpheus-agent-video-timelapser/  Timelapse generation
  orpheus-agent-bird-detection/    Layer 2: BirdNET → IOC species
  orpheus-agent-audio-events/      Layer 2: PANNs SED → AudioSet labels
  orpheus-agent-crow-detection/    Layer 2: crow-tools call analyzer
  orpheus-agent-event-correlator/  Layer 2/3: clustering + auto-discovery
  orpheus-agent-audio-playback/    Audio output
```

## Layered data flow

```
[audio-motion] → audio.motion event
                    ↓ (parallel)
        ┌───────────┼──────────────┐
        ↓           ↓              ↓
    bird-detection  audio-events  (others)
        ↓           ↓
species.detected   audio.classified
        ↓
    crow-detection (if corvid)
        ↓
    crow.analyzed
        ↓
   ┌────────────┐
   │event-correlator│ clusters all observations of the same physical event
   └────────────┘
        ↓
    Entity event (orpheus/entities/animal)
```

Detail in [`21-event-bus-and-data-flow.md`](21-event-bus-and-data-flow.md).

## Cross-classifier identity (current major feature)

The "detectallanimals" branch introduced a 5-layer identity stack:

- **L1**: each classifier emits a canonical `TaxonomyRef` (IOC,
  AudioSet, etc).
- **L1.5**: `Detection.root_event_id` chains every Detection back to
  the audio.motion event that triggered it.
- **L2**: event-correlator clusters by time-window; one Entity per
  acoustic moment with multi-classifier evidence preserved.
- **L3**: TaxonomyEquivalenceDB stores cross-namespace mappings.
- **L3-auto-discovery**: periodic worker learns equivalences from real
  co-occurrence; no hand-curated alias map.

Full design: [`docs/designs/cross-classifier-identity.md`](../designs/cross-classifier-identity.md).

## Critical constraints

| Constraint | Value | Reason |
|---|---|---|
| Python version | Per-component metadata: currently agents generally 3.9, isolated PANNs CUDA 3.8, IPC 3.8+ | Independent runtimes; no global version lock |
| Type syntax | Match the component's supported interpreter and evaluated annotations | Shared IPC must still run on 3.8 |
| Architecture | Backend/dependency specific | Keep portable agents separate from hardware implementations |
| Test coverage | Per-component floor; see [Testing](../TESTING.md) | CI gate |
| Schema migrations | Additive only | Forward-rollback compat |

## See also

- [`21-event-bus-and-data-flow.md`](21-event-bus-and-data-flow.md) — event-bus topics
  and message shapes.
- [`22-schema-and-migrations.md`](22-schema-and-migrations.md) — DB
  schema and migration rules.
- [`docs/designs/`](https://github.com/scottchronicity/orpheus/blob/main/designs/) — feature designs (read when working
  on that feature).
- [`docs/adr/`](https://github.com/scottchronicity/orpheus/blob/main/adr/) — architectural decision records (read when
  proposing architectural changes).
