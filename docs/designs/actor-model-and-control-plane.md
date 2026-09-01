# Actor model + control plane — bundled decision (design)

Status: **ACCEPTED** — recorded in [ADR 0017](../adr/0017-actor-model-nats-backplane.md).
(The owner waived the P0 spike — "no experiments first, build it reversible"; the
control plane is built + verified live, NATS is the default, MQTT is a removable
fallback. This doc is the survey + rationale behind ADR 0017.)

Date: 2026-06-27. Driver: owner pivot.

## The question (and why it's one question)

Orpheus's agents already *are* actors: each is an independent OS process with
private state, sharing **memory** via SQLite (`DetectionDB`) and a **stream of
consciousness** via the `EventBus`. The owner asked whether to up-level this —
adopt an actor framework or hand-roll — and made two sequencing rules explicit:

1. **Design the actor model and the control/comms plane as ONE decision** — the
   actor model's requirements *drive* the plane choice, not the reverse.
2. **Implementation order inverts**: the control plane lands **first**, the actor
   model is built **on top of it**.
3. **Survey the actor *platforms* first** — several bundle their own control
   plane (Dapr, Temporal, Orleans, Akka, OTP, …), so "which actor model" and
   "which control plane" can be a single answer; that survey must precede any pick.

## Actor-model requirements (the eval criteria)

- pub/sub broadcast (the consciousness stream); presence / offline-detection
  (today MQTT LWT); periodic health heartbeats.
- request-reply (occasional point-to-point actor query).
- **durable, replayable event stream → event-sourcing**: the DB becomes a
  *projection* of the log; rebuild state from history; add a new derived view by
  replay; bootstrap a new actor from the past. (`replay.py` is the seed — it
  already re-emits a SQLite projection; this makes the log itself the source.)
- a **KV / shared-state store** for hot ephemeral state kept **off SQLite**
  (relieves the DB write-contention concern, realized by [ADR 0018](../adr/0018-distributed-backplane-and-config-service.md)).
- consumer-groups / backpressure (a slow consumer pulls at its own rate).
- multi-timescale delivery: reactive (instant) + periodic + on-demand +
  **historical (replay)**.
- supervision/restart is **already owned by systemd** — the plane need NOT provide it.
- must evolve **behind the existing `EventBus` ABC**, one agent at a time, reversibly.

## Survey (done first) — no actor platform clears the Jetson bar

One Jetson Orin NX, ARM64, ~8–16GB **unified** LPDDR5 shared with the detection
GPU, 9 Python-3.9 agents hosting CUDA models in-process.

| Option | Bundled plane? | Jetson-viable? | Python-3.9? | Event-sourcing free? | Verdict |
|---|---|---|---|---|---|
| Thespian | partial (p2p, no pub/sub) | yes (pure-py) | yes | no | solves what systemd already does; misses durable log/KV/pubsub. **No** |
| Pykka | no (in-process) | n/a | **no (3.10+)** | no | wrong scope + wrong Python. **No** |
| Ray | yes (GCS+plasma) | **no** (store ~30% unified RAM; Orin wheels) | **no (3.10+)** | no | **reject stands, firmer** |
| Dask.distributed | yes (sched+workers) | risky | **no (3.10+)** | no | task-graph engine, not a bus. **No** |
| Faust/Kafka | no (needs Kafka) | **no (JVM broker)** | yes | **yes (Kafka log)** | right semantics, fatal weight. **No** (→ "want Kafka's log in a small ARM binary") |
| Dapr | **excellent** (pubsub+KV+actors) | **bad** (9 sidecars + placement + mandatory Redis) | yes (SDK) | weak | steal the *idea*, not the runtime. **No** |
| Temporal | **excellent, event-sourced** | **dealbreaker** (4-svc cluster + DB) | SDK; rewrite | **best** | footprint kills it; not a broadcast bus. **No** |
| Orleans | good | moderate | **none (.NET)** | good | full rewrite. **Hard no** |
| Akka/Pekko | good (+Persistence) | **no (JVM heap on unified RAM)** | **none (JVM)** | **strong** | best event-sourcing *design*; unadoptable runtime. **No — steal the model** |
| Erlang/Elixir OTP | **richest** (gen_server/supervisor/dist) | +150–300MB on top of Python | **none (BEAM)** | yes-ish | gold-standard model, wrong runtime + GIL interop. **No — steal supervision vocabulary** |
| Proto.Actor | yes (gRPC) | go-only | **no (Python binding dead 2020)** | no | dead Python node. **No** |
| CAF (C++) | yes | **best footprint (<30MB)** | **none** | no | unreachable interop. **No — steal "bounded RSS as a criterion"** |
| stay MQTT (mosquitto) | incumbent | **best (<50MB)** | yes | **no (retained = 1 slot)** | presence champ; can't do durable replay or off-SQLite KV |
| NATS core | pubsub + req-reply | excellent | yes | no | on-ramp only. **No alone** |
| **★ NATS + JetStream** | pubsub + **durable log** + **KV** + pull-backpressure + req-reply | **yes** (file-storage, R=1, bounded retention) | yes (nats.py) | **YES** | **the plane that meets the requirements in one ARM binary** |
| Redis Streams | streams + best KV | **loses** — log+KV **in RAM** (grows into the GPU pool) | yes | native (RAM log) | same RAM-eats-the-model hazard that killed Ray. **No** for the log |

They all fail on the same axis: the headline thing a platform bundles
(supervision) is the one requirement Orpheus already has (systemd), while what
Orpheus needs is missing or welded to a runtime the unified-RAM box can't afford
(JVM/.NET/BEAM/Ray), or a sidecar mesh / cluster + DB (Dapr/Temporal), or a dead
Python binding (Proto.Actor). The non-Python platforms also violate the
"evolve behind the ABC, one agent at a time, reversible" mandate (rewrite/bridge
9 CUDA-hosting Python agents).

## Decision

**Hand-roll actor semantics on NATS + JetStream**, behind the existing `EventBus`
ABC — configured **file-storage + replicas=1 + bounded retention/max-bytes** so
the broker sits near mosquitto on the unified-RAM box. **Adopt no actor platform.**

JetStream is the only **single ARM binary** that turns the *simulated*
event-sourcing in `replay.py` into **real** event-sourcing (replay the append-only
log by all/sequence/start-time → stream is the source of truth, SQLite a
projection), provides **off-SQLite KV** (buckets with TTL/atomic/watch),
**pull-based backpressure**, **request-reply**, and **all four delivery
timescales** on one plane. It beats MQTT/NATS-core (no durable replay/KV) and
Redis (RAM-resident log/KV grows into the GPU pool — the hazard that killed Ray;
JetStream file-storage keeps history on disk).

**Steal the ideas, not the runtimes:**
- **Akka Persistence** → the event-sourcing blueprint: persist *events* not state;
  journal + snapshot split (don't replay from genesis); tagged events /
  persistence-query to spin up a new derived view; persistenceId-per-actor so an
  agent bootstraps from its own slice. (`ReplayEngine` already has tag semantics.)
- **OTP/BEAM** → supervision *vocabulary*: encode restart-dependencies explicitly
  in systemd units (`rest_for_one`-style, richer than flat `Requires=`/`PartOf=`),
  and the `monitor` vs `link` distinction for presence. Design pattern; systemd
  keeps owning restart.
- **CAF** → bounded predictable RSS as a first-class selection criterion (already
  why JetStream-file-storage beats a GC'd VM or a RAM log).

## EventBus ABC evolution (additive, transport-agnostic)

Existing `publish/subscribe/unsubscribe/connect/disconnect/is_connected` are
untouched (→ core NATS subjects, zero call-site change). Three capabilities land
as **optional interfaces that raise `NotImplementedError` on the MQTT backend**:

| Requirement | Added surface | JetStream backing |
|---|---|---|
| request-reply | `request(subject, payload, timeout)` | native NATS req-reply |
| durable log → event-sourcing | streams iface: `stream_ensure(stream, subjects, max_age=, max_bytes=, discard=)` + `stream_publish(subject, payload, msg_id=)` + `stream_replay(stream, callback, subject=)` — a one-shot ordered drain, project-then-ack, on an ephemeral consumer | JetStream stream = append-only log; `replay.py` gains a stream loader as a 2nd source |
| KV / hot state off SQLite | `kv_get/kv_put/kv_delete/kv_watch` (TTL) | JetStream KV bucket |
| presence (replacing LWT) | one-time `orpheus_common` helper: heartbeat → `kv_put(presence.<id>, ttl)`; watcher `kv_watch`-es expiry → emits offline | KV per-key TTL; queryable, not just an edge event |
| supervision | **not in the ABC** | stays systemd |

## Implementation order (control plane FIRST, actor model SECOND)

- **P0 [waived by the owner]** — the spike's acceptance criteria became the
  shipped `nats.conf` invariants: file storage, R=1, `max_file_store: 2GB`. It
  originally read: must prove
  (1) `nats-server` with JetStream **file-storage + R=1 + retention/max-bytes
  caps** holds **flat, near-mosquitto RSS** over a multi-day soak under load (no
  drift toward the 1GB pathology — the linchpin); (2) **no contention with CUDA
  inference** (detection latency/throughput unchanged with the broker resident —
  the unified-RAM gate); (3) durable replay works and **survives kill -9 +
  restart** (file-storage); (4) KV-TTL drives presence at parity with LWT;
  (5) pull-consumer backpressure behaves; (6) `nats.py` clean on 3.9/aarch64.
  *(a) and (b) are the whole bet.* The operator runs this on the real box.
- **P1 [shipped] — implement the plane + ABC evolution behind `create_event_bus`, default
  unchanged (`"mqtt"`), new surfaces off by default.** Register `"jetstream"` (+
  `"nats"` core) in `_BACKENDS`; add the 3 optional interfaces (NotImplementedError
  on MQTT); encode the non-negotiable Jetson config (file-storage/R=1/caps +
  retention horizon) in `orpheus.yaml` + the runbook; implement presence-emulation
  once in `orpheus_common`.
- **P2 — build the actor model on the plane** (thin in-process semantics: mailbox/
  ask via `request`, KV for hot state, the helpers + thin `Actor` base from the
  actor-model design). systemd stays supervisor; encode OTP-style restart deps in
  unit files.
- **P3 — migrate agents one at a time (reversible)**: flip
  `config.event_bus.backend` per component (dual-broker or bridge a few shared
  topics during cutover); then point `replay.py` at a JetStream stream as the real
  log; move hot state to KV buckets. End state: nats-server replaces mosquitto,
  GPU keeps its RAM, systemd still supervises.

## Decisions taken

All five were answered by what shipped; the retention horizon is
`event_sourcing.max_age_seconds: 604800`. Retained as the record of what was
weighed:

1. Accept **NATS+JetStream** as the 2nd `_BACKENDS` entry + eventual mosquitto
   replacement (vs staying MQTT and never getting durable-replay/off-SQLite-KV)?
2. Accept the trade: **lose native LWT, gain ~50 lines of KV-TTL presence** (which
   is queryable/replayable)?
3. Ratify the **non-negotiable Jetson config** (file-storage + R=1 + retention/
   max-bytes) as a deploy invariant — and the **retention horizon** (how much
   history the log keeps, which bounds "rebuild from full history").
4. **Python-3.9 floor** confirmed for now (it eliminates the 3.10+ platforms and
   is *why* hand-roll wins)? (3.9 is itself EOL; a future bump is a separate,
   decoupled decision the bus choice deliberately does not force.)
5. **Cutover policy**: dual-broker during migration vs hard switch.

## Rejected alternatives (for the ADR)

Foreign actor framework (owner-rejected; language/runtime/footprint walls; systemd
already supervises). One-God-base-for-all-9 actors (the "80% identical" premise is
verifiably 4/9). Forcing the 2 sync video agents async (a rewrite of working
code). Redis for the log (RAM-resident, grows into the GPU pool). Staying MQTT
(structurally can't do durable replay or off-SQLite KV — the two unlocks).

## Files this touches when built
- `platform/orpheus-common/src/orpheus_common/event_bus.py` — `_BACKENDS` gains
  `"jetstream"`; the 3 additive optional interfaces.
- `platform/orpheus-common/src/orpheus_common/replay.py` — a JetStream stream
  loader as a 2nd source for the transport-agnostic `ReplayEngine`.
- new `orpheus_common` modules for the JetStream backend, presence helper, and
  (P2) the actor base/helpers.
