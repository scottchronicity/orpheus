# 21 — Event bus topics and data flow

The transport is **NATS + JetStream** (run by `services/orpheus-backplane`),
reached only through the `EventBus` abstraction in
`orpheus_common.event_bus` — agents call `create_event_bus()` and never a
broker client directly. Topics are written in slash form in code; on the wire
NATS subjects use dots (`orpheus/audio/motion/events` →
`orpheus.audio.motion.events`, `#` → `>`). A legacy `mqtt` backend exists as a
config fallback (`event_bus.backend`) and is slated for removal.

## Topic conventions

| Pattern | Purpose | Example |
|---|---|---|
| `orpheus/{domain}/{type}/events` | Event notifications | `orpheus/audio/motion/events` |
| `orpheus/{domain}/{type}/status` | Agent status | `orpheus/video/motion/status` |
| `orpheus/system/{agent}/health` | Health pulse (every ~30s) | `orpheus/system/bird-detection/health` |
| `orpheus/system/auto-discovery/health` | Layer 3 worker pulse | (Layer-3 background work) |
| `orpheus/detection/{classifier}/events` | Classifier output | `orpheus/detection/bird/events`, `orpheus/detection/audio/events`, `orpheus/detection/crow/events` |
| `orpheus/entities/animal` | Correlated Entity events | (Layer 2 output) |

Agent names in `orpheus/system/{agent}/health` are `[a-z0-9_-]+` — no dots,
no wildcards; the subject↔topic mapping is lossy on dots.

## Detection event flow

A typical acoustic event triggers this chain:

1. **Audio.motion** event published by `orpheus-agent-audio-motion`.
2. **Bird-detection** subscribes to audio.motion, runs BirdNET, emits
   one or more `species.detected` events on
   `orpheus/detection/bird/events`. Each carries a canonical IOC
   `TaxonomyRef`.
3. **Audio-events** subscribes to audio.motion, runs PANNs SED, emits
   one or more `audio.classified` events on
   `orpheus/detection/audio/events`. Each carries a canonical
   AudioSet `TaxonomyRef`.
4. **Crow-detection** subscribes to bird-detection events (filters
   corvids) AND audio-events events (filters AudioSet Crow/Caw). For
   either, it runs AVES + classifier and emits `crow.analyzed` events
   on `orpheus/detection/crow/events`. Dedup'd by `audio_clip_path`.
5. **Event-correlator** subscribes to all three detection topics,
   clusters by time-window, emits one `Entity` event per acoustic
   moment on `orpheus/entities/animal`.

Each Detection carries:
- `taxonomy: TaxonomyRef` — canonical species claim (or None for
  crow-tools, which is a call-type analyzer).
- `intervals: list[TemporalInterval]` — when in the clip the
  detection fired.
- `source_event_id` — immediate parent event ID.
- `root_event_id` — chain spine to the audio.motion at the root.
  Set via `Detection.derive_root_event_id(parent_detection)`.

Per-evidence: each `EntityEvidence` row carries the emitting classifier's
own `species_code`, `species_common`, `taxonomy`, and `detection_type`.
Never collapse multi-classifier evidence into a single "consensus"
species — the layered design depends on preserving each opinion.

## Invariants for new agents

If your new agent emits events, it MUST:

1. Publish a 30s health heartbeat to `orpheus/system/<name>/health`
   with at minimum: status, events_processed, errors_count,
   last_error, timestamp.
2. If it emits a Detection downstream of another event, set
   `root_event_id` via `Detection.derive_root_event_id(parent)`.
3. If it's a sensory source (no parent), set `root_event_id =
   self.event_id` after construction.
4. If it makes a species claim, set `taxonomy` to a `TaxonomyRef`
   with a namespace from `orpheus_common.detection.namespaces.KNOWN_NAMESPACES`.
   Don't invent namespaces.
5. Increment `self.errors_count` and set `self.last_error =
   f"{type(e).__name__}: {str(e)[:200]}"` on every caught exception
   in event handlers. The UI's cross-agent error feed reads these
   from the health pulses.
6. **Persist its OWN stream to `DetectionDB`** — call `db.save()` on the
   *same* `Detection` you publish, preserving its `event_id` /
   `source_event_id` / `root_event_id`. Never rely on another service
   (especially not the UI backend) to record your stream, and never
   reconstruct a `Detection` for persistence without carrying those ids
   over — they're the cross-classifier chain. Minting a new `event_id`
   on save orphans the chain root and silently breaks correlation,
   entity clustering, lineage, and the `root_event_id` backfill. See
   [ADR 0012](../adr/0012-agents-own-their-detection-stream.md). For a
   sensory root (audio.motion) persist best-effort *after* publishing and
   swallow DB errors so storage never stalls the pipeline head.

## Delivery guarantees

The `EventBus` API keeps a `qos` parameter for compatibility; what it means
depends on the backend:

- **nats (default):** plain pub/sub is at-most-once; at-least-once delivery
  comes from JetStream durable consumers where they're used. `qos` has no
  per-message effect.
- **mqtt (legacy fallback):** `qos` maps to broker QoS — health publishes 0
  (a dropped pulse re-publishes in ~30s), detection and Entity events 1.

Whatever the backend, design handlers to tolerate redelivery: dedup by
`event_id` (the correlator and crow-detection already do).

## Listening locally

With the backplane running (`make dev-stack SVC=backplane` on a dev box),
use the `nats` CLI (`brew install nats-io/nats-tools/nats`, or the release
binary on Linux) — remember subjects are the dotted form:

```bash
# All Orpheus traffic
nats sub 'orpheus.>'

# Just one agent's health
nats sub 'orpheus.system.bird-detection.health'

# All Entity events (the "interesting" stream)
nats sub 'orpheus.entities.animal'
```

For end-to-end pumping (e.g., to smoke-test the correlator without
running real classifiers), see
[`tools/integration/pump_fake_animal_events.py`](https://github.com/scottchronicity/orpheus/blob/main/tools/integration/pump_fake_animal_events.py).

## See also

- [`20-architecture.md`](20-architecture.md) — components + layered
  flow at a glance.
- [`22-schema-and-migrations.md`](22-schema-and-migrations.md) —
  Detection / Entity model details.
- [ADR 0017](../adr/0017-actor-model-nats-backplane.md) — why NATS +
  JetStream is the transport and mqtt is a removable fallback.
- [`docs/designs/cross-classifier-identity.md`](../designs/cross-classifier-identity.md)
  — the full design for the current layered system.
