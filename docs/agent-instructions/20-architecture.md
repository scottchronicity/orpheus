# 20 — Architecture

For the full design narrative, read
[`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) and
[`docs/designs/`](https://github.com/scottchronicity/orpheus/blob/main/designs/). This file is the orientation shortcut.

## Holonic agents

Orpheus is a distributed system of autonomous agents, each a "holon"
(autonomous whole that's also part of a larger system). Each agent
runs in its own process, owns its own data, and communicates with
others via the event bus (NATS + JetStream by default; MQTT fallback —
ADR 0017). **No agent depends on internal state of another.**

Run on a Jetson Orin NX (production) or a Mac dev box (development).

## Components

```
platform/orpheus-common/      Shared library: config, EventBus (NATS/JetStream),
                              Detection / Entity / TaxonomyRef models,
                              equivalence graph, structlog, schema migrations
services/
  orpheus-backplane/          Messaging backplane (NATS + JetStream; legacy mqtt fallback)
  orpheus_ui/                 FastAPI + React UI (port 8082)
  orpheus-gps/                GPS time + location service
  orpheus-dashboard/          DEAD — superseded by orpheus_ui. Not in
                              COMPONENT_DIRS, not built, not tested. Don't extend it.
  orpheus-bluetooth-autoconnect/  Audio-out routing
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
| Python version | 3.9.5 | Jetson Orin NX system Python |
| Type syntax | `X \| None` is fine in annotations (`from __future__ import annotations`); use `Optional[X]` anywhere evaluated at runtime | 3.9 compatibility |
| Architecture | ARM64 (Jetson) + x86_64 (Mac dev) | Both must work |
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
