# Backplane Quick Start

Fast reference for the Orpheus messaging backplane (`orpheus-backplane`) —
NATS + JetStream by default, mosquitto as the one-line fallback.

## Installation (one-time setup)

```bash
cd services/orpheus-backplane
make install                       # nats (default): downloads the binary, writes config, installs the unit
BACKPLANE_BROKER=mqtt make install # mosquitto fallback instead
```

Never run `make` itself as root — targets self-sudo for the privileged steps.

## Daily operations

```bash
make status            # unit + listener state
make start
make stop
make restart
make logs              # follow logs (journalctl -f on Linux, tail -f on macOS; Ctrl+C to exit)
```

Or directly via systemd:

```bash
sudo systemctl status orpheus-backplane.service
sudo journalctl -u orpheus-backplane.service -n 50
sudo systemctl restart orpheus-backplane.service
```

(The nats unit also aliases `orpheus-mqtt.service` for migration safety.)

## Verify it's serving

```bash
curl -s http://127.0.0.1:8222/healthz     # nats monitoring endpoint → ok
```

On the mqtt fallback, the classic tools still apply:

```bash
mosquitto_sub -h localhost -t 'orpheus/#' -v
mosquitto_pub -h localhost -t 'orpheus/test' -m 'Hello Orpheus!'
```

## Connection details for agents

- **nats (default):** `event_bus.nats_url` — `nats://127.0.0.1:4222`
- **mqtt (fallback):** `mqtt.broker_host` — `localhost:1883`, anonymous
- The `orpheus/...` topic hierarchy is the wire contract on either backend.
  Wildcards: `+` single level (`orpheus/+/detections`), `#` multi-level
  (`orpheus/audio/#`).

## Python quick start

Agents never construct broker clients directly — use the factory (same code
runs on either backend via `event_bus.backend: nats | mqtt`):

```python
from orpheus_common import OrpheusConfig, create_event_bus

bus = create_event_bus(OrpheusConfig.get_instance(), client_id="my-agent")
bus.connect()
bus.subscribe("orpheus/detection/bird/events", lambda topic, payload: print(payload))
bus.publish("orpheus/test", {"hello": "orpheus"})
```

## Remote / distributed

`make install-backbone` on the broker host (REFUSES an open listener without an
AUTH_FILE); point other hosts at it with `ORPHEUS_EVENT_BUS__NATS_URL`. See the
[distributed runbooks](../../docs/runbooks/README.md) and ADR 0018.

## Troubleshooting

- Port already in use: check for a stray broker (`lsof -i :4222` / `:1883`).
- Agents can't connect: `make status` here first, then the agent's journal —
  agents come up disconnected and retry the broker forever (cold-broker
  hardening), so fixing the broker heals them without agent restarts.
- Full reference: [README.md](README.md) in this directory.
