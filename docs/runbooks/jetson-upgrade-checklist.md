# Jetson upgrade — one page

The whole rollout on one screen. Each step links to detail in the
[rollout](jetson-rollout.md) / [rollback](jetson-rollback.md) runbooks. NATS is the
transport now — installing it is part of the upgrade, not optional.

## Before you touch the Jetson

- [ ] **Rehearse on the laptop** against its own populated database —
      [laptop verification §5](laptop-verification.md). Data-read smoke and the
      dashboard must both be green before the station is touched.

## On the Jetson — in this order

**Fill these in first.** The rest of the page uses them. Do not paste the whole
page at once: the placeholders below are not optional, and in bash a bare `<name>`
is a redirect, so a wholesale paste silently skips the tagging and deploys anyway
— leaving a restarted station with no rollback tag.

```bash
export ORPHEUS_SRC=~/runtime/orpheus; cd "$ORPHEUS_SRC"

BATCH=            # a name for this upgrade, e.g. flywheel_2
TARGET=           # the branch or merge commit you are deploying
DEPLOYED=         # the commit running NOW — from `make show-deployed`, not HEAD.
                  # On a normal box show-deployed prints no commit (rsync tree, no
                  # git metadata); use the tag or note from your last upgrade.
```

### - [ ] 0. Know where you are

Write this into your rollback note.

```bash
make show-deployed                 # deployed commit + orpheus-common version
make verify-deploy                 # baseline: must be GREEN before you change anything
```

### - [ ] 1. Safety net

`/data/orpheus` is orpheus-owned — sudo throughout.

```bash
BACKUP=/data/orpheus/backups/$(date +%Y%m%d-%H%M); sudo mkdir -p "$BACKUP"
sudo sqlite3 /data/orpheus/detections/orpheus.db "VACUUM INTO '$BACKUP/orpheus.db'"
for db in /data/orpheus/*.db; do [ -f "$db" ] && sudo sqlite3 "$db" "VACUUM INTO '$BACKUP/$(basename "$db")'"; done
sudo cp /opt/orpheus/config/orpheus.yaml "$BACKUP/"
sudo cp /opt/orpheus/config/.env "$BACKUP/.env" 2>/dev/null || true   # backbone URL, and its
                                                 # credentials on an auth-gated broker; absent
                                                 # on a single-host install
grep -A30 'retention:' /opt/orpheus/config/orpheus.yaml  # ceilings + floors the sweep will enforce
make storage-report                                      # what the sweep would delete — deletes nothing
sudo ls -l "$BACKUP"    # eyeball it: a backup you did not confirm is not a backup
```

Tag the commit that is running now, so there is something to roll back to:

```bash
git tag "flywheel/$BATCH/pre-deploy" "$DEPLOYED"
git tag -f orpheus/last-known-good "$DEPLOYED"
```

### - [ ] 2. Deploy

Order matters.

```bash
sudo systemctl stop orpheus-storage-sweep.timer  # the ONLY unit that deletes data, and
                                               # services-stop does not touch it. Left armed
                                               # it fires every 15 minutes, mid-deploy.
make services-stop                             # quiesce writers; they restart in update-services below
git fetch origin && git checkout "$TARGET"
make install-backbone                          # NATS FIRST
systemctl is-active orpheus-backplane.service  # confirm broker up BEFORE agents
make services-install                          # installs NEW agents + refreshes units
make update-services                           # updates + restarts everything
make verify-deploy                             # imports + units + broker + DATA-READ — all ✅
#   ^ first start may pause minutes building indices on a big DB. Expected, not a hang.
sudo systemctl start orpheus-storage-sweep.timer  # re-arm the deleter
```

### - [ ] 3. Is it working?

```bash
make status-all                                # every unit active
journalctl -u "orpheus-*" --since -10m | grep -iE "error|traceback"   # nothing new
systemctl status orpheus-storage-sweep.timer   # ACTIVE. Its .service is a one-shot and is
                                               # 'inactive (dead)' between runs — that is correct.
make storage-report                            # the sweep's table should look sane: the ceilings
                                               # and floors you expect, and no surprise deletions
#   Dashboard green; detections flowing; entities appear on real sound.
```

**Retention needs one look, once.** `orpheus-storage-sweep` owns every deletion
under `/data/orpheus`; no agent trims its own directory. For 24 hours after the
timer is first installed it is report-only — it says what it would delete and
deletes nothing — so if `make storage-report` shows it removing something you did
not expect, fix the ceiling in `storage.retention` before that grace expires.
`make storage-sweep ARGS=--force` starts enforcement early — it resolves the console
script in the deployed venv, which is not on your PATH; `sudo systemctl disable
--now orpheus-storage-sweep.timer` stops it entirely.

## New features (optional, later)

Only after a clean default soak, flip flags one at a time —
[what's-new testing tour](whats-new-testing-tour.md).

## If something's wrong — [rollback](jetson-rollback.md)

| Symptom | Action | Time |
|---|---|---|
| A new feature misbehaves | flip its one flag off + restart the owning unit | seconds |
| The deploy itself is bad | `cd "$ORPHEUS_SRC" && git checkout orpheus/last-known-good && make services-install && make update-services && make verify-deploy` | minutes |
| Data corruption (rare) | Level 3 restore — stop writers, `rm` the `-wal`/`-shm` sidecars, `sudo cp` the backup back, then `sudo chown orpheus:orpheus` it | — |

There is no "roll back the transport" — NATS is the transport; a broker problem is a
deploy problem, so you roll back to the tag (which restores the old code + its transport).
