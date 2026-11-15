# Runbook — rolling a big branch onto the Jetson (with backups)

Precondition: the branch passed the [laptop verification runbook](laptop-verification.md)
end-to-end on the laptop (the laptop and this Jetson are independent machines — no
data is copied between them). Additive schemas and opt-in features reduce risk, but
do not imply an unchanged runtime: configured `auto` inference can select an
available accelerator, component installers can recreate environments, and the
audio-output installer can change Linux audio-service ownership when enabled. Read
the effective deployed configuration and complete the branch-specific gates below
before choosing the rollout path.

> **The one thing that is NOT "flip a flag": the transport is now NATS.**
> `event_bus.backend` defaults to `nats` (the actor-substrate roadmap pivot,
> [ADR 0017](../adr/0017-actor-model-nats-backplane.md)) and MQTT is no longer
> the transport we run. So **installing the NATS backplane is a required step of
> this upgrade, not optional** — step 3 does it *before* restarting agents,
> because agents that restart against a broker that isn't up will crash-loop
> until it is. There is no "roll back the transport" — if the deploy goes bad you
> restore the captured pre-deploy broker/runtime combination (§2); checking out old
> code does not restore the old broker or its state.

> **Pick your variant before you start.** §0–§5 below are the normal rolling deploy.
> If this upgrade swaps the transport or changes the schema, read
> [the cold cutover](#the-cold-cutover-for-transport-swaps-and-schema-changes) first
> and follow that instead — it stops everything before touching anything, so you find
> a bad component with the system quiet rather than half-restarted.

## 0. Know where you are (do this FIRST)

You can't roll back to a point you can't name. Record what's running now:

```bash
# Your git clone — NOT /opt/orpheus, which is an rsync deploy tree with no git metadata.
export ORPHEUS_SRC=~/runtime/orpheus
cd "$ORPHEUS_SRC"
make show-deployed        # local checkout/deploy-tree cross-check only; not proof of
                          # the deployed source commit
make verify-deploy        # read-only baseline health check
```

Every step below runs from `$ORPHEUS_SRC` unless it says otherwise: the make targets
install *into* `/opt/orpheus` from the checkout, and git only works in the checkout.

Record the deployed revision from an authoritative deployment record. `/opt/orpheus`
is an rsync tree without Git metadata, and `show-deployed` does not establish its
source commit. Without a record, derive it from the deployed files, and check the
candidate against it:

```bash
make match-deployed                        # the commits each deployed component matches exactly
make match-deployed REV=<candidate>        # ❌ = deploying <candidate> would revert that component
```

A ❌ against the candidate means the station runs commits the candidate does not
contain (local fixes deployed from a checkout and never pushed, for example).
Merge them into the candidate on a development branch, keeping their SHAs, and
re-check; never rewrite or reset the station's own checkout to get there. The
check needs those commits in the checkout it runs from (`git fetch` first) and
reads only the source trees: re-run it with `sudo` if a component is unreadable.

If the exact revision or baseline health cannot be established, stop.
If `verify-deploy` is already ❌ before deployment, resolve that first. Its
deployment-isolation section fails on runtime unit overrides and on anything
that depends on a home directory; the gates below say how to resolve each.

## 0a. Branch-specific runtime and audio gates

For a release that changes inference, component runtimes, or Bluetooth output,
capture the actual station baseline before deployment. A laptop checkout cannot
prove which revision or overrides are live. Save the effective configuration and
unit state privately in the backup directory; do not publish credentials.

```bash
BACKUP="${BACKUP:-/data/orpheus/backups/$(date +%Y%m%d-%H%M)}"
sudo mkdir -p "$BACKUP"
sudo cp -a /opt/orpheus/config "$BACKUP/config-before-review"
sudo systemctl list-unit-files 'orpheus-*' --no-pager | sudo tee "$BACKUP/unit-files.txt" >/dev/null
sudo systemctl list-units 'orpheus-*' --all --no-pager | sudo tee "$BACKUP/unit-state.txt" >/dev/null
for unit in orpheus-backplane orpheus-gps orpheus-agent-event-correlator \
  orpheus-agent-audio-events orpheus-agent-bird-detection \
  orpheus-agent-crow-detection orpheus-audio-output \
  orpheus-agent-audio-playback; do
  sudo systemctl cat "$unit" 2>&1 | sudo tee -a "$BACKUP/effective-units.txt" >/dev/null
done
if [ -x /usr/local/bin/nats-server ]; then
  /usr/local/bin/nats-server -v | sudo tee "$BACKUP/nats-version.txt" >/dev/null
else
  echo "NATS binary not installed" | sudo tee "$BACKUP/nats-version.txt" >/dev/null
fi
sudo du -sh /var/lib/orpheus/backplane/jetstream 2>/dev/null || true
for unit in orpheus-gps orpheus-agent-event-correlator \
  orpheus-agent-audio-events orpheus-agent-bird-detection \
  orpheus-agent-crow-detection orpheus-audio-output \
  orpheus-agent-audio-playback; do
  sudo systemctl show "$unit" -p LoadState -p ActiveState -p User -p ExecStart \
    | sudo tee -a "$BACKUP/unit-details.txt" >/dev/null
done
for py in /opt/orpheus/services/orpheus-gps/venv/bin/python \
  /opt/orpheus/agents/orpheus-agent-event-correlator/venv/bin/python \
  /opt/orpheus/agents/orpheus-agent-audio-events/venv/bin/python \
  /opt/orpheus/agents/orpheus-agent-bird-detection/venv/bin/python \
  /opt/orpheus/agents/orpheus-agent-crow-detection/venv/bin/python; do
  [ ! -x "$py" ] || "$py" -c 'import sys; print(sys.executable, sys.version)'
done
# Installers for several services remove and recreate their venvs. Preserve
# restorable pre-deploy environments on this host; a Git checkout cannot recreate
# an old Python minor version or guarantee that its ARM64 wheels remain available.
for env in /opt/orpheus/services/orpheus-gps/venv \
  /opt/orpheus/agents/orpheus-agent-event-correlator/venv \
  /opt/orpheus/agents/orpheus-agent-audio-events/venv \
  /opt/orpheus/agents/orpheus-agent-bird-detection/venv \
  /opt/orpheus/agents/orpheus-agent-crow-detection/venv; do
  if sudo test -d "$env"; then
    sudo mkdir -p "$BACKUP/venvs"
    sudo cp -a "$env" "$BACKUP/venvs/$(basename "$(dirname "$env")")-venv"
  fi
done
sudo systemctl cat orpheus-audio-output orpheus-agent-audio-playback
if sudo test -d /etc/orpheus/bluetooth-autoconnect; then
  sudo cp -a /etc/orpheus/bluetooth-autoconnect "$BACKUP/"
fi
```

Resolve these gates against the station's actual config and installed environments:

- GPS and event-correlator require Python 3.12 or 3.13. Their installers recreate
  their deployed virtual environments. Confirm the interpreter and dependency
  wheels resolve for the station's Jetson ARM64/Python ABI before stopping services.
  A local macOS test, PyPI metadata, or a successful source checkout does not prove
  that every binary wheel exists or builds on the deployed JetPack image. No system
  Python is replaced, and these runtimes do not replace the NVIDIA environment.
- PANNs' validated CUDA worker remains an optional Python 3.8 environment at
  `$ORPHEUS_DATA_ROOT/venvs/panns-gpu`. It is installed separately with the
  hash-checked NVIDIA wheel. General service deployment must not recreate or
  upgrade it. Confirm the worker executable, checkpoint and CUDA health before
  selecting `gpu_worker` or `auto`.
- BirdNET's normal install uses CPU `onnxruntime`; CUDA uses the compatible
  `onnxruntime-gpu` package in that agent's venv, with exactly one ORT package
  installed. Confirm the installed distribution and health-reported providers.
  An explicit accelerator with a missing provider must stop at startup; `auto`
  uses only providers the installed runtime exposes.
- Crow defaults to `device: auto`, which may select CUDA on Jetson. Confirm actual
  device and memory behavior from health/logs instead of assuming CPU execution.
- Read the live YAML and `.env` (and the legacy Bluetooth `config.env`, if it
  still exists) without replacing them with the example config. The audio-output
  installer reports which source won configuration resolution.
  When `audio_output.enabled: true`, its installer masks the configured user's
  stock PulseAudio units, enables lingering, stops stock PulseAudio, retires the
  legacy/competing Bluetooth units, writes a playback routing drop-in, and starts
  the manager. It may restart a running playback agent. Confirm exact output,
  server and user settings, saved prior unit state, and recording isolation before
  allowing this host transaction. When disabled, the installer disables the new
  manager and leaves other audio services unchanged.
- `make services-install` invokes the audio-output installer; it is not a dry run.
  `make update-services` deploys code and restarts components. Use the cold cutover
  below. Never run these against active writers as a preflight.
- **Runtime unit overrides.** A drop-in under `/run/systemd/system/<unit>.d/`
  (from `systemctl edit --runtime` or a trial) outranks `/etc`, is in no repo,
  survives the deploy, and vanishes at the next reboot: the service then runs one
  way after the deploy and another after a power cut. `verify-deploy` fails on it
  and on any unit `Environment`/`ExecStart` path into a home directory. The
  `systemctl cat` capture above records it. Carry the setting you want to keep into
  `orpheus.yaml`, and remove the drop-in during the cutover with that component
  stopped (`sudo rm /run/systemd/system/<unit>.d/<name>.conf && sudo systemctl
  daemon-reload`).
- **PANNs backend after a trial override.** A GPU trial drop-in typically sets
  `ORPHEUS_AUDIO_EVENTS__BACKEND=gpu_worker` and a `PYTHONPATH` into a home-directory
  checkout. The deployed agent at the candidate has the worker client, so drop the
  `PYTHONPATH`. Then decide: `audio_events.backend: gpu_worker` (GPU required) or
  `auto` keeps the worker; `inprocess` (the default) runs on CPU on JetPack 5,
  because the agent venv's Torch has no CUDA there, so `device: auto` resolves to
  CPU. The worker's memory gates are checked at start and while running: if
  `last_error` in its health reports MemAvailable below the start gate (timelapse
  encodes and the other model agents compete for memory), size the
  `audio_events.gpu_worker` budgets from measurements
  ([PANNs on GPU](../operator-manual/panns-gpu.md)) before relying on it.
- **Python 3.12/3.13 for GPS and the correlator.** JetPack 5 ships 3.8 and 3.9.
  `sudo scripts/provision-python.sh` installs a pinned CPython under
  `/opt/orpheus/python` (a distribution package also works). Never point a deployed
  venv at an interpreter under a home directory (a user's uv or pyenv Python):
  `verify-deploy` fails such a venv. `make … install-service` runs each installer
  under `sudo`, which drops `PYTHON_BIN`, so invoke these two directly:
  `sudo PYTHON_BIN=/opt/orpheus/python/bin/python3.12 bash services/orpheus-gps/systemd/install-service.sh`,
  and the same for `agents/orpheus-agent-event-correlator/systemd/install-service.sh`.
  A global `PYTHON_BIN` would also reach bird-detection, which requires 3.9.
- **BirdNET's venv.** Its installer copies only the agent's payload (never a
  working-tree or old venv beside the source), rebuilds the venv with Python 3.9
  on every install, and fails if the result references a home directory. A deployed
  venv that `verify-deploy` reports as depending on a home directory is replaced
  by a normal install. `sudo ONNX_RUNTIME=cuda bash agents/orpheus-agent-bird-detection/systemd/install-service.sh`
  selects `onnxruntime-gpu`; the default is CPU.

Stop if a required interpreter or dependency is unavailable, accelerator selection
does not match the installed runtime, effective audio settings or competing-unit
state are unclear, capture isolation is unhealthy, the baseline is degraded, or
the rollback artifacts are incomplete.

## 1. Backup (5 minutes, on the Jetson)

The schema contract means the OLD binary can always read the NEW database
(additive columns only), so a DB restore should never be *needed* — this backup is
belt-and-suspenders.

Everything under `/data/orpheus` belongs to `orpheus:orpheus` and everything under
`/opt/orpheus` to root, so this whole section runs under `sudo` — an unprivileged
`mkdir` into the data root just fails with permission denied.

JetPack ships no `sqlite3` CLI (`sudo sqlite3 ...` fails with `command not found`),
so the backup is a stdlib-Python tool, `scripts/backup-databases.py`:

```bash
# Every SQLite DB under /data/orpheus (incl. detections/) + the deployed
# orpheus.yaml and .env. VACUUM INTO from a read-only connection: a consistent
# snapshot with the agents still running (a live cp of a WAL-mode DB copies a
# torn/stale file). Each copy is integrity-checked before it counts; it refuses
# an existing destination or too little free space. ~9 GB for an 8 GB orpheus.db.
make backup-databases ARGS=--dry-run          # what it will copy, and the space it needs
BACKUP="${BACKUP:-/data/orpheus/backups/$(date +%Y%m%d-%H%M)}"
make backup-databases ARGS="--dest $BACKUP"   # --quick: quick_check instead of integrity_check
make verify-backup BACKUP="$BACKUP"           # sha256 + integrity again, from the files on disk
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

**This feature branch must use the cold cutover below.** The generic rolling
commands in this section restart and reinstall components in place. They are
disqualified when a release changes the transport, recreates component runtimes,
changes accelerator packages, or changes audio-server ownership. This branch
contains all four kinds of change. In particular, `services-install` invokes the
audio-output transaction and `update-services` restarts components; neither is a
safe preflight or a substitute for the staged sequence.

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

Treat each capability as a separate acceptance gate. Save command output and
timestamps in the rollback note. A simulated or laptop pass does not satisfy the
Jetson hardware gates below.

| Area | Acceptance check | Stop condition |
|---|---|---|
| NATS | `systemctl is-active orpheus-backplane`; run `make verify-deploy`; confirm agents reconnect and subscriptions are present. | Broker probe fails, agents remain disconnected, or pending subscriptions do not clear. |
| Recording continuity | Confirm audio-motion is active and new recordings continue across the cutover; verify fresh `audio.motion` events/clips and inspect the configured capture device. Compare with the pre-deploy recording cadence. | Any recording gap, device ownership change, or capture-isolation health failure. |
| Audio output | Only after output manager health is `healthy` and capture isolation is `ok`, perform one brief, low-volume playback check using the approved station sound. Confirm start/finish share a playback ID and timing/elapsed duration are plausible. | Playback is routed to the wrong sink, records through ALSA/capture, or event timing/identity is absent. |
| Corollary discharge | Confirm `corollary_discharge.enabled` remains false unless it was deliberately enabled in the backed-up station config. When enabled, verify overlapping observations are tagged `is_self_generated`, persisted and published; unrelated wildlife remains untagged and retained. | Any observation is deleted/suppressed, unrelated wildlife is tagged, or a playback window arrives too late to account for an overlap. |
| BirdNET | Check health-reported requested and registered ONNX providers, then verify normal classifications and confidence/geo-filter behavior. | Explicit provider request differs from registered provider, model load fails, or detection semantics regress. |
| PANNs | Verify the isolated worker's Python 3.8 interpreter, NVIDIA Torch/CUDA and model hashes; compare expected CPU/GPU labels and intervals on the accepted fixture/known clip. | Worker health/recovery fails, mismatched model/runtime artifact, or results exceed the accepted comparison. |
| Crow and correlation | Confirm configured crow device in health/logs; verify detections flow through correlator, persistence, and NATS publication. | Correlator errors, missing persisted/published detections, or unexpected device/resource pressure. |
| Existing services | `make status-all`; inspect service journals and dashboard; confirm GPS, camera capture, snapshot/timelapse, storage timer and UI behavior. | Any previously healthy service is degraded or storage timer is not re-armed. |

Keep corollary discharge disabled by default. A disabled configuration is accepted
when playback events do not cause tagging; enabling it is a separate, intentional
config change and acceptance gate.

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
When a flag-gated behavior alone misbehaves, disable that flag and restart only
its owning unit. Transport, runtime, provider, or audio-ownership failures require
the staged Level 2 rollback; a flag change cannot restore those components.

## The cold cutover — for transport swaps and schema changes

For a transport swap, schema change, runtime recreation, inference-provider change,
or audio-ownership change, use the cold cutover below. Do not use the generic
rolling sequence above for this feature branch. A cold cutover keeps writers stopped
while code and environments change, then starts components in explicit stages.

1. **Pull + tag in `$ORPHEUS_SRC`** (§2). Tags point at the DEPLOYED commit,
   never HEAD — using the `$BATCH` and `$DEPLOYED` you set in §0 and §2:
   `git tag "flywheel/$BATCH/pre-deploy" "$DEPLOYED" &&
   git tag -f orpheus/last-known-good "$DEPLOYED"`.
2. **Full stop**: `make services-stop`, plus `make -C services/orpheus-gps
   service-stop` (GPS is missing from the top-level list),
   `sudo systemctl stop orpheus-storage-sweep.timer` (the ONLY unit that deletes
   data; `services-stop` does not touch it, and it fires every 15 minutes) and
   and, ONLY on a box that has never run `install-backbone`,
   `[ -f /etc/systemd/system/orpheus-mqtt.service ] && sudo systemctl stop orpheus-mqtt`
   — once NATS is installed `orpheus-mqtt` is an `Alias=` of `orpheus-backplane`, so
   the unqualified command stops your broker. Confirm with `systemctl list-units 'orpheus-*' --all --no-pager`
   — an armed timer's state is `waiting`, so `--state=running` hides it.
3. **Backup on the stopped box**: plain `cp -a` of every DB (+ any `-wal`/`-shm`
   sidecars), the whole `/opt/orpheus/config` dir, `/etc/orpheus/backplane`, and
   `/var/lib/orpheus/backplane/jetstream`; save the backplane unit and NATS version
   too. The JetStream file store holds durable stream/KV state and is outside
   `$ORPHEUS_DATA_ROOT`; SQLite backups do not cover it. Check free space first,
   stop the backplane before copying its store, and keep that copy if rolling back
   to another broker. `sha256sum` the backups and record their paths. No sqlite3
   CLI is needed for a stopped-box copy. **Operator reviews the inventory before
   proceeding.**
4. **Cold code swap, zero processes running**: `make -C platform/orpheus-common
   install-service` FIRST (component deploys install orpheus-common from /opt).
   Install/deploy per component with its declared runtime and verify imports and
   dependencies before continuing. Keep the audio-output installation out of this
   batch: its installer is a host transaction that starts the manager when enabled,
   even though this cutover is still in its file-install stage. Install it later at
   the audio stage in §7, after its ownership gate. Install UI last because its
   installer can restart it. Deploy one component at a time and verify its venv
   (`pip list` — new platform dependencies like nats-py must appear; no paths into
   `/home`) before continuing.
   **Gotcha when installing from an older checkout**: its bird-detection and
   event-correlator installers `cp -r .`, so a working-tree `venv/` (or an
   untracked `oldvenv/` beside the source) is copied into `/opt`, over the
   deployed venv. Those two installers now copy only the payload; GPS copies only
   `src/` and `systemd/`. With an older checkout, move working-tree venvs out of
   the agent directories first.
   A component `deploy` syncs source before installing its package. If it returns
   nonzero, treat that component as partially changed: keep its unit stopped, do
   not continue the rollout or start it, and restore/redeploy the tagged known-good
   revision before resuming. A failed install is not an automatic rollback.
5. **Transport**: `make install-backbone`; `systemctl is-active
   orpheus-backplane` must say active before any agent starts.
6. **Single-agent proof**: start the event-correlator alone (its unit `Wants=`
   bird + crow, so those come with it by design). Watch the journal
   (`sudo journalctl` — unprivileged reads silently show nothing) for the DB
   open / index build to complete and "Connected to NATS". A read-only python3
   row-count doubles as the data-read smoke where sqlite3 is absent.
7. **Staged rollout**: verify NATS first; then GPS and the correlator using the
   confirmed Python 3.12/3.13 interpreter, passed as `PYTHON_BIN` on the `sudo`
   command line of each installer (§0a). Start light agents, then model agents
   one at a time while watching memory and accelerator health. Install audio output
   only after confirming its effective config and saved prior audio-unit state;
   verify capture isolation before starting audio-motion or playback. Start
   playback only after output is ready. Keep the separately installed PANNs Python
   3.8 worker untouched. Start/verify the correlator after NATS and detection
   producers are healthy; UI last (its installer can restart it). Do not use the
   generic `services-start` as a substitute for these gates.
8. `make verify-deploy` → all ✅, then the §4 soak checklist (with `sudo` on
   the journalctl lines). Re-arm the sweep you stopped in step 2:
   `sudo systemctl start orpheus-storage-sweep.timer`.

Rollback is not a one-command operation for this branch. It must restore the
specific pre-deploy combination recorded at the station: service code and units,
Python interpreters and venvs, effective configuration, audio ownership, broker
implementation/version, and JetStream file-store state when applicable. Do not
assume the older checkout's aggregate `services-install` restores those pieces
safely. See the [rollback runbook](jetson-rollback.md); if any part of the baseline
or its restorable artifacts was not captured, stop and treat rollback as unproven.
