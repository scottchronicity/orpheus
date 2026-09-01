# orpheus-backplane — the Orpheus messaging backplane

The broker that carries the Orpheus "stream of consciousness" — every agent
publishes/subscribes through it. It is a **stable abstraction over the
transport**: which broker runs is config-driven, so the rest of the system
(agents subscribing to `orpheus/...` topics via the `EventBus` ABC) is unchanged
when the broker changes.

> Renamed from `orpheus-mqtt`. See
> [`docs/designs/actor-model-and-control-plane.md`](../../docs/designs/actor-model-and-control-plane.md)
> for why NATS+JetStream is now the default.

## Brokers

| `BACKPLANE_BROKER` | Broker | Notes |
|---|---|---|
| `nats` (default) | **NATS + JetStream** | One ARM-native binary: core pub/sub + durable replayable streams (event-sourcing) + a KV store (hot state / presence) + request-reply. File-storage with bounded caps (`config/nats.conf`) so it stays near mosquitto's footprint and never grows into the Jetson's unified RAM. |
| `mqtt` | Mosquitto | Fallback. Installs **as `orpheus-backplane.service`** too, so `After=orpheus-backplane.service` resolves either way. |

The active broker is selected by `event_bus.backend` in `orpheus.yaml`
(`nats` \| `mqtt`); the agents read it via `create_event_bus()`.

## Install + run

**Jetson / Linux (production, systemd):**
```bash
make install            # nats (default): downloads the binary, writes the
                             # JetStream config + systemd unit, enables + starts
# or the mqtt fallback:
BACKPLANE_BROKER=mqtt make install
make start | stop | restart | status | logs
```

**macOS (dev):**
```bash
make install                 # brew install nats-server
make start                   # runs config/nats.conf with JetStream under
                             #   $ORPHEUS_DATA_ROOT/backplane (pidfile-managed)
make run                     # ...or run it in the foreground
make status | stop
```
`make dev-stack` (repo root) starts the backplane automatically.

## Layout

- `config/nats.conf` — NATS+JetStream config (file storage, `store_dir` from
  `$ORPHEUS_BACKPLANE_STORE`, bounded `max_file_store`). `config/mosquitto.conf`
  — the mqtt fallback.
- `scripts/install.sh` — broker+platform dispatcher → `install-nats.sh` /
  `install-mosquitto.sh`.
- `systemd/orpheus-backplane.service` (nats) / `orpheus-backplane-mosquitto.service`
  (mqtt). The nats unit aliases `orpheus-mqtt.service` for migration safety.

## Status

The `nats` backend has full parity: pub/sub (agents run on it unchanged) PLUS
the JetStream surfaces — durable replayable streams (the event-sourcing shadow),
KV (retain-as-last-value, KV-TTL presence, operational health, distributed
config), and request-reply — all shipped as additive `EventBus` methods
(`orpheus_common/event_bus.py`). `retain` maps to KV last-value; presence is the
LWT replacement (a killed agent ages out of the bucket within ~3x its
heartbeat).
