# Changelog

All notable changes to Orpheus are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

For a reader-facing tour of what changed and how to turn each thing on, see
[What's new](docs/whats-new.md). Individual components carry their own
`CHANGELOG.md` and `VERSION` alongside their `pyproject.toml`; this file is the
repository-wide record.

## [0.4.0] - 2026-09-01

The summer update. Everything here is additive and backwards compatible: a
previous release reads a database this one has opened, and a configuration file
written for the previous release parses unchanged.

### Added

#### Messaging backplane

- **NATS + JetStream as the default broker**, installed and supervised by the
  `orpheus-backplane` service (`make install-backbone`). One binary provides
  pub/sub, durable streams, and a key/value store.
- **An `EventBus` abstraction** with `create_event_bus()`; no component
  constructs a broker client directly. Mosquitto remains a one-line fallback via
  `event_bus.backend: "mqtt"`.
- **JetStream surfaces on the bus** — request/reply, key/value, and durable
  streams — plus NATS parity for the MQTT behaviors that had no direct analogue:
  key/value-TTL presence in place of last-will, and retain-as-last-value.
- **Cold-broker resilience.** An agent started before the broker is up begins
  disconnected and attaches when the broker appears, rather than crash-looping.
  `event_bus.connect_required: true` restores hard-fail behavior; the default is
  derived from whether the broker URL is loopback.
- **Multi-host deployment.** `make install-host` and `make install-backbone`
  install a per-host subset; bus-client units read `/opt/orpheus/config/.env` for
  a per-host broker URL; opening a non-loopback listener requires an auth file.
- **Configuration over the bus** — *off by default*. `config_service.enabled`
  reads shared configuration from the broker's key/value store, so multi-host
  installs stop copying identical YAML. `orpheus-config push` is the single write
  authority.

#### Agent substrate

- **An `Actor` base** composing the agent lifecycle — bus connection,
  subscriptions, heartbeat, signal handling, shutdown, statistics — with
  `on_started`/`on_stopping` hooks. The crow, correlator, bird, and audio-events
  agents run on it.
- **An injectable `Clock` and `PeriodicTask`**, so tick-driven behavior is
  testable without wall-clock waits.
- **Per-instance identity.** `ORPHEUS_AGENT_INSTANCE_ID` from the deployment
  environment lets one agent run as several instances with no per-agent code.
- **Per-agent tick rates.** The optional `agents:` block tunes the heartbeat
  cadence of any agent built on the actor base — every one except the video
  snapshotter and video timelapser, which have no heartbeat.

#### Detection and correlation

- **An audio-events agent (PANNs)** covering the whole AudioSet ontology
  alongside the bird specialists, with bounded concurrent clip processing and a
  shared GPU-or-CPU device policy.
- **Cross-classifier identity.** Detections carry a chain root, so several
  classifiers describing one animal produce one entity with all the evidence
  attached, correlated by shared source rather than by co-occurrence.
- **An entity-type taxonomy** — a data-driven registry deriving a coarse path
  such as `Animal.Bird.Crow`, an additive `entity_type` column, a migration for
  legacy rows, and off-by-default per-type bus topics.
- **Automatic equivalence discovery** — *on by default*. A background scan
  proposes that one classifier's label and another's mean the same animal,
  auto-accepts above a threshold, and queues the rest for review. Guarded against
  proposing equivalences within a single namespace.
- **Corollary discharge** — *off by default*. The playback agent publishes
  playback windows; entities overlapping them are tagged `is_self_generated`
  rather than dropped, so the system does not record itself as wildlife.
- **Late-arrival enrichment** — *off by default*. A classifier reporting after
  its cluster closed attaches to the right entity instead of creating a duplicate.
- **Latent state-space memory** — *off by default*, consumer stubbed. The
  correlator records what was present at this site at this hour; nothing reads it
  back yet.
- **A geographic plausibility filter** for BirdNET, with a site whitelist and a
  soft-admit path so a rare-but-real visitor can still surface.
- **Weather-station ingestion** — *stubbed*. The ingestor, database table,
  correlator context join, and dashboard card exist; the Ecowitt field mapping is
  unimplemented, so the ingestor exits on its first poll.

#### Dashboard

- **New pages**: Entities, Audio Events, Equivalences, and Diagnostics.
- **Diagnostics** shows correlator health including chain-completion latency, a
  per-volume storage trend with a days-until-full projection, a cross-agent error
  feed, agent presence, audio system health, and a service log viewer.
- **External species links** to iNaturalist, Wikipedia, GBIF, and AudioSet.
- **A graceful expired-clip state** for evidence whose media has rolled off
  retention, instead of a broken player.
- **Time-of-day filtering, pagination, and a refetch indicator** across Birds,
  Crows, Audio Events, and Entities, with filter state in the URL so a view is
  bookmarkable.
- **Entity-type chips and self-generated tags** on entity rows.
- **One-click guest sign-in** via a server-side endpoint, gated by
  `ui.guest_quick_login` (default on).
- **Request-timing middleware** for slow-query visibility.

#### Operations

- **`make verify-deploy`** — a read-only post-upgrade check covering component
  installs, service state, models, root-filesystem headroom, log bounds, and that
  the database still reads.
- **`orpheus-storage-sweep`** — one component that owns every deletion under the
  data root, run as a one-shot from a 15-minute systemd timer. Per-category
  ceilings (`max_gb`) are enforced regardless of free space; below
  `storage.retention.reserve_gb` every category above its floor gives up data in
  proportion to what it has to give; `floor_days` and `min_file_age_hours` are
  never breached, and a conflict between a floor and a ceiling logs CRITICAL
  rather than deleting recent recordings. `make storage-report` is a dry run, the
  first sweep after an install is report-only for 24 hours, and every sweep that
  deletes writes a CSV manifest of exactly which files went.
- **Host log bounds.** Every shipped unit carries a log rate limit
  (`LogRateLimitBurst=500`/30s against systemd's default of 10,000) and a
  `SyslogIdentifier`, so one stuck service cannot fill the disk and an operator
  can tell which one is shouting. Container logs are capped per service, and
  `make dev-stack` trims its own log files. `make install-log-bounds` opts into a
  persistent, capped journal with the syslog mirror off.
- **Deployment manifests from configuration.** `make manifests` generates systemd
  or docker-compose topology from `orpheus.yaml`.
- **Model provisioning** — `make check-models` and `make download-models`.
- **One-time backfills** for `root_event_id` and `entity_type`, both with
  `--dry-run` variants.
- **Independent per-component versioning** — a `VERSION` file per component read
  dynamically at build time, with `scripts/bump-version.sh`.
- **Runbooks** for laptop verification, Jetson rollout and rollback, distributed
  deployment, and the what's-new feature tour.

#### Observability

- **Health over key/value** — *off by default*. `event_bus.health_kv_enabled`
  mirrors agent health into a KV plane and `ui.health_source` selects which plane
  the dashboard reads, with a diff oracle for comparing them during migration.
- **Agent presence** — *off by default*. Agents announce themselves continuously
  from the heartbeat; the dashboard shows who is alive now.
- **A durable event log** — *off by default*. `event_sourcing.shadow_publish_enabled`
  also writes detections to a bounded JetStream stream, with `orpheus-reconcile`
  to compare stream against database. SQLite remains the source of truth.
- **An OpenTelemetry tracing foundation** — *stubbed*. The module and optional
  dependencies ship and the configuration is accepted, but nothing is
  instrumented, so enabling it emits nothing.
- **Per-volume storage history** with a fill-rate projection.

#### Sharing and portal

- **A read-only `DetectionDB` mode** and a read-only-replica dashboard, so heavy
  reads can be served away from the station.
- **`orpheus-mirror`** — a consistent database snapshot (`VACUUM INTO`) and
  push-only transport, as a CLI. No service unit ships, so scheduling it is your
  own supervisor's job.
- **A public projection and export** — *off by default*. A privacy chokepoint
  that buckets time to the day and reduces location to a site label, never a
  coordinate, with a provenance envelope on the export.
- **API rate limiting and per-query time budgets** — *off by default*, for a UI
  exposed beyond a LAN.

#### Testing and development

- **The Simulacrum** — the whole collective in containers, with a synthetic
  source, a replay mode that plays real clips through the system, a real-model
  fleet profile, per-service health checks, and `make sim-validate` asserting a
  real clip drives the full cascade to an entity.
- **A generated failure matrix** over agent-down, topology, and multiplicity
  scenarios, driven from a contract oracle.
- **An end-to-end BDD suite** (`make test-bdd`) and **shell tests**
  (`make test-bash`).
- **Historical event replay** (`orpheus-replay`) for detections and entities.
- **`make dev-stack`** — every component as a background process on a laptop,
  with `dev-status`, `dev-logs`, `dev-stop`.
- **A documentation site** built from `docs/`, published from the public
  repository, with `make docs-preview` serving the built site at the path it is
  published under.
- **Repository guardrails** (`make guardrails`) that fail the build when an agent
  is half-wired, a page is missing from the site navigation, or the README's
  roadmap counts drift from the ledger.
- **A dry run for the issue-board sync**, so a run can be rehearsed before it
  touches a public board.

### Changed

- **Schema migrations are additive and run on first open**, so a previous release
  still reads a database a newer one has opened. Compound and covering indices
  are built on first open of an existing database; on a large history this pauses
  startup and says so.
- **Agents no longer delete recordings.** The `_periodic_cleanup` tasks in
  audio-motion and video-motion and the inline age purge in video-snapshotter are
  removed; `orpheus-storage-sweep` covers those directories and the timelapse
  directory that nothing cleaned before. The Diagnostics storage panel reads the
  sweep's published report instead of the agents' health payloads.
  `raw_audio_days`, `raw_video_days`, `max_size_gb`, `cleanup_trigger_percent`,
  `cleanup_amount_percent`, `check_interval_hours` and
  `video_snapshotter.retention_days` are still accepted and validated so an
  existing configuration parses, but nothing applies them. `detections_days` for
  database rows remains unapplied.
- **The Entities page is served by a covering index** and samples its scatter
  server-side, and **the diagnostics history endpoints aggregate from raw rows**
  rather than building a model per row. Measured on a station holding 2.7 million
  detections: Entities 27.5s → 5.8s warm, bird-correlation 39.7s → 3.7s warm.
- **`make update-services` stops on the first failure** instead of reporting
  success, and covers every installed component rather than a subset.
- **`orpheus-mqtt` is now `orpheus-backplane`**, broker-agnostic; the unit keeps
  an `orpheus-mqtt` alias so an existing install is not orphaned.
- **`make test-all` includes every component and exits non-zero** when any suite
  fails.
- **`make dev-stop` stops the whole process tree**, not just the launch wrapper
  that spawned it.
- **The accounts database follows `ORPHEUS_DATA_ROOT`** instead of probing
  hardcoded paths; an explicit `ORPHEUS_UI_DATABASE_URL` still wins, and an
  existing database is never orphaned.
- **`ruff` is pinned exactly** rather than floored, so a linter release cannot
  turn an unchanged tree red.
- **Documentation is organized by what a reader came to do**, published as a
  site, with a comparison page, a security posture page, an AI-assisted install
  path, and a stated voice and audience for contributors.

### Fixed

- **BirdNET used softmax on multi-label logits**, collapsing simultaneous species
  to one; it now uses sigmoid and de-duplicates windows by label index.
- **Opening a pre-`root_event_id` database crashed** — an upgrade blocker.
- **Correlator health tolerates an un-migrated or read-only database** instead of
  erroring.
- **Deployment suppressed dependency resolution**, so a new platform dependency
  never reached existing component environments; the platform installer also
  omitted its `VERSION`, so `/opt` builds carried `0.0.0`.
- **`orpheus-gps` and the UI backend did not self-install**, so a deployed
  environment could not import them.
- **Schema initialization now waits out a concurrent migration** rather than
  failing after five seconds — on a large history the loser of that race was
  being restarted by systemd.
- **Audio-events dropped every corvid detection** because of a whitelist missing
  eight bird-like AudioSet labels, and did not survive a missing GPU.
- **Auto-discovery could propose same-namespace equivalences** and its test rotted
  against the wall clock.
- **The correlator gated clip-interval overlap on shared clip origin**, and its
  expiry failures are now counted and survivable rather than silently killing the
  timer.
- **UI failures surfaced as errors rather than blank charts**, the
  `dashboard.poll_interval` knob actually takes effect, a reset during compute no
  longer clobbers the bird-like cache, and a missing replica snapshot falls back
  to the live database with a warning.
- **Memory-bounded streaming** replaced materializing large windows in
  auto-discovery, reconciliation, and equivalence diagnosis.
- **The NATS bus** no longer leaves a zombie worker after an aborted connect,
  reports transport-down as a connection error rather than an attribute error,
  and its teardown outlives the drain.
- **`make sim-validate` could report success while proving nothing** — it passed
  with the classifiers stopped, and exited zero with nothing running at all.
- **`make check-models` reported no models** on a fully provisioned station,
  because it only looked for two file extensions, and named a download command
  that does not exist.
- **The end-to-end suite tested a stale bundle**, because it did not rebuild the
  frontend it drove.

### Security

- **Unauthenticated arbitrary file read via the single-page-app route.** The
  catch-all joined a raw URL path onto the static directory with no containment,
  so a bare `GET` could read any file the service user could open — including the
  environment file holding the session-signing secret.
- **Arbitrary file read under the data root via the clip endpoints.** The
  absolute-path branch checked containment against the whole data root rather
  than the clip directory, so an authenticated viewer could retrieve the accounts
  and detections databases. Both branches now contain to the channel or camera
  directory.
- **Unauthenticated account creation with a client-supplied role**, and an
  unauthenticated debug endpoint serving the broker URL with plaintext
  credentials and the site's coordinates. Both are now restricted to
  administrators.
- **The guest account was not read-only** — the role gate existed but was never
  applied, and a viewer could grant itself administrator on its own profile.
  Role is no longer settable on self-update, and the four state-changing
  endpoints require an administrator.
- **The login page displayed working credentials.** It now shows a rotation
  prompt naming the environment variables, and never a password; one-click guest
  sign-in moved to a server-side endpoint so no password ships to the browser.
- **Sign-in brute-force protection is always on**, rather than being gated behind
  the general API rate-limit switch that defaults off.
- **Secrets are fully redacted** in debug output rather than exposing a trailing
  fragment, credential-bearing URLs are redacted too, camera credentials no
  longer appear in capture logs, and session tokens no longer reach the access
  log on any launch path.

### Removed

- **Process machinery is no longer part of this repository** — the backlog
  flywheel's skills, review passes, and working notes. The work ledger
  (`docs/backlog.json`) holds outstanding work only; what shipped is recorded
  here and in [What's new](docs/whats-new.md).
- **The legacy `orpheus-dashboard` service**, superseded by the current UI, and a
  vendored third-party snapshot that nothing referenced.

### Notes

- **Age-based clip retention was implemented and then reverted** before release.
  Enforcing it would have deleted history on any station holding more than its
  configured window implies — a station keeping a year of clips under a 30-day
  setting loses eleven months on the first pass. `orpheus-storage-sweep` answers
  the same problem the other way round: `floor_days` is a window that is *never*
  deleted rather than one after which everything is, so the sweep bounds the disk
  by size and can only ever remove recordings older than the floor.
</content>
