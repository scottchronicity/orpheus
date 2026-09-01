# Distributed Orpheus + the backplane-as-config-service (design)

Status: implemented behind [ADR 0018](../adr/0018-distributed-backplane-and-config-service.md)
— the `JetStreamKvConfigBackend` (read path), the `orpheus-config-push` write
authority, and the `get_instance` KV read layer — a direct `kv_list` snapshot, not routed through the backend class — are shipped, all opt-in behind
`config_service.enabled`. Single-host stays the default; everything here is
opt-in + reversible.

## The two questions (and why they're one answer)

1. Run the broker (+ db/storage/UI) on a **different host** from the sense+act
   agents (the parked DB-contention split).
2. Stop **copying identical config** across hosts — a "config service."

Both ride the NATS backplane: it already spans hosts, and JetStream has a **KV**
store. We already have `ConfigStore` (layered env→DB→YAML + versioning +
`subscribe`); only its persistence is wired to SQLite. So the config service is
`ConfigStore` over a JetStream KV bucket — **no new daemon** — with a tiny per-host
bootstrap (`nats_url`) to reach it.

## Config service

**Build now — the one cheap, reversible, KV-independent step:** extract a
`ConfigBackend` Protocol out of `ConfigStore` (`config_store.py`); the SQLite SQL
moves behind it as the default `SqliteConfigBackend`. Byte-identical behavior,
reverts by re-inlining. This *preserves the option* to add a KV backend without
committing to multi-host. Nothing else in the config service moves the needle on
one box.

**Backend interface:**
```python
class ConfigBackend(Protocol):
    def current(self, key) -> Any: ...          # latest value or _MISSING
    def put(self, key, value, author, changed_at) -> int: ...
    def history(self, key, limit) -> list[ConfigVersion]: ...

There is no `watch` on the Protocol. Cross-host hot-reload is not built, and
`ConfigStore.subscribe` still notifies in-process only.
```
`ConfigStore.get()` keeps `env > backend.current() > yaml_getter > default`.

**Shipped (rides the JetStream-KV ABC surface `kv_get/put/delete/watch`):**
`JetStreamKvConfigBackend` (a pure *consumer* of those methods) + a 4th
`get_instance` layer. Resolution becomes `env > KV > local-yaml > default` (KV in
the old DB slot; `_normalize` runs *after* the KV read so `ORPHEUS_*` env still
wins). **SQLite stays the audit-of-record** — the KV ABC has no history iteration,
and KV `history=N` is bounded (~64/key), not the unbounded `config_versions` trail.
KV is for distribution + watch only.

**Bootstrap (no new file):** per-host secret is `ORPHEUS_EVENT_BUS__NATS_URL`
(**double** underscore — single splits to the wrong key) in a systemd
`EnvironmentFile`, consumed by the existing `${VAR:-default}` substitution. A
single-host box keeps one `orpheus.yaml` and never sees any of this. If the broker
is unreachable at boot, fall back to the local YAML (an edge box boots on
possibly-stale config).

**Real work in the KV slice (sized honestly; now shipped):** `OrpheusConfig.__init__`
requires an `mqtt` section in strict mode, so a KV snapshot must reproduce *every*
required section; `ConfigStore` is per-key `get()` (a whole-tree `snapshot()` is
new); the env layer returns raw strings (vs `OrpheusConfig.get` type-coercing) —
that reconciliation is required, not deferrable. Highest-blast-radius file in the
platform.

## Distributed deploy

- **Topology as config:** per-host `nats_url` + install profile + shared KV keys.
  No code knows about hosts. Config-driven `nats_url` is already done.
- **Broker remoting:** a *separate* `nats.distributed.conf` (never edit
  `nats.conf`; install is a copy). Listening beyond loopback requires **auth**, and
  that half is enforced in code: `install-backbone` refuses a non-loopback `LISTEN`
  without an `AUTH_FILE`. TLS is owner-managed and may be deferred on a trusted home
  LAN (see the deployment design, D4) — mandatory on an untrusted segment, but not
  machine-enforced. LAN
  floor = TLS server-auth + user/pass with per-role subject permissions (one
  mechanism per tier). `:8222` monitoring stays loopback everywhere.
- **NatsBus is the readiness authority** (systemd can't depend on a remote
  process). The one genuine near-term code change: initial-connect becomes
  optionally non-fatal + retrying behind a defaulted flag (the `connect()` gate at
  `event_bus_nats.py` must be fixed alongside the reconnect kwargs), `servers`
  comma-splits for failover, creds/tls thread through the existing
  `connect_coro_factory` seam. localhost path byte-identical; ship a cold-broker test.
- **systemd agent→broker dep** is cosmetic today (`Wants=` is a no-op on a host
  with no local broker). Fix via per-profile `<unit>.service.d/topology.conf`
  drop-ins when the 2nd host is real — not now.

## Phased plan

1. **Now (KV-independent):** `ConfigBackend` Protocol extraction; NatsBus
   cold-broker hardening (+ test); `docker-compose` external-broker overlay
   (validate the data-plane split on a laptop, no Jetson).
2. **After the JetStream-KV surface:** `JetStreamKvConfigBackend` + the
   `get_instance` KV layer + the strict-section/coercion reconciliation.
3. **When a 2nd host is real (human-gated):** secured remote broker + auth/cert
   bootstrap + install profiles + systemd drop-ins; the Jetson split deploy.
4. **Later:** cross-host hot-reload (`subscribe` → `kv_watch` + per-component live
   re-resolution; ~9-agent change).
