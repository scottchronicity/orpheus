# ADR 0015: EventBus abstraction over the message transport

**Status:** Accepted — superseded in part by [ADR 0017](0017-actor-model-nats-backplane.md),
which made `"nats"` the default backend. The EventBus ABC and the factory below
remain live; the `"mqtt"` default does not.

**Date:** 2026-06-21

**Deciders:** Scott, Development Team

**Backlog:** "[ARCH] Abstract paho-mqtt Behind a Generic EventBus Interface" (Epic 4)

## Context

Active Inference and offline analysis want durable, replayable event logs, but
the transport today is ephemeral MQTT. The good news: agents already do **not**
import `paho-mqtt` directly — they all go through `orpheus_common.mqtt.MQTTClient`,
which already wraps paho (auto-reconnect, JSON, topic matching, LWT). What was
missing was a *transport-agnostic contract* and a *factory* so the backend
becomes a deployment decision (MQTT now; a durable stream later — see the Epic 4
"Durable Event Backend Evaluation" spike) without editing call sites.

## Decision

Add a small, **purely additive** abstraction in `orpheus-common`:

- **`EventBus` ABC** (`orpheus_common.event_bus`) with the methods the existing
  client already exposes: `publish`, `subscribe`, `unsubscribe`, `connect`,
  `disconnect`, and an `is_connected` **property** (it's a property on the
  current client; the ABC matches that so callers keep writing `bus.is_connected`).
  `EventCallback = Callable[[str, dict], None]`.
- **`MQTTClient` implements `EventBus`** (subclass) and gains the one missing
  method, `unsubscribe`. `MQTTBus` is an alias of `MQTTClient` (the
  EventBus-vocabulary name); `MQTTClient` stays the canonical name so every
  existing `from orpheus_common.mqtt import MQTTClient` keeps working.
- **`create_event_bus(config, *, client_id, ...)` factory** with a backend
  registry, reading `config.event_bus.backend` (default `"nats"`). A new
  backend is one registry entry — no call-site changes.
- **`event_bus.backend` config** (`EventBusConfig`, default `"nats"`) — additive
  and defaulted, so a config with no `event_bus:` section still validates and
  behaves exactly as before.

## Migration path

Adoption is incremental and non-breaking — `create_event_bus()` returns the same
`MQTTClient` object an agent would have built itself, so migrated and
un-migrated components interoperate. Components move from
`MQTTClient(broker_host=cfg.mqtt.broker_host, ...)` to
`create_event_bus(cfg, client_id=..., will_topic=..., will_payload=...)` one at a
time. (This change migrates `orpheus-agent-event-correlator` and `orpheus-gps`
as the first adopters; the rest follow in later batches.)

## Consequences

- **Fully reversible / stack-safe.** Pure addition: a new module, a new
  (defaulted) config section, one new method, an alias. No schema/MQTT-payload
  change, no behavior change for code still using `MQTTClient` directly. Reverts
  to bare `main` cleanly, alone or stacked with other flywheel commits.
- **Unblocks** the durable-backend evaluation spike and historical event replay
  (both `depends_on` this abstraction).
- The `is_connected` property (vs. the issue's sketched `is_connected()` method)
  was chosen to match the existing client so no caller changes.
- A second backend still needs the spike's decision before it's added; this ADR
  only lands the seam.
