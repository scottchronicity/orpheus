# Runbook — rolling back on the Jetson

Three escalation levels. Because everything in a flywheel batch is additive and
flag-gated, Level 1 solves feature-level problems and Level 2 solves deploy-level
problems; Level 3 (data restore) exists for disasters and should never be reached
via a normal deploy.

## Level 1 — a NEW FEATURE misbehaves (seconds, no redeploy)

Every new behavior sits behind an off-by-default flag. Turn the one flag back off
in `/opt/orpheus/config/orpheus.yaml` and restart the owning service:

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
make services-restart                          # or restart just the owning unit
```

> **Note on the transport:** there is no "roll back to MQTT" — NATS is the
> transport now. A broker-level problem is a *deploy* problem: roll back to the
> pre-deploy tag (Level 2), which restores the old code and its old transport.

## Level 2 — the DEPLOY itself is bad (minutes)

Return to the tagged last-known-good and reinstall. If you don't remember the
batch name, use the floating tag or list them.

**Do this in the git checkout, not in `/opt/orpheus`.** `/opt` is an rsync deploy tree
with no git metadata: `cd /opt/orpheus && git checkout` fails with `fatal: not a git
repository`, which is a bad thing to discover at 2am. The checkout is where you cloned
— `~/runtime/orpheus` per the [installation guide](../INSTALLATION.md) — and the make
targets install from there into `/opt`.

```bash
cd ~/runtime/orpheus                           # your clone; NOT /opt/orpheus
sudo systemctl stop orpheus-storage-sweep.timer  # the only unit that deletes data;
                                               # services-stop does not touch it
make services-stop                             # same quiesce as the rollout §3 — do not
                                               # swap code under live writers. NB: this
                                               # also stops orpheus-backplane;
                                               # services-install restarts it.
git tag -l 'flywheel/*/pre-deploy'             # or just use orpheus/last-known-good
git checkout orpheus/last-known-good           # (or flywheel/<batch-name>/pre-deploy)
make services-install                          # in case the bad deploy added units
make update-services
make verify-deploy
sudo systemctl start orpheus-storage-sweep.timer   # re-arm the deleter
```

**No database work is needed.** The schema contract is additive-only: the old
binary reads the new DB untouched (new columns are ignored, new tables never
referenced). This is verified per-batch by the reversibility review gate.

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
# (sqlite3 .recover, .dump, per-table SELECTs). This is your only copy of
# everything recorded since the backup.
STAMP=$(date +%Y%m%d-%H%M)
sudo cp -a /data/orpheus/detections/orpheus.db "/data/orpheus/detections/orpheus.db.corrupt-$STAMP"
sudo cp -a /data/orpheus/detections/orpheus.db-wal "/data/orpheus/detections/orpheus.db-wal.corrupt-$STAMP" 2>/dev/null || true

# Remove stale WAL/SHM sidecars BEFORE copying: if the previous run died
# uncleanly (the Level-3 scenario), SQLite would replay a leftover -wal into
# the restored file on next open — the classic restore-corruption vector.
sudo rm -f /data/orpheus/detections/orpheus.db-wal /data/orpheus/detections/orpheus.db-shm
sudo cp /data/orpheus/backups/<stamp>/orpheus.db /data/orpheus/detections/orpheus.db
# (+ any other .db you need from the same backup dir — remove ITS
#  <name>.db-wal / <name>.db-shm sidecars first, same reason)
sudo chown orpheus:orpheus /data/orpheus/detections/orpheus.db   # cp made it root-owned
sudo ls -l /data/orpheus/detections/orpheus.db                   # confirm before starting
make services-start
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
