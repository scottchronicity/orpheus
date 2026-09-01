# What's new

Everything in the current unreleased line, for operators and contributors — the same set the
[changelog](changelog.md) records in short form. Features marked **off by default**
change nothing until you turn them on in `config/orpheus.yaml`; the rest are simply
how Orpheus works now. Anything marked ***stubbed*** is scaffolding — the code is
present and the switch exists, but the working part is not written yet, and the issue
that tracks finishing it is named alongside. Search this page for *stubbed* to see
all of them.

If you are upgrading an existing install, read the
[Jetson rollout runbook](runbooks/jetson-rollout.md) first — the messaging
backplane changed, and that is the one step with an ordering requirement.

---

## Messaging backplane

Orpheus components talk to each other over an **event bus**. The bus is now an
abstraction with two interchangeable backends, and the default is NATS with
JetStream.

| What | Detail |
|---|---|
| **NATS + JetStream is the default broker** | One small binary provides pub/sub, durable streams, and a key/value store. Installed and supervised by the `orpheus-backplane` service (`make install-backbone`). See [the backplane](operator-manual/index.md#4-the-backplane-messaging). |
| **Mosquitto/MQTT still works** | Set `event_bus.backend: "mqtt"` to fall back. Nothing else in your config changes. |
| **Agents survive a cold broker** | An agent started before the broker comes up no longer crash-loops: it starts disconnected and attaches when the broker appears. `event_bus.connect_required: true` restores hard-fail behavior. |
| **Remote brokers / multiple hosts** | `event_bus.nats_url` points anywhere, so agents, UI, and broker can live on different machines. See the [distributed runbooks](runbooks/distributed-backbone-on-nuc.md). |
| **Agent presence** — *off by default* | `event_bus.presence_enabled: true` makes every agent announce itself continuously, so the dashboard can show who is alive right now. See [Agent presence](user-guide/index.md#agent-presence). |
| **Health over key/value** — *off by default* | `event_bus.health_kv_enabled` mirrors agent health into a KV plane; `ui.health_source` selects which plane the dashboard reads. A migration seam — see [health sources](operator-manual/index.md#6-health-monitoring-observability). |
| **Durable event log** — *off by default* | `event_sourcing.shadow_publish_enabled` also writes detections to a bounded JetStream stream. SQLite stays the source of truth. |
| **Config over the bus** — *off by default* | `config_service.enabled` reads shared configuration from the broker's KV store so multi-host installs stop copying identical YAML. |

## Detection & classification

| What | Detail |
|---|---|
| **Audio-events agent (PANNs)** | A general sound classifier covering AudioSet's 527 classes — dogs, vehicles, speech, rain, sirens — alongside the bird specialists. Its output has its own dashboard page. See the [User Guide](user-guide/index.md) for the Audio Events page. |
| **Cross-classifier entities** | Detections from different classifiers that describe the same real animal collapse into one **entity** instead of three rows. See the [User Guide](user-guide/index.md) for the Entities page. |
| **Entity types** | Each entity carries a coarse type path such as `Animal.Bird.Crow`. Publishing per-type bus topics is off by default (`correlation.publish_entity_type_topics`). |
| **Automatic equivalence discovery** — *on by default* | A background scan proposes "BirdNET's X is the same animal as PANNs' Y" from co-occurrence, auto-accepting the obvious ones and queueing the rest for your approval on the [Equivalences page](user-guide/index.md#equivalences-teaching-orpheus-that-two-labels-mean-one-animal). |
| **Geographic plausibility filter** | BirdNET species wildly out of range for your location and season are suppressed, with a deliberate weak-admit path so a rare-but-real visitor can still surface. Tunable via `detection.geo_filter_*`. |
| **Corollary discharge** — *off by default* | With `corollary_discharge.enabled` (a top-level key, not under `correlation:`), entities that overlap Orpheus's own audio playback are tagged `is_self_generated` rather than dropped, so the system doesn't record itself as wildlife. |
| **Late-arrival enrichment** — *off by default* | With `correlation.late_enrichment.enabled`, a classifier that reports after its cluster closed still attaches to the right entity instead of creating a duplicate. |
| **Latent state-space memory** — *off by default*, consumer *stubbed* | `correlation.state_space_memory_enabled` has the correlator record what was present at this site, at this hour. Nothing reads it back: enabling it collects history, it does not change correlation. Tracked as *Act on the latent memory — an active-inference consumer*. |

## Dashboard

| What | Detail |
|---|---|
| **Audio Events page** | Browse and filter the non-bird soundscape by AudioSet label. |
| **Equivalences page** | Review, accept, or reject proposed cross-classifier equivalences, and see when the discovery scan last ran. |
| **Entity type chips and self-generated tags** | Visible on entity rows. |
| **Diagnostics page** | Correlator health (including chain-completion latency), storage trend, a cross-agent error feed, agent presence, audio system health, and a service log viewer. |
| **Weather card** — *stubbed* | The card, the database table, and the `orpheus-weather` ingestor are in place, but the Ecowitt field mapping is unimplemented: the provider raises on every parse, so the ingestor exits on its first poll and no reading reaches the card. Tracked as *Finish the weather integration — real gateway parsing and a dashboard card*. |
| **External species links** | Detections link out to iNaturalist, Wikipedia, and GBIF (AudioSet for sound labels). |
| **Graceful expired clips** | A detection whose media has rolled off retention shows a "clip expired" state instead of an error. |
| **Time-of-day filtering, pagination, refetch indicator** | Shared across the Birds, Crows, Audio Events, and Entities pages. |

## Running & operating

| What | Detail |
|---|---|
| **Post-upgrade verification** | `make verify-deploy` checks every component's install, service state, models, and that the database still reads. |
| **Safer upgrades** | `make update-services` now stops on the first failure instead of reporting success; the [rollout runbook](runbooks/jetson-rollout.md) documents the stop-swap-start procedure used in production. |
| **One component owns retention** | `orpheus-storage-sweep` is now the only thing that deletes a recording — a one-shot on a 15-minute timer, installed with the platform library. No agent trims its own directory any more, which is what lets one component weigh every category against the single filesystem they share. Timelapses, which nothing used to clean at all, are covered like everything else. See [Data & retention](operator-manual/index.md#7-data-retention). |
| **Ceilings, pressure, and floors** | Each category in `storage.retention.categories` has a **ceiling** (`max_gb`, enforced whether or not the disk is under pressure) and a **floor** (`floor_days`, never deleted for any reason). Separately, when free space falls below `reserve_gb` (default `100`) every category above its floor gives up data in proportion to what it has to give, so one kind of recording does not carry the whole cost of a filling disk. When a ceiling and a floor contradict each other the floor wins: the sweep logs at CRITICAL and stops rather than deleting your recent history. Defaults: audio 600 GiB / 30 days, motion video 60 GiB / 90 days, snapshots 450 GiB / 90 days, timelapses 450 GiB / 90 days. Every `*_gb` key is GiB, the same unit the dashboard and `make storage-report` show. Note that `min_free_space_percent` also ships set (10), and on a disk larger than about a terabyte it is the stricter of the two reserves, so it — not `reserve_gb` — is what the sweep holds free. |
| **See it before it acts** | `make storage-report` decides exactly what a real sweep would and deletes nothing, printing a per-category table of size, ceiling, floor, and the action it would take. The first sweep after an install is report-only for `first_run_grace_hours` (default 24), so the numbers are reviewable before anything is removed. Every sweep that deletes writes a CSV manifest of exactly which files went. `sudo systemctl disable --now orpheus-storage-sweep.timer` or `storage.retention.sweep_enabled: false` stops all deletion. |
| **Row retention** — *stubbed* | `storage.retention.detections_days` is accepted and nothing applies it, so detection history grows unbounded. Tracked as *Enforce detections_days — retention for database rows*. |
| **Host log bounds** | Every shipped unit now carries a log rate limit (`LogRateLimitBurst=500`/30s against systemd's default of 10,000) and names itself in syslog, so one stuck service cannot emit gigabytes a day and an operator can tell which one is shouting. Container logs are capped at 20 MB × 3 per service, and `make dev-stack` trims its own log files. What is *not* bounded by default is the journal's mirror into `/var/log/syslog`, which logrotate bounds by schedule rather than size — `make install-log-bounds` opts into a persistent, capped journal with the mirror off, and `make verify-deploy` reports root-filesystem headroom and warns when you have not. See [Keeping the system disk safe](operator-manual/index.md#8-keeping-the-system-disk-safe). |
| **Per-agent tick rates** | The optional `agents:` block tunes the heartbeat cadence of any agent built on the actor base — every one except the video snapshotter and video timelapser, which have no heartbeat. A block naming one of those two parses without error and has no effect. |
| **Read-only mirror** — *off by default*, service *stubbed* | `orpheus-mirror` publishes a consistent snapshot of the database to another host on demand, so heavy dashboard reads never contend with live writes; `ui.read_from_replica` points a UI at that copy. The CLI works; no service unit ships, so running it on a schedule is your own supervisor's or cron's job and `mirror.enabled` only gates a future one. Tracked as *Read-only mirror host: serving stack + public portal*. |
| **Public projection** — *off by default* | `public.enabled` exposes a privacy-preserving view: time bucketed to the day, location as a site label, never a coordinate. |
| **API rate limiting and query budgets** — *off by default* | `ui.rate_limit_enabled` and `ui.query_timeout_seconds` harden a UI exposed beyond your LAN. |
| **OpenTelemetry** — *stubbed* | The tracing module and its optional dependencies ship, and `telemetry.enabled` accepts a console, OTLP, Jaeger, or Tempo backend — but nothing calls `setup_tracing` and no component creates a span, so enabling it produces no output. Tracked as *OpenTelemetry (OTel) Migration*. |
| **Deployment manifests from config** | `make manifests` generates systemd or docker-compose topology from `orpheus.yaml`, so what runs matches what is configured. |
| **Model provisioning** | `make check-models` and `make download-models` verify and fetch the ML checkpoints. |
| **One-time data backfills** | `make backfill-root-event-ids` and `make backfill-entity-types` upgrade historical rows; both have `-dry-run` variants. |

## Development & testing

| What | Detail |
|---|---|
| **Simulacrum** | `make sim-up` runs the whole collective in containers with a synthetic source — no hardware required. `make sim-fleet-up` adds the real models and `make sim-validate` asserts a real audio clip drives the full cascade. |
| **Dev stack** | `make dev-stack` runs every component as a background process on a laptop, with `dev-status`, `dev-logs`, `dev-stop`. |
| **Behavior tests** | `make test-bdd` runs the correlator scenarios; `make test-bash` covers the shell tooling. |
| **Repo guardrails** | `make guardrails` fails the build when a new agent is half-wired or a doc is missing from the site nav. |
| **Documentation site** | `make docs-serve` previews this site; `make docs-build` is the strict build, which fails on a nav entry pointing at a page that does not exist. In-page links are not validated — many of them deliberately point at source files outside the site. |

---

## Upgrade notes

1. **Install the backplane before restarting agents.** Agents restarted against a
   broker that isn't up will sit disconnected until it appears.
2. **Run `make storage-report` after the upgrade.** `orpheus-storage-sweep` takes
   over every deletion under `$ORPHEUS_DATA_ROOT` and the agents stop deleting, so
   categories that were never trimmed before — timelapses in particular — now have
   a ceiling. The first sweep after the timer is installed is report-only for 24
   hours; that window is when to disagree with the numbers. Confirm the timer with
   `systemctl status orpheus-storage-sweep.timer` (its one-shot `.service` is idle
   between runs, which is correct). `raw_audio_days`, `raw_video_days`,
   `max_size_gb`, `cleanup_trigger_percent`, `cleanup_amount_percent` and
   `check_interval_hours` still parse but no longer do anything; `floor_days` and
   `max_gb` replaced them. `detections_days` is still not applied to database rows.
3. **The first start after upgrading may pause for seconds to minutes** while the
   database builds indexes over existing detections. It logs that it is doing so.
4. **Everything else is additive.** New configuration keys have defaults, new
   database columns are additive, and the previous release can still read the
   upgraded database.

