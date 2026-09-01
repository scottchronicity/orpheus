# Runbook — rolling a big branch onto the Jetson (with backups)

Precondition: the branch passed the [laptop verification runbook](laptop-verification.md)
end-to-end on the laptop (the laptop and this Jetson are independent machines — no
data is copied between them). Everything new in this branch is **off by default**
(additive config, flag-gated behavior, additive schema), so once the transport is up
the deploy changes nothing behaviorally until you flip flags — that is the safety
property the soak verifies.

> **The one thing that is NOT "flip a flag": the transport is now NATS.**
> `event_bus.backend` defaults to `nats` (the actor-substrate roadmap pivot,
> [ADR 0017](../adr/0017-actor-model-nats-backplane.md)) and MQTT is no longer
> the transport we run. So **installing the NATS backplane is a required step of
> this upgrade, not optional** — step 3 does it *before* restarting agents,
> because agents that restart against a broker that isn't up will crash-loop
> until it is. There is no "roll back the transport" — if the deploy goes bad you
> roll back to the pre-deploy tag (§2), and the old code brings its own transport.

> **Pick your variant before you start.** §0–§5 below are the normal rolling deploy.
> If this upgrade swaps the transport or changes the schema, read
> [the cold cutover](#the-cold-cutover-for-transport-swaps-and-schema-changes) first
> and follow that instead — it stops everything before touching anything, so you find
> a bad component with the system quiet rather than half-restarted.

## 0. Know where you are (30 seconds — do this FIRST)

You can't roll back to a point you can't name. Record what's running now:

```bash
# Your git clone — NOT /opt/orpheus, which is an rsync deploy tree with no git metadata.
export ORPHEUS_SRC=~/runtime/orpheus
cd "$ORPHEUS_SRC"
DEPLOYED=$(git -C "$ORPHEUS_SRC" rev-parse HEAD)   # the checkout is the source of the
                          # deploy; /opt/orpheus has no git metadata, so show-deployed
                          # cannot give you a commit
echo "$DEPLOYED" >> ~/rollback-note.txt
make show-deployed        # cross-check: orpheus-common version + last sync should match
make verify-deploy        # baseline: confirm the box is GREEN before you change anything
```

Every step below runs from `$ORPHEUS_SRC` unless it says otherwise: the make targets
install *into* `/opt/orpheus` from the checkout, and git only works in the checkout.

Write the `show-deployed` output into your rollback note — that commit is what you tag
in §2. If `verify-deploy` is already ❌ *before* you deploy, fix that first — otherwise
you can't tell whether a post-deploy failure is new.

## 1. Backup (5 minutes, on the Jetson)

The schema contract means the OLD binary can always read the NEW database
(additive columns only), so a DB restore should never be *needed* — this backup is
belt-and-suspenders.

Everything under `/data/orpheus` belongs to `orpheus:orpheus` and everything under
`/opt/orpheus` to root, so this whole section runs under `sudo` — an unprivileged
`mkdir` into the data root just fails with permission denied.

```bash
# Quick backup: every SQLite DB + the runtime config (small, seconds)
BACKUP=/data/orpheus/backups/$(date +%Y%m%d-%H%M)
sudo mkdir -p "$BACKUP"
sudo sqlite3 /data/orpheus/detections/orpheus.db "VACUUM INTO '$BACKUP/orpheus.db'"  # consistent snapshot, no downtime
for db in /data/orpheus/*.db; do   # state_space/config/circuit_breakers/etc., if present
  [ -f "$db" ] && sudo sqlite3 "$db" "VACUUM INTO '$BACKUP/$(basename "$db")'"
done   # VACUUM INTO, not cp: a live cp of a WAL-mode DB copies a torn/stale file
sudo cp /opt/orpheus/config/orpheus.yaml "$BACKUP/orpheus.yaml"
sudo cp /opt/orpheus/config/.env "$BACKUP/.env" 2>/dev/null || true   # backbone URL, and its
                        # credentials on an auth-gated broker; absent on a single-host install
sudo ls -l "$BACKUP"    # eyeball it: a backup you did not confirm is not a backup

# Full backup (optional, if disk allows): the whole data root incl. clips
# sudo rsync -a /data/orpheus/ /some/other/disk/orpheus-backup-$(date +%Y%m%d)/
```

## 2. Tag the rollback point

Tag what is CURRENTLY running (the last known-good). Two tags: a named one for the
record, and a floating `orpheus/last-known-good` so a stressed rollback never has to
remember the batch name.

**In the checkout, never in `/opt/orpheus`.** `/opt` is an rsync deploy tree with no
git metadata — every `git` command run there fails with `fatal: not a git repository`.
`make show-deployed` confirms it by printing `(no git checkout at /opt/orpheus - rsync
deploy, no git metadata)` on a box installed per the
[installation guide](../INSTALLATION.md), which is the normal case.

Tag the commit that is currently deployed — the one you captured in §0, not
whatever HEAD happens to be in the checkout now:

```bash
cd "$ORPHEUS_SRC"
BATCH=            # a name for this upgrade, e.g. flywheel_2
# $DEPLOYED was captured in §0. In a new shell, re-read it:
#   DEPLOYED=$(tail -1 ~/rollback-note.txt)
git tag "flywheel/$BATCH/pre-deploy" "$DEPLOYED"
git tag -f orpheus/last-known-good "$DEPLOYED"   # always points at the newest pre-deploy state
```

## 3. Deploy

One pre-flight: know what the retention sweep will do while you are not watching.
`orpheus-storage-sweep` owns every deletion under `$ORPHEUS_DATA_ROOT` and runs
from a timer every 15 minutes; no agent trims its own directory. It brings each
category back to its `max_gb` ceiling oldest-first, takes proportionally from
every category above its `floor_days` floor when free space is under
`reserve_gb`, and never deletes inside a floor. Confirm the values you are
deploying against, and ask the sweep itself what it would remove:

```bash
sed -n '/^  retention:/,/^  [a-z]/p' /opt/orpheus/config/orpheus.yaml   # the whole block:
                                                       # reserve, grace, every ceiling + floor
df -h /data                                            # free space against reserve_gb
make storage-report                                    # per-category table; deletes nothing
```

If this is the first deploy that installs the timer, the first real sweep is
report-only for `first_run_grace_hours` (default 24) — it writes the report, logs
at CRITICAL if it would have removed anything, and deletes nothing. That window
is when to disagree with the ceilings.

Deleted clips are **not** in the §1 quick backup (only the optional full rsync
saves them, and a rollback does not bring them back), so if `storage-report`
shows a category the sweep would trim and those clips matter, take the full rsync
first.

Run this from the runtime checkout (`$ORPHEUS_SRC` from §2) — the make targets rsync
into `/opt/orpheus` from there.

```bash
cd "$ORPHEUS_SRC"
sudo systemctl stop orpheus-storage-sweep.timer   # the ONLY unit that deletes data under
                                           # /data/orpheus, and services-stop does not touch
                                           # it. Left armed it fires every 15 minutes, mid-
                                           # deploy. Re-start it in §4 when you are done.
make services-stop                         # quiesce the agents/UI so nothing writes during the
                                           # code swap and the one-time index migration runs
                                           # uncontended (it holds the writer lock). They come
                                           # back up in the update-services step below.
                                           # NOTE: services-stop DOES stop the backplane —
                                           # it is in the stop list. The broker is down from
                                           # here until install-backbone restarts it below.
                                           # If a step in between fails, start it by hand:
                                           # sudo systemctl start orpheus-backplane
git fetch origin
git checkout <branch-or-merge-commit>     # never force; add-on-top discipline
make install-backbone                      # NATS backplane FIRST (idempotent; loopback default).
                                           # REQUIRED, not optional: agents restarted before the
                                           # broker is up crash-loop until it is.
systemctl is-active orpheus-backplane.service   # confirm the broker is up BEFORE touching agents
make services-install                      # install any NEW agents this branch adds (audio-events,
                                           # event-correlator, ...). `update-services` alone only
                                           # updates already-installed components — new agents would
                                           # never appear. Also refreshes unit files.
make update-services                       # per-component code update + restart (self-sudos where needed)
make verify-deploy                         # imports (+ version cross-check), is-active, broker probe,
                                           # models, AND a data-read smoke on the migrated DB — expect all ✅
```

**First start on a large existing DB may pause.** The first agent to open the DB
builds compound indices over your whole detection history — on a Jetson with a
year of data this holds the writer lock for **seconds to minutes**. It logs
`Building compound index(es) on N existing detection rows … not a hang`. Let it
finish; this is a one-time cost, not a failure.

**Memory on a small board.** The three model agents (audio-events/PANNs,
bird-detection/BirdNET, crow-detection/AVES) each carry a soft `MemoryHigh` in
their unit — it throttles reclaim, it does not OOM-kill, so it's safe by default.
On a 4GB Nano, if `journalctl` shows heavy reclaim or the box thrashes when they
cold-start together, either lower the `MemoryHigh` values or start the heavy
agents one at a time (`systemctl start` each, wait for its model to load, then the
next) rather than all at once. `systemctl status orpheus-agent-*` shows each
agent's live memory (MemoryAccounting is on).

If `verify-deploy` shows a ❌, stop here and read its line — the egg-info pre-clean
and the gotchas entries cover the historical failure modes.

## 4. Soak checklist (first 30–60 minutes)

- [ ] `sudo systemctl start orpheus-storage-sweep.timer` — re-arm the sweep you
      stopped in §3. Nothing deletes recordings until you do.
- [ ] `make status-all` — every unit active.
- [ ] `journalctl -u "orpheus-*" --since -10m | grep -iE "error|traceback"` — nothing new/recurring.
- [ ] Dashboard: health cards green; detections flowing; entities appearing on real sounds.
- [ ] `curl -s localhost:8082/api/diagnostics/bus` (authenticated) — under
      `subscriptions`, `pending` should be empty. Non-empty while `connected` is
      `true` means the UI is connected to the broker but not listening to those
      subjects: it will keep serving whatever it cached, so the dashboard looks
      fine while going stale. The bus re-applies them itself within a minute; if
      they stay pending, `journalctl -u orpheus-ui | grep -i "subscriptions"` has
      the reason.
- [ ] Diagnostics: recent-errors panel quiet; storage history plotting.
- [ ] `systemctl status orpheus-storage-sweep.timer` — **active**, with a next
      elapse inside 15 minutes. The `.service` it triggers is a one-shot and is
      *inactive (dead)* between runs; that is correct, not a failure.
      `make verify-deploy` checks the same thing and reports the last run's result.
- [ ] `make storage-report` — the per-category table should show the ceilings and
      floors you confirmed in the step-3 pre-flight, and on a healthy station
      "nothing to do" in every row. `journalctl -u orpheus-storage-sweep --since -1h`
      has what the timed runs decided. For the first 24 hours after the timer is
      installed the sweep is report-only, so a row saying it *would* remove
      something is your cue to review the ceiling before the grace expires.
- [ ] Confirm defaults: no new flags flipped yet — once the transport is up,
      behavior should match pre-deploy. Two expected exceptions that are NOT bugs:
      the NATS transport itself, and a one-time pause on first start while the DB
      builds indices (grep the journal for `Building compound index(es)`). Anything
      else persistently different — new tracebacks, missing detections after the
      index build finishes — see the [rollback runbook](jetson-rollback.md).

## 5. Enable new features (deliberately, one at a time)

Only after a clean default soak, flip flags per the
[what's-new testing tour](whats-new-testing-tour.md) — one flag, observe, next.
Each feature's rollback is its own flag; the deploy never has to move.

## The cold cutover — for transport swaps and schema changes

The sequence above uses `update-services`, which restarts each component as its
update completes. For a **major** upgrade — a transport swap, a schema change — use
the stricter variant below instead, the one the flywheel_1 cutover ran on the
production Jetson on 2026-08-22. Its property: **nothing runs until you deliberately
start it**, so a bad component is caught with the rest of the system stopped rather
than mid-restart.

1. **Pull + tag in `$ORPHEUS_SRC`** (§2). Tags point at the DEPLOYED commit,
   never HEAD — using the `$BATCH` and `$DEPLOYED` you set in §0 and §2:
   `git tag "flywheel/$BATCH/pre-deploy" "$DEPLOYED" &&
   git tag -f orpheus/last-known-good "$DEPLOYED"`.
2. **Full stop**: `make services-stop`, plus `make -C services/orpheus-gps
   service-stop` (gps is missing from the top-level list),
   `sudo systemctl stop orpheus-storage-sweep.timer` (the ONLY unit that deletes
   data; `services-stop` does not touch it, and it fires every 15 minutes) and
   and, ONLY on a box that has never run `install-backbone`,
   `[ -f /etc/systemd/system/orpheus-mqtt.service ] && sudo systemctl stop orpheus-mqtt`
   — once NATS is installed `orpheus-mqtt` is an `Alias=` of `orpheus-backplane`, so
   the unqualified command stops your broker. Confirm with `systemctl list-units 'orpheus-*' --all --no-pager`
   — an armed timer's state is `waiting`, so `--state=running` hides it.
3. **Backup on the stopped box**: plain `cp -a` of every DB (+ any `-wal`/`-shm`
   sidecars) and the whole `/opt/orpheus/config` dir; `sha256sum` both sides;
   write a rollback note into the backup dir. No sqlite3 CLI is needed for a
   stopped-box copy. **Operator reviews the inventory before proceeding.**
4. **Cold code swap, zero processes running**: `make -C platform/orpheus-common
   install-service` FIRST (component deploys install orpheus-common from /opt);
   then per component `install-service` (unit files; agent installers do not
   start anything — orpheus_ui's does, so do the UI LAST) + `deploy` (code +
   dependency resolution into the deployed venv). Deploy the first agent alone
   and verify its venv (`pip list` — new platform deps like nats-py must
   appear; no paths into /home) before doing the rest.
   **Gotcha**: agent installers `cp -r .` — a working-tree `venv/` will be
   copied over the deployed venv. Remove/quarantine working-tree venvs first
   (see backlog: fix the installers to exclude venv).
5. **Transport**: `make install-backbone`; `systemctl is-active
   orpheus-backplane` must say active before any agent starts.
6. **Single-agent proof**: start the event-correlator alone (its unit `Wants=`
   bird + crow, so those come with it by design). Watch the journal
   (`sudo journalctl` — unprivileged reads silently show nothing) for the DB
   open / index build to complete and "Connected to NATS". A read-only python3
   row-count doubles as the data-read smoke where sqlite3 is absent.
7. **Staged rollout**: light agents, then model agents one at a time (watch
   RAM), then gps/bluetooth, UI last (its install-service auto-restarts it).
8. `make verify-deploy` → all ✅, then the §4 soak checklist (with `sudo` on
   the journalctl lines). Re-arm the sweep you stopped in step 2:
   `sudo systemctl start orpheus-storage-sweep.timer`.

Rollback is unchanged (checkout the tag in the runtime checkout, old code's
`services-install` restores mosquitto), and the schema contract held: old DB
was read untouched; the compound indices were already present so the one-time
build did not pause this cutover.
