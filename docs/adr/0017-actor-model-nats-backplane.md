# ADR 0017: Hand-rolled actors on a NATS+JetStream backplane (NATS the default)

**Status:** Accepted. Shipped: the NATS default, the `orpheus-backplane` rename,
and the KV / presence / event-sourcing surfaces (all behind off-by-default
flags). Outstanding: the Jetson NATS soak, after which §4's removal criterion
(delete the mqtt backend and the `paho` dependency) applies.

**Date:** 2026-06-27

**Deciders:** Scott, Development Team

**Backlog / design:** owner-driven roadmap pivot; full survey + design in
[`docs/designs/actor-model-and-control-plane.md`](../designs/actor-model-and-control-plane.md).
Supersedes the "MQTT now; durable backend later" posture of [ADR 0015](0015-event-bus-abstraction.md)
and resolves "[SPIKE] Durable Event Backend Evaluation".

## Context

Orpheus's agents already *are* actors: independent OS processes with private
state, sharing **memory** via SQLite and a **stream of consciousness** via the
bus. We want to make that explicit and give it real primitives — durable
replayable history (event-sourcing), a KV for hot shared state, request-reply,
multi-timescale delivery — without adopting a foreign framework or bloating the
Jetson (unified LPDDR5 shared with the detection GPU).

A survey-first evaluation (done before deciding, per the owner) scored actor
*platforms* (Ray, Dapr, Temporal, Orleans, Akka, Erlang/OTP, Proto.Actor, CAF)
and hand-roll-on-a-transport. **No platform cleared the Jetson bar**: each is
blocked by a language wall (JVM/.NET/BEAM/dead-Python-binding), the unified-RAM
wall (JVM heap / Ray's object store grow into the GPU pool), a footprint/ops wall
(sidecar mesh / cluster + DB), or violates "evolve behind the EventBus ABC, one
agent at a time." The one feature platforms bundle that we'd actually use —
supervision — Orpheus already gets from **systemd**.

## Decision

1. **Hand-roll actor *semantics* on NATS + JetStream**, behind the existing
   `EventBus` ABC ([ADR 0015]). Adopt no actor platform. systemd remains the
   supervisor. Steal *designs* (event-sourcing from Akka Persistence; supervision
   *vocabulary* — `rest_for_one`-style restart deps, `monitor` vs `link` presence
   — from OTP), not runtimes.
2. **NATS+JetStream is the DEFAULT transport.** `event_bus.backend` defaults to
   `"nats"` (the factory + `EventBusConfig`); `config/nats.conf` runs JetStream
   **file-storage with bounded caps** so the broker sits near mosquitto and never
   grows into the GPU's RAM. One ARM-native binary gives pub/sub + durable streams
   + KV + request-reply.
3. **The messaging service is the broker-agnostic `orpheus-backplane`** (renamed
   from `orpheus-mqtt`): config-driven broker, cross-platform install (nats on
   Jetson + macOS; mosquitto fallback), `nats-py` is a core dependency.
4. **MQTT (mosquitto) is a removable fallback, not a co-equal backend.** Keep it
   as a one-config-line escape hatch (`event_bus.backend: mqtt`) **through the
   first Jetson NATS soak** to de-risk the cutover. **Removal criterion:** once
   NATS is soaked + proven on the Jetson, delete the mqtt backend + the `paho`
   dependency. Do **not** build MQTT equivalents of the JetStream-only surfaces
   (streams/KV/presence) — those are `NotImplementedError` on mqtt by design.
5. **The `EventBus` ABC stays — it is not sunk cost.** A generalized,
   inject-the-client-per-config interface is justified by *one* backend: it keeps
   agents transport-agnostic, lets tests inject fakes, and makes the actor
   abstraction clean. Its planned growth (`request`, durable streams, KV) is
   additive + optional (raises on backends that can't serve a surface).

## Consequences

- **Reversible by config:** flip `event_bus.backend: mqtt` to fall back; the
  rename is git-tracked. The new code defaults to
  nats, so a coherent deploy installs the backplane first (`make services-install`
  orders it; the install removes the legacy `orpheus-mqtt.service` and the nats
  unit aliases it for migration safety).
- **The DB becomes a projection** (long game): a durable consciousness stream
  lets state be rebuilt from history; `replay.py` is the seed.
- **Off-SQLite hot state** via JetStream KV relieves the DB-write-contention
  concern; KV-TTL also restores presence (replacing MQTT LWT).
- **Verified:** macOS golden path live (brew → run → NatsBus round-trip); the
  Linux install empirically reviewer-verified (real arm64 tarball/layout/env-
  expansion); the collective validated end-to-end in the Simulacrum (synthetic
  detections off NATS → EntityEvents persisted).

## Rejected alternatives

- **A foreign actor platform** (Ray/Dapr/Temporal/Orleans/Akka/OTP/Proto.Actor/
  CAF) — language/runtime/unified-RAM/footprint walls; systemd already supervises.
- **Keeping MQTT as a permanent co-equal backend** — sunk cost: the value
  (durable streams/KV/presence) has no MQTT analogue, so MQTT can only ever be a
  degraded subset.
- **Dropping the EventBus ABC and coding NATS directly** — loses the injection
  seam, testability, and transport-agnostic agents; the ABC is cheap and right.
- **Redis Streams for the log** — RAM-resident log/KV grows into the GPU pool
  (the hazard that killed Ray); JetStream file-storage avoids it.

## Addendum (2026-06-30): the two-planes law — observability + event-sourcing

This ADR's "DB becomes a projection" + "KV-TTL presence" consequences are made
concrete by a design effort reconciling the three "stream of events" ideas (NATS
JetStream, OpenTelemetry, local metrics/Grafana). Full design + the determinism
contract: [`docs/designs/observability-and-event-sourcing.md`] and
[`docs/designs/event-sourcing-determinism-contract.md`].

1. **Two strictly-separated planes.** A *perception/domain* plane — the JetStream
   durable detection log (lossless, replayable) with SQLite as a **projection** — and
   an *instrumentation/operational* plane — OpenTelemetry traces/metrics/logs
   (sampleable, egress-only). **They never mix.** The durable domain log carries
   detections exclusively; operational signal never enters it. NATS (not OTel) is the
   domain event source-of-truth; OTel is observability exported OUT, fully optional
   (zero-dep default; no operator is forced to run Grafana to see agent health).
2. **Operational health migrates OFF the domain message bus, non-regressively.**
   Agent health/error-feed/latency that rides `orpheus/system/*/health` today moves to
   a zero-dep **NATS KV** operational substrate (`orpheus_health` bucket), via a
   flag-gated parallel run (dual-write → UI reads KV in shadow with a diff oracle →
   promote → soak → retire the bus publish, then the subs). UI changes are in scope;
   the cardinal rule is **zero regression**. On the `mqtt` fallback this is a graceful
   no-op (the bus stays the operational plane). This **supersedes an earlier
   "freeze health on the bus" stance** (owner correction).
3. **Backlog #95 / Epic 5 ("free the domain bus of observability traffic") is
   re-framed from cut to DONE-non-regressively** — it is the *outcome* of the
   migration's late phase on the nats backend, not a hard cutover. `get_meter` /
   speculative metrics scaffolding is **cut** until a real consumer exists.
4. **Event-sourcing ("rebuild by replay") is gated on a written determinism
   contract** (the `entities` projection is not faithfully reconstructable from the
   detection stream today). SQLite stays the source of truth this horizon; the
   JetStream domain stream is **shadow-only** (off-by-default
   `event_sourcing.shadow_publish_enabled`) until reconciliation proves equivalence.
