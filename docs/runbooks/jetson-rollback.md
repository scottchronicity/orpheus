# Runbook — rolling back on the Jetson

Three escalation levels. Because everything in a flywheel batch is additive and
flag-gated, Level 1 solves feature-level problems and Level 2 solves deploy-level
problems; Level 3 (data restore) exists for disasters and should never be reached
via a normal deploy.

## Level 1 — a NEW FEATURE misbehaves (seconds, no redeploy)

When a feature is controlled by a flag, change only that setting in
`/opt/orpheus/config/orpheus.yaml` and restart only its owning unit. Do not use the
root `services-restart` target for this stack: it also stops and starts the managed
audio-output service and can interrupt playback or alter audio routing.

| Feature | Flag to turn off | Restart |
|---|---|---|
| Corollary discharge (self-playback tagging) | `corollary_discharge.enabled` | event-correlator |
| Late-arrival enrichment | `correlation.late_enrichment.enabled` | event-correlator |
| Weather ingestion + entity weather join | `weather.enabled` | correlator (+ stop the weather poller if scheduled) |
| Event-sourcing shadow | `event_sourcing.shadow_publish_enabled` | detection agents |
| KV presence | `event_bus.presence_enabled` | all agents |
| Health-KV dual-write / serving | `event_bus.health_kv_enabled`, `ui.health_source: bus` | agents / UI |
| UI reads from replica | `ui.read_from_replica` | UI |
| API rate limiting / query budget | `ui.rate_limit_enabled`, `ui.query_timeout_seconds: 0` | UI |
| Per-agent tick override | remove the `agents.<name>:` entry | that agent |
| Entity-type routed topics | `correlation.publish_entity_type_topics` | event-correlator |

```bash
sudo nano /opt/orpheus/config/orpheus.yaml    # flip the one flag
sudo systemctl restart orpheus-agent-event-correlator.service  # corollary discharge example
```

> **Note on the transport:** there is no "roll back to MQTT" — NATS is the
> transport now. A broker-level problem is a *deploy* problem: roll back to the
> pre-deploy tag (Level 2), which restores the old code and its old transport.

## Level 2 — the DEPLOY itself is bad

There is no safe one-line rollback for a release that changes transports, Python
runtimes, model providers, or audio ownership. The old Git commit alone does not
restore replaced virtual environments, systemd units, the output-manager host
transaction, or NATS's file store. The exact pre-deploy combination must have been
captured in the station's rollout record. If it was not, do not run aggregate
`services-install`, `update-services`, `services-start`, or `services-restart` as a
guess; stop and plan a controlled recovery from the current inventory.

Before starting, confirm the rollback record includes all of the following:

- the pre-deploy source commit, active/enabled unit states, unit files and effective
  Orpheus configuration (including environment overrides);
- the prior Python interpreter path/version and dependencies for each service whose
  environment was replaced, or a verified copy of each old venv;
- the prior BirdNET ONNX Runtime package/provider and PANNs worker artifacts;
- the prior audio-output manager/legacy Bluetooth units, PulseAudio masks, lingering
  state, playback drop-in, and `/var/lib/orpheus-audio-output` change record;
- the prior broker implementation/version/config and a consistent JetStream store
  copy if NATS was in use. JetStream state is at
  `/var/lib/orpheus/backplane/jetstream`, outside `$ORPHEUS_DATA_ROOT`.

If any item is absent, rollback to the exact old service combination is unproven.
Do not proceed with a deployment that lacks these rollback artifacts.

For a prepared rollback, use the [cold cutover](jetson-rollout.md#the-cold-cutover-for-transport-swaps-and-schema-changes)
and tailor every component restore to the captured inventory:

1. Stop the storage timer, all Orpheus services, and GPS. Keep the services stopped
   while changing code or venvs. Preserve a copy of the current post-deploy database,
   configuration and NATS store before restoring anything.
2. Check out the recorded pre-deploy commit in the runtime checkout, never in
   `/opt/orpheus`. Do not force-reset or discard local operator changes.
3. Restore or recreate each component environment with the recorded interpreter
   and dependencies. Verify imports before starting that component. Do not replace
   the PANNs Python 3.8 NVIDIA environment unless the inventory says it changed.
4. Restore the broker implementation and configuration recorded before deployment.
   If returning to NATS, use its preserved file store only with a compatible server
   version. If returning to another broker, retain the NATS copy; there is no
   automatic cross-broker replay or conversion.
5. Restore the recorded audio configuration and ownership. If the new manager's
   transaction is recorded and rollback is required, use its own rollback procedure
   from the matching checkout. Do not manually unmask or start stock PulseAudio;
   first verify capture isolation. Start audio output only after that gate passes,
   then playback and recording agents in the rollout's staged order.
6. Start NATS/backplane first, then GPS and light agents, then model agents one at a
   time, then the correlator and UI. Confirm recording continuity, audio routing,
   provider/runtime health and NATS connectivity. Re-arm the storage timer only
   after the system passes those checks.

The SQLite schema is additive, but that alone does not prove the whole deployment
can be rolled back. Preserve the pre-deploy DB backup and the NATS file-store copy;
restore either only when the recorded failure requires it and its matching service
state is stopped.

## Level 3 — data disaster (should never follow from a deploy)

Only for corruption/operator error, not for rollback.

The whole procedure is privileged: `/data/orpheus` belongs to `orpheus:orpheus` and
the agents run as `User=orpheus`. Restore the file **and its ownership** — a
root-owned `orpheus.db` is the worst outcome here, because `make services-start`
reports success while every agent fails on `attempt to write a readonly database`.

```bash
sudo systemctl stop 'orpheus-*'

# Preserve the suspect DB before overwriting it. You are here because the live
# database is bad — and a corrupt SQLite file is usually still partly readable
# (sqlite3 .recover, .dump, per-table SELECTs; JetPack has no sqlite3 CLI, so
# do that on another machine). This is your only copy of everything recorded
# since the backup.
STAMP=$(date +%Y%m%d-%H%M)
sudo cp -a /data/orpheus/detections/orpheus.db "/data/orpheus/detections/orpheus.db.corrupt-$STAMP"
sudo cp -a /data/orpheus/detections/orpheus.db-wal "/data/orpheus/detections/orpheus.db-wal.corrupt-$STAMP" 2>/dev/null || true

# Prove the backup is intact before it replaces anything: every file's sha256
# against SHA256SUMS, and integrity_check on every database
# (backups made by `make backup-databases`).
make verify-backup BACKUP=/data/orpheus/backups/<stamp>

# Remove stale WAL/SHM sidecars BEFORE copying: if the previous run died
# uncleanly (the Level-3 scenario), SQLite would replay a leftover -wal into
# the restored file on next open — the classic restore-corruption vector.
sudo rm -f /data/orpheus/detections/orpheus.db-wal /data/orpheus/detections/orpheus.db-shm
sudo cp /data/orpheus/backups/<stamp>/orpheus.db /data/orpheus/detections/orpheus.db
# (+ any other .db you need from the same backup dir — remove ITS
#  <name>.db-wal / <name>.db-shm sidecars first, same reason)
sudo chown orpheus:orpheus /data/orpheus/detections/orpheus.db   # cp made it root-owned
sudo ls -l /data/orpheus/detections/orpheus.db                   # confirm before starting
# Do not use make services-start here. Follow Level 2's staged startup after
# confirming NATS and audio capture isolation; re-arm the storage timer last.
```

Then confirm an agent can actually write, rather than trusting the unit states:

```bash
make status-all
journalctl -u "orpheus-*" --since -2m | grep -i "readonly database"   # expect nothing
```

Note: restoring loses detections recorded after the backup. Exhaust Levels 1–2 first.

## After any rollback

Open an issue describing what happened so the next batch
fixes the cause, and leave the pre-deploy tag in place until a later deploy succeeds.
