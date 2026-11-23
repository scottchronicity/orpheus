# Operator's Manual

**Audience:** whoever **installs, configures, deploys, runs, monitors, and
troubleshoots** an Orpheus deployment — on a single Jetson or across a home lab.

If you want to *use the dashboard* to look at wildlife, you want the
[User Guide](../user-guide/index.md) instead.

**What's under this manual:**

| Section | Answers |
|---|---|
| [1. Install & first run](#1-install-first-run) | Getting it onto a machine for the first time. |
| [2. Configuration](#2-configuration) | Every knob, and which optional features exist and how to switch them on. |
| [3. Deployment topologies](#3-deployment-topologies) | One box, or several. |
| [4. The backplane](#4-the-backplane-messaging) | The message broker everything talks through. |
| [5. Running & supervision](#5-running-supervision) | Keeping it alive, upgrading it, the make targets you'll use. |
| [6. Health & observability](#6-health-monitoring-observability) | Knowing it's working without logging in. |
| [7. Data & retention](#7-data-retention) | What's kept, for how long, and how to move a copy elsewhere. |
| [8. Keeping the system disk safe](#8-keeping-the-system-disk-safe) | Stopping one noisy service from taking the host down. |
| [9. Troubleshooting](#9-troubleshooting) | When it isn't working. |

Doing something to a live system? The [runbooks](../runbooks/README.md) are the
step-by-step procedures. Exposing it beyond your own machines? Read
[Security](../security.md) first.

**DNA rule — keep this manual current.** Every feature that changes how Orpheus is
**installed, configured, deployed, run, or observed** must add or update a section
here in the same change (non-negotiable #12 in [`AGENTS.md`](../agents-index.md)).
If a feature only changes what an end-user *sees in the dashboard*, document it in
the [User Guide](../user-guide/index.md) instead — most features touch one, some
touch both. A feature is not done until its docs land with it.

---

## 1. Install & first run

Pick your platform quickstart, then the full install reference:

- [Installation reference](../INSTALLATION.md) — what gets installed, the `make`
  install targets, the data root.
- Platform quickstarts: [macOS](../MACOS_QUICKSTART.md) ·
  [Linux](../LINUX_QUICKSTART.md) · [Jetson](../JETSON_QUICKSTART.md) ·
  [Windows](../WINDOWS_QUICKSTART.md).

Everything is driven by `make` targets (never raw `pip`/`systemctl`) — see
[Tooling](../agent-instructions/10-tooling.md).

### Component Python environments

There is no project-wide Python version. Each component's `requires-python` in
its `pyproject.toml` is the authority; [ADR 0020](../adr/0020-portable-capabilities-and-runtime-boundaries.md)
sets that boundary. On a station:

| Components | Python | Where the interpreter comes from |
|---|---|---|
| GPS, event correlator | 3.12 or 3.13 | `make provision-python` installs CPython 3.12 at `/opt/orpheus/python`. Their installers use `/opt/orpheus/python/bin/python3.12` when it exists, otherwise `python3.12` on `PATH`. `make install-service` runs the installer under `sudo`, which drops `PYTHON_BIN`, so set `PYTHON_BIN` only when running `systemd/install-service.sh` yourself. Development environments are `venv-py312`, built with `python3.12` unless `GPS_PYTHON` / `CORRELATOR_PYTHON` names another 3.12 or 3.13 interpreter; a `PYTHON_SYSTEM` set for the 3.9 components does not affect them. |
| PANNs CUDA worker (Jetson, optional) | 3.8 | Its own isolated environment, built against NVIDIA's JetPack 5 PyTorch wheel. See [PANNs on the Jetson GPU](panns-gpu.md). |
| Everything else (the UI backend, audio-output, the capture, model and video agents) | 3.9, at least 3.9.5 | The root Makefile's default: `python3.9` on `PATH`, or the interpreter `PYTHON_SYSTEM` names. `orpheus-common` itself supports 3.9 to 3.13. |

The event-correlator installer rebuilds its old Python 3.9 service environment
when it detects one. GPS installation already recreates its service environment.
These installers affect only their component venvs; they do not change the
system Python or the inference workers. See [ADR 0024](../adr/0024-independent-python-312-runtime-migration.md).

## 2. Configuration

For optional isolated PANNs GPU inference, including automatic backend selection,
memory requirements, health and CPU rollback, see [PANNs GPU worker](panns-gpu.md).
For the speaker Orpheus plays through (`audio_output`: output device, audio
server, reconnect policy), see [Audio output](audio-output.md).

- The single source of truth is `orpheus.yaml` (runtime config lives at
  `/opt/orpheus/config/orpheus.yaml` on a deployed box; `config/orpheus.example.yaml`
  documents every knob with comments).
- Env overrides use `ORPHEUS_<SECTION>__<KEY>` (double underscore for nesting);
  env wins over file config.
- **Torch device placement:** the model agents take a `device` knob
  (`crow_detection.device`, `audio_events.device`). Crow supports `auto`, `cpu`,
  `cuda`, and `mps`; `auto` prefers CUDA, then MPS where supported, then CPU.
  Audio-events supports its configured `auto`, `cpu`, or `cuda` choices. Explicit
  accelerators fail clearly when unavailable. Pin `cpu` to keep a model off an
  accelerator under deployment-specific resource pressure.
- **Distributed config (optional, ADR 0018):** with `config_service.enabled`, a host
  reads shared config off the backplane KV (`orpheus-config-push` seeds it from one
  authority host) so hosts don't copy identical YAML — see
  [Distributed & config service design](../designs/distributed-and-config-service.md).
  Default off: local YAML only. When it is on, every section except `event_bus` and
  `config_service` is shared, and shared values win over the host's own YAML. Put
  per-host values (`audio.channels`, `audio_output`, `storage`,
  `mirror.staging_path`) in that host's `/opt/orpheus/config/.env` as
  `ORPHEUS_<SECTION>__<KEY>` variables, which win over both.

### Optional features and their switches

#### BirdNET execution provider

`bird_detection.execution_provider` selects BirdNET's ONNX Runtime provider:
`auto` (default), `cpu`, `cuda`, or `coreml`. `auto` chooses the first provider
available to the BirdNET agent's installed ONNX Runtime, in CUDA, CoreML, CPU
order. ONNX Runtime may assign unsupported model operators to CPU when an
accelerator provider is enabled. Explicit accelerator choices fail startup if
that provider is not exposed by the installed runtime.

The normal BirdNET installation uses the CPU `onnxruntime` package. CUDA
requires installing a compatible `onnxruntime-gpu` package in this agent's
environment instead; ONNX Runtime CPU and GPU packages must not coexist in one
environment. Orpheus does not install accelerator packages globally or pin a
CUDA stack for all hosts. Use `make -C agents/orpheus-agent-bird-detection
install-cuda` to select the CUDA runtime; this removes either existing ORT
distribution before installing the other. It installs `onnxruntime-gpu` from
PyPI, so it works only where PyPI publishes a wheel for your platform: check
first with `pip download onnxruntime-gpu --no-deps`. On a Jetson, a CUDA build
of ONNX Runtime may need a vendor wheel instead. jetson1 runs the CPU default. Agent health reports the requested
provider, `inference_provider_requested`, the registered providers,
`inference_providers_registered`, and the first registered provider as
`inference_provider`. `auto` means available according to ONNX Runtime, not
hardware-validated for a particular deployment.

Everything here is **off unless noted**. Turning one on is a config edit plus a
restart of the affected component; turning it off is the same edit in reverse.
[What's new](../whats-new.md) explains what each feature buys you.

| Feature | Key | Default | Turn it on when |
|---|---|---|---|
| Agent presence | `event_bus.presence_enabled` | `false` | You want the dashboard to show which agents are alive right now (needs the NATS backend). |
| Health over KV | `event_bus.health_kv_enabled` + `ui.health_source` | `false` / `bus` | You are migrating health off the message bus; run both planes and compare before switching the reader. |
| Durable event log | `event_sourcing.shadow_publish_enabled` | `false` | You want a replayable log of detections alongside the database. Bounded by `max_age_seconds` and `max_bytes`. |
| Distributed config | `config_service.enabled` | `false` | More than one host, and you are tired of copying identical YAML. |
| One-click guest sign-in | `ui.guest_quick_login` | **`true`** | On by default: the login page offers a guest button that signs in server-side, so no password is shipped to the browser. Anyone who can reach the port can view the dashboard while this is on — turn it off for an instance that is not on a network you control. |
| Equivalence discovery | `correlation.auto_discovery.enabled` | **`true`** | On by default. Scans every `interval_seconds` (6h) over `lookback_days` (7); pairs at or above `accept_threshold` go live, pairs above `propose_threshold` queue for review on the Equivalences page. |
| Entity-type topics | `correlation.publish_entity_type_topics` | `false` | Something downstream wants to subscribe per entity type rather than filter. |
| Latent state-space memory (consumer *stubbed*) | `correlation.state_space_memory_enabled` | `false` | You want to start accumulating the site's history now. The correlator records into it; nothing consumes it, so correlation behaves identically either way. The consumer is tracked as *Act on the latent memory — an active-inference consumer*. |
| Geographic filtering | `bird_detection.geo_filter_min_prob`, `geo_filter_weak_admit_prob`, `geo_filter_weak_admit_conf` | `0.03` / `0.0005` / `0.85` | Active by default. Raise `min_prob` to suppress more out-of-range species; the weak-admit pair is the escape hatch that lets a confident rare visitor through. `bird_detection.site_species_whitelist` always admits named species. All four live under `bird_detection:`, not `detection:` — the bird agent reads only that section, so a copy placed under `detection:` parses without error, logs nothing, and changes nothing. |
| BirdNET execution provider | `bird_detection.execution_provider` | `auto` | Selects `auto`, `cpu`, `cuda`, or `coreml`. `auto` checks providers exposed by ONNX Runtime in the BirdNET agent environment, preferring CUDA, then CoreML, then CPU. Explicit unavailable providers fail startup. CUDA requires compatible `onnxruntime-gpu` instead of `onnxruntime`; do not install both in one environment. Base installs remain CPU-only. |
| Corollary discharge | `corollary_discharge.enabled`, `corollary_discharge.buffer_seconds` | `false` / `2.0` | Orpheus plays audio at your site and you don't want it recorded as wildlife. Entities are tagged, never dropped. |
| Weather (*stubbed*) | `weather.enabled`, `weather.url` | `false` | You have an Ecowitt-compatible station on the LAN — but the Ecowitt field mapping is unimplemented, so the ingestor raises and exits on its first poll and the card stays empty. Enabling this is only useful if you are the one grounding that mapping. Tracked as *Finish the weather integration*. |
| Read-only mirror (service *stubbed*) | `mirror.enabled`, `mirror.transport`, `mirror.dest` | `false` | Dashboard reads are contending with live writes, or you want a copy on another host. Pair with `ui.read_from_replica` on the reader — and set `mirror.staging_path` there too, to the path the push lands at: it is a per-host setting, and the UI resolves the replica from its own host's value, so a reader that leaves it empty falls back to the live DB. The CLI works; run `orpheus-mirror` yourself from cron or your own unit — the flag reserves the setting for a future service, it does not start one. Tracked as *Read-only mirror host: serving stack + public portal*. |
| Public projection | `public.enabled`, `public.site_label` | `false` | You are sharing observations publicly. Fail-closed: time buckets to the day and location renders a label, never a coordinate. |
| API rate limiting | `ui.rate_limit_enabled`, `ui.rate_limit_requests`, `ui.rate_limit_window_seconds` | `false` / `300` / `60` | The UI is reachable beyond your own LAN. |
| Query budget | `ui.query_timeout_seconds` | `0.0` (none) | A slow query must fail fast rather than tie up the database. |
| Tracing (*stubbed*) | `telemetry.enabled`, `telemetry.backend` | `false` / `console` | The module and its optional dependencies ship and the backends are wired, but nothing calls `setup_tracing` and no component creates spans, so enabling this emits nothing. Tracked as *OpenTelemetry (OTel) Migration*. |
| Per-agent tick rates | `agents.<name>.heartbeat_seconds` | `30.0` | One agent should report faster or slower than the rest. |

### One component deletes recordings

Retention is owned by `orpheus-storage-sweep`, a one-shot run from
`orpheus-storage-sweep.timer` every 15 minutes. No agent deletes anything, and
every category under `$ORPHEUS_DATA_ROOT` — audio clips, motion video, snapshots
and timelapses alike — is subject to the same policy. See [§7](#7-data-retention)
for the knobs and the operator commands.

It enforces a **ceiling** per category (`max_gb`, applied whether or not the disk
is under pressure), relieves **pressure** when free space falls below
`reserve_gb` by taking proportionally from every category above its floor, and
refuses to breach a **floor** (`floor_days`) for any reason. When a floor and a
ceiling contradict each other the floor wins: the sweep logs at CRITICAL and
leaves the ceiling breached rather than delete recent recordings.

The first sweep after an install reports what it would delete and deletes
nothing, for `first_run_grace_hours` (default 24). Review it with
`make storage-report` before enforcement begins.

Row retention is the one part still *stubbed*: `storage.retention.detections_days`
is accepted and nothing applies it, so detection history keeps growing — tracked
as *Enforce detections_days — retention for database rows*.

## 3. Deployment topologies

- [Deployment guide](../DEPLOYMENT.md) — the single-host happy path.
- Distributed (home lab) runbooks:
    - [Backbone on the NUC](../runbooks/distributed-backbone-on-nuc.md)
    - [Agents split across hosts](../runbooks/distributed-agents-split.md)
    - [Portal on its own host](../runbooks/distributed-portal.md)
    - [Runbook index](../runbooks/README.md)
- Design + decisions: [Distributed deployment](../designs/distributed-deployment.md),
  [ADR 0018](../adr/0018-distributed-backplane-and-config-service.md).

The backbone (NATS broker + services) is movable (Jetson or NUC); topology is
config (`ORPHEUS_EVENT_BUS__NATS_URL`), validated in docker-compose before metal.

**Run the collective in containers (the Simulacrum, no hardware):** `make sim-up`
starts the backplane + correlator + a sim-source (`demo` profile); the `fleet`
profile adds the real classifier agents + the UI (models mounted from
`artifacts/models`). The sim-source has two modes via `SIM_MODE`: `synthetic`
(default — grounded synthetic detections exercise the correlator) and `replay` —
it replays the REAL clips in `artifacts/audio-samples/` as `audio.motion` chain-root
events, so the fleet profile runs the real models on real audio and the classifiers
decide (`SIM_MODE=replay make sim-up`). Services carry healthchecks — `make sim-status`
shows `(healthy)`. Verified: BirdNET identifying the bundled robin/jay clips
end-to-end through the correlator to EntityEvents.

**Generate manifests from the config (keep topology in sync):**
`orpheus-manifest-gen` (or `make manifests TARGET=systemd`) reads `orpheus.yaml` and
emits either a systemd `orpheus.target` (Wants exactly the enabled units — reuses the
shipped per-agent `.service` files) or a docker-compose file (`TARGET=docker-compose`),
so which agents/services run tracks the config (audio channels → the audio pipeline;
cameras → video-motion plus the capture agents video-snapshotter/video-timelapser; the
correlator/backplane/UI are always in). Deterministic + idempotent. The compose `image:`
tag is a convention your build fills. Every shipped agent must be in the generator's
catalog — `make guardrails` fails if one is missing, so a target can't silently drop it.

**Camera timelapses:** The configured timezone sets the schedule and the output
date. The timelapser reads snapshots from every UTC-date folder that overlaps
the video’s time window, including when the window crosses midnight.

## 4. The backplane (messaging)

- Default backend is **NATS + JetStream** (`event_bus.backend: nats`); mosquitto
  **mqtt** is the one-line fallback.
- JetStream provides durable streams, KV, and request-reply
  ([ADR 0017](../adr/0017-actor-model-nats-backplane.md)). Subjects mirror the MQTT
  topic hierarchy ([event bus & data flow](../agent-instructions/21-event-bus-and-data-flow.md)).

## 5. Running & supervision

- systemd supervises the agents + services; agents are thin actors on the backplane
  with a 30s heartbeat ([Actor model](../designs/actor-model-and-control-plane.md)).
  **Per-agent tick frequency:** `agents.<name>.heartbeat_seconds` in `orpheus.yaml`
  tunes each agent's heartbeat independently; unlisted agents keep the 30s default.
  The KV presence and health TTLs are *not* per-agent — NATS fixes one TTL for the
  whole bucket, so every agent requests the same value: 3x the largest heartbeat you
  configured anywhere, floored at 90s. Slowing one agent therefore slows how fast
  every *other* agent is detected as dead. That TTL is also set by whichever agent
  creates the bucket first and ignored on every write after, so changing a heartbeat
  on a running station moves the tick and leaves the TTL alone until you delete the
  `orpheus_presence` and `orpheus_health` buckets on the broker.
- Use the per-component `make` targets to install/restart; never run as root.
- **The targets you will actually use**, from the repo root:

    | Command | Does |
    |---|---|
    | `make install-backbone` | Installs and starts the message broker. Run this **before** restarting agents on an upgrade. |
    | `make services-install` | Installs unit files, including any agent this release adds. |
    | `make update-services` | Updates each component's code and restarts it. Stops on the first failure. |
    | `make services-start` / `services-stop` / `status-all` | Bulk supervision. |
    | `make check-models` / `download-models` | Verify the ML checkpoints are present; fetch the ones that can be fetched. Both read `$ORPHEUS_DATA_ROOT`. |
    | `make manifests TARGET=systemd\|docker-compose` | Generates the deployment topology from `orpheus.yaml`. |
    | `make dev-stack` / `dev-status` / `dev-logs` / `dev-stop` | Runs the whole stack as background processes on a development machine — no systemd, no root. |
    | `make backfill-root-event-ids` / `backfill-entity-types` | One-time upgrades of historical rows. Run the `-dry-run` variant first; both print what they would change. |
- **Post-upgrade check:** after any update, `make verify-deploy` (repo root) is a
  read-only health check — every component venv imports its package, systemd units
  are present/active, models are in place. Non-zero exit means something needs
  attention before you walk away. The models + data-read checks look under
  `$ORPHEUS_DATA_ROOT` (default `/data/orpheus`); on a dev laptop pass
  `ORPHEUS_DATA_ROOT=$HOME/data/orpheus` or they skip.

## 6. Health, monitoring & observability

- **Dashboard health:** the Orpheus UI's Diagnostics page surfaces correlator health,
  storage trend, per-category storage headroom, recent errors across agents, agent
  presence, and audio system health;
  model latency is on the Audio Events page (see [Orpheus UI](../ORPHEUS_UI.md) and the
  [User Guide](../user-guide/index.md)).
- **Dashboard polling (`dashboard.poll_interval`, ms):** the UI now reads this served
  value at load and scales every polling tier from it (default 5000). Raise it to cut
  the dashboard's read pressure on the SQLite DB (the read-contention lever short of the
  read-only mirror below); the value is served on `GET /api/config` and applied before
  first render, so a bad/absent value falls back to the built-in defaults.
- **Dashboard services (`dashboard.services`):** the units the dashboard's Service
  Status card shows, in order; without the key, the list in
  `config/orpheus.example.yaml` is used. An upgrade keeps your list as it was, so after
  a service is renamed or retired, update it from the example. Until you do, the card
  flags each stale entry: a retired unit as not installed, a renamed one as an alias
  of its replacement (`orpheus-mqtt` → `orpheus-backplane`,
  `orpheus-bluetooth-autoconnect` → `orpheus-audio-output`). `make verify-deploy`
  lists the same entries under "Dashboard service inventory".
- **Operational vs domain planes (the law):** operational signal (health, metrics,
  traces) is kept off the durable domain event log; agent health is moving onto a
  zero-dependency NATS **KV** plane, and deep telemetry is optional OpenTelemetry/OTLP
  — see [Observability & event-sourcing](../designs/observability-and-event-sourcing.md).
  Basic agent-health visibility never requires Grafana/Prometheus.
- **Presence:** a kill -9'd agent ages out of the KV presence bucket within its TTL
  (the NATS replacement for MQTT last-will).
- **Where the dashboard reads health from (`ui.health_source`):** during the
  non-regressive migration of health off the domain bus, this flag selects the source
  the UI *serves* from — `bus` (default, today's path), `both` (read the KV plane in
  the shadow + expose `/api/diagnostics/health-source-diff` to prove equivalence, but
  still serve from the bus), or `kv` (serve from the KV plane). Promote `both → kv`
  only after a soak where the diff endpoint stays equivalent; rollback is a single
  flip back, no redeploy. On the mqtt backend it always falls back to `bus`. The
  producer-side `event_bus.health_on_bus` (default `true`) is the LAST step: set it
  `false` to stop agents publishing health to the domain bus — but only honored when
  KV health is active on the producer, so flipping it while KV is off leaves the bus
  publish in place.
- **Weather-context join (follows `weather.enabled`, default off):** the correlator
  attaches the freshest weather reading to each emitted entity's context
  (`context.weather` — additive; old binaries ignore it). A reading older than
  2× `weather.poll_interval_seconds` is treated as stale and not attached, so an
  ingestor outage leaves the field absent rather than wrong. `entities_weather_tagged`
  in the correlator health payload counts what it tagged. **No reading reaches it
  today:** the join is built and tested, but the Ecowitt field mapping it depends on
  is unimplemented (see the weather row above), so `entities_weather_tagged` stays at
  zero until that mapping is grounded.
- **Correlator late-arrival enrichment (`correlation.late_enrichment.enabled`, default
  off):** when on, a slow classifier's detection arriving after its acoustic moment's
  cluster closed is folded into the recently-emitted entity (same DB row updated in
  place) instead of spawning a duplicate. Enriched-entity updates publish on
  `orpheus/entity-updates/animal` — never the create topics, so create-counting
  consumers are unaffected. Watch `entities_enriched` in the correlator's health
  payload to see it working; `ttl_seconds` (default 300) bounds how long an entity
  stays enrichable. Rollback is the flag — setting it back to `false` restores the
  duplicate-entity behaviour.
- **Corollary discharge (`corollary_discharge.enabled`, default off):** when on,
  the correlator subscribes to the playback agent's window events
  (`orpheus/actuation/audio/playback`) and tags entities that overlap Orpheus's
  own audio playback with `is_self_generated: true` — **tagged, never dropped**,
  so the data stays available for analysis and the dashboard doesn't count the
  system hearing itself as wildlife. `corollary_discharge.buffer_seconds`
  (default 2.0) pads each window's tail to catch reverb/late triggers.
  `max_playback_seconds` (default 300) bounds an announced playback if the
  playback agent stops before sending its measured finish event. The playback
  agent publishes start and finish events with the same ID; the finish contains
  the measured elapsed duration. Overlapping detections remain in the entity
  evidence and database, including wildlife heard at the same time. Off (the
  default): no playback subscription and no tagging. Rollback is the flag. See
  the [audio output guide](audio-output.md) for speaker setup.
- **Logging:** [Logging guide](../LOGGING.md).

## 7. Data & retention

- Detections + entities persist to SQLite under `$ORPHEUS_DATA_ROOT`
  (default `/data/orpheus`); clips live alongside under retention caps configured in
  `storage:`.
- **The data drive at boot.** On a station the data root is its own drive. Every
  service that reads or writes it (the nine agents, the UI, and the storage sweep)
  declares `RequiresMountsFor=/data/orpheus`, so it waits for the drive at boot,
  does not start without it, and stops if the drive goes away, instead of writing
  recordings and a fresh, empty database onto the root filesystem.
  `make verify-deploy` checks what systemd has loaded ("Data-drive dependency"),
  and `make guardrails` fails a unit in the repository that lacks it.
  The mount itself is host configuration, outside the repository: an `/etc/fstab`
  line such as `UUID=<the drive's UUID> /data/orpheus ext4 defaults,nofail 0 2`
  (`blkid` gives the UUID). Keep `nofail`: without the drive the station still
  boots and answers on SSH, with the data services held back. After such a boot,
  reconnect the drive: with the recovery below installed, it mounts and the
  services start by themselves. Without it, run
  `sudo systemctl start data-orpheus.mount`, then start the services in the
  order the [rollout runbook](../runbooks/jetson-rollout.md) gives, or reboot.
- **Connecting the data drive.** Give it a SuperSpeed link with its own power:
  a USB 3 port on the board, or an externally powered USB 3 hub. Check with
  `lsusb -t`: the drive should show `Driver=uas` at `5000M` or `10000M`. Avoid
  a bus-powered hub, and any hub that links at USB 2 only (`480M`). On jetson1
  a bus-powered USB-C hub could not power the drive and reset every few
  seconds, taking everything else on it (the Ethernet adapter included) down
  with it. Make sure the plug cannot work loose: a loose plug at the board's
  USB-C port was enough to lose the drive at a reboot. The
  [jetson1 hardware manifest](https://github.com/scottchronicity/orpheus/blob/main/platform/jetson-orin-nx-yahboom/HARDWARE_MANIFEST.md)
  records how that station is wired.
- **Unplugging the data drive** (to move it or change a cable), without a reboot:
  1. `sudo systemctl stop` the data-root services by name (the nine agents and
     `orpheus-ui`; `scripts/data-root-units.sh` lists them). Stop them before
     the mount: while a stop of the mount alone is in progress, any other unit
     that starts (a crash reporter, for one) pulls `local-fs.target` and with it
     the mount back in, which cancels the stop and restarts the services.
  2. `sync`, then `sudo systemctl stop data-orpheus.mount`.
  3. Once `findmnt /data/orpheus` shows nothing, detach the disk so nothing can
     mount it again before you pull it:
     `echo 1 | sudo tee /sys/block/<sdX>/device/delete`.
  4. Unplug it and plug it in where it is going. The recovery below mounts it
     and starts the services. Confirm with `lsusb -t` and `make verify-deploy`.
  Leave `orpheus-storage-sweep.timer` running. Stopping and starting it later
  in the same boot leaves it with no next run (its `OnBootSec` has passed and
  its last run is forgotten) until the sweep runs once more.
- **When the data drive drops out.** If the drive drops out while running (a USB disconnect), systemd stops every
  data-root service with it, so nothing writes onto the root filesystem.
  `make install-data-root-recovery` (run by `make install-host`) installs a udev
  rule that mounts the drive again when it reappears, after the usual `fsck`,
  and each data-root service's `WantedBy=data-orpheus.mount` restarts it with
  the mount. A service you disabled stays stopped, and a drive that fails its
  `fsck` stays unmounted. `make verify-deploy` checks this ("Data-drive
  recovery"). The installer reads the drive's identity from `/etc/fstab`, so
  any local disk works with no source change. The requirements:
  - **Mount point:** the drive must be mounted at `/data/orpheus`. Every
    shipped unit requires and restarts with that mount. The installer refuses
    a separate drive mounted elsewhere, including one mounted at `/data` with
    `/data/orpheus` a directory on it, and `verify-deploy` fails it.
    `ORPHEUS_DATA_ROOT` elsewhere is for development hosts only.
  - **How fstab names it:** by `UUID=`, `LABEL=`, `PARTUUID=`, `PARTLABEL=`
    or a `/dev/disk/by-*` path. A kernel name like `/dev/sda1` can change when
    the drive reconnects. The installer skips it with a warning, so the rest of
    the install still runs, and `verify-deploy` fails until fstab is fixed.
  - **Where recovery doesn't apply:** if the data root is on the system disk
    or on a network share, there is no drive to recover, and both the installer
    and the check pass.
  Two things the recovery cannot undo: clips that were being written when the
  drive dropped out are cut short (their FLAC headers are never finished), and
  after a power cut journald renames the journal it was writing before the clock
  is set. The shipped `make install-log-bounds` drop-in therefore has no
  `MaxRetentionSec`, which would delete that journal at once.
- **The clock at boot.** Recordings, clip names and database rows are stamped
  with the system clock, and a Jetson has no battery-backed clock unless a coin
  cell is fitted to the carrier's RTC connector. `make install-clock-guard`
  (run by `make install-host`, effective from the next boot) does two things.
  It enables `systemd-time-wait-sync`, so `time-sync.target`, which every
  data-root service starts after, waits until NTP has set the clock (bounded at
  300 s). On a Jetson it also runs NVIDIA's `nvrtc-sync-boot` before
  `systemd-timesyncd`, so a batteryless RTC cannot set the clock back to 1970
  after timesyncd has restored the last known time. Offline, the station starts
  after 300 s on that restored time (behind by the outage, never 1970), and NTP
  corrects it once the network returns. Only a coin cell makes offline time
  exact. `make verify-deploy` checks all of this ("Clock at boot"), and
  `make guardrails` fails a data-root unit without `After=time-sync.target`.
  If rows were recorded on a wrong boot clock anyway, measure the step in the
  same boot, before any reboot: compare `realtime - monotonic` now with a unit
  started before the step, using `busctl get-property` on
  `ExecMainStartTimestamp` and `ExecMainStartTimestampMonotonic`. Then repair
  with `scripts/repair-clock-step.py` (`plan`, then `apply` with an undo file,
  run as the data's owner). It moves the rows by the step, renames their clips (moving a clip's mtime by the step too when it was finished on the boot clock, since the storage sweep ages files by mtime),
  and repoints every detection and entity that names them.
- **`orpheus-storage-sweep` is the only thing that deletes a recording.** It is a
  one-shot unit driven by `orpheus-storage-sweep.timer` every 15 minutes, installed
  with the platform library by `make services-install`. No agent trims its own
  directory any more, which is what lets one component weigh every category
  against the single filesystem they share.
- **The knobs, under `storage.retention`.** Each category in `categories` has a
  **ceiling** (`max_gb`) and a **floor** (`floor_days`). The ceiling is enforced
  whether or not the disk is under pressure, oldest file first. Separately, when
  free space falls below `reserve_gb` (default `100`), every category above its
  floor gives up data in proportion to how much it has to give, so one category
  does not lose everything while another sits untouched. The floor is absolute:
  the sweep never deletes a file inside it, and if that means a ceiling cannot be
  reached, or the reserve cannot be met, it logs at CRITICAL and stops rather than
  taking your recent history. `min_file_age_hours` is a second hard floor that
  always applies. Age limits count elapsed time across daylight-saving changes.
  `min_free_space_percent`, if set, is read as a percentage of the
  whole disk and reconciled with `reserve_gb` — the stricter of the two wins.
  Every `*_gb` key is **GiB** (1024³ bytes, what `df -h` and the dashboard show);
  the `_gb` spelling is kept so that stations with ceilings already configured
  do not silently lose them. Shipped defaults: audio 600 GiB / 30 days, motion
  video 60 GiB / 90 days, snapshots 450 GiB / 90 days, timelapses 450 GiB /
  90 days.
- **Commands.** `make storage-report` is a dry run that decides exactly what a real
  sweep would and deletes nothing, printing a per-category table — run it before
  changing a ceiling and after any deploy. `make storage-sweep` runs one real sweep
  now. `sudo systemctl disable --now orpheus-storage-sweep.timer` or
  `storage.retention.sweep_enabled: false` stops all deletion; the second keeps
  measuring, so the dashboard still shows what is growing. The first sweep after an
  install reports and deletes nothing for `first_run_grace_hours` (default 24);
  `orpheus-storage-sweep --force` ends that grace early. An exit code of `2` means
  free space is below the reserve and every category is at its floor — the one
  condition that needs a person, so the unit fails on purpose rather than showing
  a green timer.
- **The record of what went.** Each sweep that deletes writes a CSV manifest to
  `$ORPHEUS_DATA_ROOT/.storage-sweep-manifests/` naming every path, its size and
  its timestamp, and logs the category, the counts, and the window of recording
  that disappeared. The last 50 manifests are kept.
- **Keys that no longer do anything.** `raw_audio_days`, `raw_video_days`,
  `max_size_gb`, `cleanup_trigger_percent`, `cleanup_amount_percent` and
  `check_interval_hours` are still accepted and validated so an existing
  configuration parses, but nothing applies them — `floor_days` and `max_gb`
  replaced them. `video_snapshotter.retention_days` is inert for the same reason,
  and the snapshotter says so in its journal at startup.
- **Seeing where the space went.** The UI's Diagnostics page has a *Storage
  headroom* panel listing every category under `$ORPHEUS_DATA_ROOT` — audio clips,
  motion video, snapshots, timelapses, and the database — with its current size
  and, where one exists, the ceiling and floor that trim it. The numbers come from
  the report the sweep publishes to `$ORPHEUS_DATA_ROOT/.storage-sweep-state.json`
  on each run, so they are as fresh as the 15-minute cadence and carry the time
  they were taken; nothing is measured in the request path. Before the first sweep
  has run — a fresh install, or a station with the timer disabled — the panel
  reports "not yet measured" rather than zeros.
- A read-only **mirror/replica** can serve heavy reads (UI, exports) off the Jetson —
  see [Read-only portal](../designs/read-only-portal.md). If `ui.read_from_replica` is set
  before the mirror has produced a snapshot (or it's disabled/broken, or `mirror.staging_path`
  is not set on the reading host), the UI falls back to the live DB with a warning rather
  than 500-ing every read, so flipping the flag early is safe. That fallback is
  journal-only today — the UI logs a warning and carries on, and nothing on screen
  tells you which database you are looking at, so check the log after flipping the
  flag (tracked as *Show which database the dashboard is reading*).
  On a separate portal host see the
  [portal runbook](../runbooks/distributed-portal.md) — the reader-side `staging_path`
  is the step that gets missed. The rsync push is bounded by `mirror.push_timeout_seconds` (default 300) so a
  half-open SSH can't hang the mirror loop past its next cycle or the stop signal.
- **Read-surface protection (portal prerequisite N2, both off by default):**
  `ui.rate_limit_enabled` turns on per-client API rate limiting (sliding window over the
  existing CircuitBreaker; `ui.rate_limit_requests`/`ui.rate_limit_window_seconds`,
  default 300/60s; a tripped client gets 429 + Retry-After, and the trip logs once).
  `ui.query_timeout_seconds` (default 0 = unbounded) puts a wall-time budget on each of
  the UI's DB queries — a runaway portal/LLM query is interrupted instead of starving
  the box. Both are the "not-DDoS-able" floor for sharing the read-only portal and the
  prerequisites for the MCP serving chain.
- The public export (`orpheus-public-export`, off-Jetson, gated by `public.enabled`) writes
  `entities.json` with a provenance envelope — `generated_at` (coarsened to
  `public.time_granularity`, never second-precision), `count`, and `site_label` — so a
  citizen-science consumer can judge staleness and dataset scope.
- **Event-sourcing shadow (`event_sourcing.shadow_publish_enabled`, default off,
  nats-only):** when on, agents that own a domain stream ALSO publish their detections
  to a bounded JetStream durable stream (in addition to the SQLite save) so the durable
  log earns a first writer and the reconciliation evidence a future "stream is truth"
  inversion needs. SQLite stays the source of truth; the stream is bounded
  (`max_age`/`max_bytes` well under the account store, `discard: old`) so it reverts by
  ageing out. See [Observability & event-sourcing](../designs/observability-and-event-sourcing.md)
  and the [determinism contract](../designs/event-sourcing-determinism-contract.md).
  Each owning agent's health payload reports `event_sourcing_shadow` (true only when
  the shadow actually resolved on — nats + `stream_ensure` succeeded), so a silent
  self-disable (e.g. shadow enabled but running on mqtt) is visible in that payload
  and in the agent's journal rather than leaving you to assume reconciliation
  evidence is being collected when it isn't. No dashboard panel reads it today. Verify the shadow with `orpheus-reconcile` (or `make reconcile`): it compares the
  durable stream against the DB by `event_id` — `db_only` ids are expected during the
  shadow phase; any `stream_only` id is an integrity violation. A clean run is the
  evidence required before ever treating the stream as the source of truth. If you
  rename an agent's `output_topic` away from the built-in domain topics, the shadow
  skips that agent and logs a single warning (naming the fix) rather than silently
  losing every write — widen the domain topic list if the rename is intentional.

## 8. Keeping the system disk safe

Retention protects `$ORPHEUS_DATA_ROOT`. This section is about the *other*
disk — the one holding the operating system, `/var/log`, and the journal. A
station has been lost this way: one service logged hard enough to fill the root
filesystem, and when a Linux box runs out of root disk it does not degrade, it
stops. Networking included.

### What Orpheus bounds by default

- **Every shipped unit carries a log rate limit** (`LogRateLimitBurst=500` per
  30s). systemd's own default is 10,000 messages per 30s per service, which is
  enough for a single stuck agent to emit gigabytes a day. 500/30s is roughly a
  hundred times the busiest agent's normal rate, so ordinary operation and a
  crash-loop traceback both pass through untouched. When the limit does engage,
  journald records `Suppressed N messages from <unit>` — a flood shows up as a
  flood rather than as silence.
- **Every unit names itself** (`SyslogIdentifier=`). Without it our agents reach
  syslog as an anonymous `python`, and the first question during an incident —
  *which* service is shouting — has no answer.
- **Container logs are capped** at 20 MB × 3 files per service in both compose
  files. Docker's default `json-file` driver is unbounded.
- **`make dev-stack` trims its own log files** at 50 MB, keeping the most recent
  lines. Development only; the deployed services log to the journal.

### What Orpheus does *not* bound, and why

The journal is mirrored into `/var/log/syslog` by rsyslog on Debian-family
systems. That file is bounded by logrotate's *schedule*, not by size: between
rotations it grows without limit, and a skipped rotation turns hours of slack
into days. Orpheus does not change that by default, because rewriting a host's
logging policy is not a package's decision to make.

There is a second trap worth knowing about even if you change nothing. If
`/var/log/journal` does not exist, systemd keeps the journal in RAM — so it is
erased on every reboot, *and* any `SystemMaxUse` you configured is inert
because nothing is being written to disk. A station in that state cannot tell
you what happened before a crash, which is precisely when you want to know.
`make verify-deploy` reports it.

### Opting in

```bash
make install-log-bounds
```

This writes `/etc/systemd/journald.conf.d/10-orpheus.conf` and restarts
journald. It makes the journal persistent first (so the size cap becomes real
and survives a reboot), caps it at 1 GB, and then turns off the syslog mirror —
in that order, because switching off the mirror while the journal is in RAM
would leave logs nowhere durable at all.

It is host-wide, not scoped to Orpheus, which is why nothing installs it for
you. To undo:

```bash
sudo rm /etc/systemd/journald.conf.d/10-orpheus.conf
sudo systemctl restart systemd-journald
```

**If you rely on `/var/log/syslog`** — you ship it to a collector, or your own
tooling reads it — do not use this. Bound your rotation by size instead:

```bash
sudo sed -i 's/^\(\s*\)daily$/\1daily\n\1maxsize 100M/' /etc/logrotate.d/rsyslog
```

`make verify-deploy` reports root-filesystem headroom, whether the installed
units actually carry rate limits, whether the journal is persistent, and
whether the drop-in is present — naming the command when it is not. It warns;
it will not refuse to run because you declined.

## 9. Troubleshooting

- [Gotchas](../agent-instructions/99-gotchas.md) — the field-tested traps.
- [Audio output](audio-output.md) — the speaker never connects, drops, or
  plays nothing; capture-interface conflicts.
- [Kiosk display](kiosk.md) — the optional always-on screen: opening it from
  any browser, URL settings, where to run it and what that costs.
- [Version compatibility matrix](../version-compat-matrix.md).

---

### How to extend this manual

When you ship an operator-facing feature, add a subsection under the matching
heading above (or a new top-level heading if it's a new capability), with: what it
does, the config/flags that turn it on (default state), the `make`/CLI commands, and
the rollback. Link the design doc/ADR rather than duplicating it. Keep it concrete
enough to follow cold at 2am.
