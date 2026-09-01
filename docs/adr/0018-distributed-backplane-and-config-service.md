# ADR 0018: Distributed (multi-host) Orpheus over the NATS backplane, and the backplane as the config service

**Status:** Accepted — partially implemented. Shipped: the `ConfigBackend`
Protocol and both backends, the `config_service` KV layer in `OrpheusConfig`,
`orpheus-config-push`, NatsBus connect hardening, and `nats.distributed.conf`.
Not shipped, still gated on a real second host: install profiles, the installer
refusal gate, and the cert/CA lifecycle.

**Date:** 2026-06-27

**Deciders:** Scott, Development Team

**Builds on:** [ADR 0017](0017-actor-model-nats-backplane.md) (NATS+JetStream backplane),
[ADR 0015](0015-event-bus-abstraction.md) (EventBus ABC). Full design + survey:
[`docs/designs/distributed-and-config-service.md`](../designs/distributed-and-config-service.md).
Realizes the parked DB-contention / split-deployment concern.

## Context

With NATS as the backplane, two owner questions arise: (1) run the broker (and
storage/UI) on a *different host* from the sense+act agents — the parked
DB-contention split; (2) stop copying identical `orpheus.yaml` across many hosts —
"should Orpheus install a config service?" Both converge on the backplane: it
already spans hosts, and JetStream ships a KV store. We have `ConfigStore` (layered
env→DB→YAML + versioning + `subscribe`) — its persistence is the only thing wired
to SQLite. So the config service is *not* a new daemon; it's `ConfigStore` over a
JetStream KV bucket, with a tiny per-host bootstrap (`nats_url`) to reach it.

## Decision

**Topology is config, never code.** A split (sense+act on host A; broker + db +
storage + UI on host B) is expressed by per-host `event_bus.nats_url` + an install
profile + shared KV keys. Already supported: config-driven `nats_url`
(`EventBusConfig`/`create_event_bus`/`NatsBus`), proven by the Simulacrum's
per-host YAML override.

**Single-host loopback stays the shipped default.** `config/nats.conf` =
`listen: 127.0.0.1:4222`, never edited. Distributed is a *separate*
`nats.distributed.conf` selected by an install profile.

**Leaving loopback requires TLS + auth in the same change.** The installer
**refuses** to write a `0.0.0.0` listener without an auth file. LAN floor = TLS
server-auth + user/pass with per-role subject permissions (agents may publish only
`orpheus.>`; the UI can't forge detections) — **one** mechanism per tier (not
mTLS-and-password together). NKeys/JWT/mTLS is the untrusted-segment tier. The
monitoring endpoint (`:8222`) stays loopback on every host.

**NatsBus is the readiness/reconnect authority, not systemd.** A remote process
can't be a systemd dependency. So: NatsBus initial-connect becomes
optionally-non-fatal-and-retrying behind a defaulted flag (come up "disconnected,"
attach when the broker appears), the `connect()` readiness gate is fixed alongside
the reconnect kwargs (`max_reconnect_attempts=-1`, `reconnect_time_wait`), and
`servers` comma-splits for failover. The localhost path stays byte-identical.

**Config distribution is behind its OWN interface, parallel to the EventBus —
not coupled to the transport.** Two orthogonal seams: `EventBus` (messaging:
nats/mqtt/…) and `ConfigBackend` (config persistence/distribution: SQLite-local /
JetStream-KV / …). The JetStream-KV config backend *reuses* the NATS connection
(one piece of infra, not two), but that's an efficiency, not coupling: switching
the bus to MQTT does **not** break config — you fall back to `SqliteConfigBackend`
(local). The KV backend simply *requires* a KV-capable bus; selecting it on a
non-KV bus is a config error that degrades to local.

**The config service = the JetStream KV bucket backing `ConfigStore`'s backend
slot. No separate daemon.** Resolution becomes `env > KV(service) > local-yaml >
default` (KV in the old DB slot; `_normalize` runs *after* the KV read so env still
wins). The per-host bootstrap is `ORPHEUS_EVENT_BUS__NATS_URL` (note: **double**
underscore — single splits wrong) in a systemd `EnvironmentFile` — no new
`bootstrap.yaml`, no new parser. **SQLite stays the audit-of-record** (the KV ABC
is `kv_get/put/delete/watch` only — no history iteration; JetStream KV keeps a
bounded per-key revision count, not the unbounded `config_versions` trail). KV is
for *distribution + watch*, not audit.

**Reversibility-first staging.** Single-host runs today's exact
`_load_raw_config` + `_normalize` (`config_service.enabled=false`, KV never
imported). Each distributed piece is its own off-by-default flag.

## Consequences

- The Jetson DB-contention split becomes achievable: UI reads on host B stop
  contending with agent writes on host A; hot state + config move to KV/broker.
- Per-host config shrinks to one secret (`nats_url` + creds) in an
  `EnvironmentFile`; shared config is one authored KV value — no copied YAML.
- Cross-host hot-reload via `kv_watch` becomes *possible* but needs a per-component
  live-re-resolution path that doesn't exist (components read config once at boot)
  — a ~9-agent change, explicitly deferred.
- New operational surface: a CA/cert lifecycle (issue/distribute/rotate/expire)
  the runbook must own once the broker is remote.

## Sequencing (reversibility-ordered)

- **Now (independent of the KV surface):** extract a `ConfigBackend` Protocol +
  `SqliteConfigBackend` from `ConfigStore` (pure refactor, preserves the option);
  NatsBus cold-broker connect-hardening (non-fatal gate + reconnect kwargs +
  comma-split servers + creds/tls via the existing `connect_coro_factory` seam),
  with a cold-broker test; `docker-compose` overlays proving an external broker on
  a laptop.
- **After the JetStream-KV surface ships:** `JetStreamKvConfigBackend` +
  `get_instance` KV layer (the strict-required-section + env type-coercion
  reconciliation is real work; size accordingly).
- **When a 2nd host is real (human-gated):** secured `nats.distributed.conf` +
  auth template + cert bootstrap + installer refusal gate; install profiles
  (`agents-only` vs `backplane+services`) + systemd topology drop-ins; the Jetson
  split deploy.

## Rejected alternatives

- A new `bootstrap.yaml` / `ORPHEUS_BOOTSTRAP_PATH` parser — a parallel config
  primitive; the existing `EnvironmentFile` + `${VAR:-default}` substitution does it.
- A separate config-service daemon — the broker already installed is the service.
- Backing `ConfigStore.history()` on KV revisions — KV `history=N` is bounded
  (per-key, ~64), not the unbounded audit trail; `kv_history` isn't in the ABC.
- A systemd `Requires=`/remote dependency for the broker — systemd can't order
  against a remote process; NatsBus reconnect is the readiness mechanism.
- mTLS-and-password together as the LAN floor — redundant moving parts.
- Building the KV config service now, for one box — premature; the Protocol
  extraction preserves the option at ~zero cost.
