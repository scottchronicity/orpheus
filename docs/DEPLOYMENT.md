# Orpheus Deployment Quick Reference

Run all `make` targets as your normal user — never `sudo make`. Targets
that need elevated privileges (installing systemd units, deploying to
`/opt/orpheus/`) invoke `sudo` internally for just those steps, and
`make install` actively rejects running as root.

## First-Time Setup (Jetson)

```bash
# 1. Clone repository
cd ~ && mkdir -p runtime/orpheus
cd runtime/orpheus
git clone https://github.com/scottchronicity/orpheus.git .

# 2. Install platform library (REQUIRED FIRST)
cd platform/orpheus-common
make install-service

# 3. Configure for your deployment
sudo nano /opt/orpheus/config/orpheus.yaml

# 4. Install and start everything else
cd ~/runtime/orpheus
make services-install    # every component, including the classifiers and correlator
make services-start
```

Install the whole set. Audio-motion without `audio-events`, `bird-detection`,
`crow-detection` and `event-correlator` gives you a station that records clips
and never identifies anything — see
[Installation](INSTALLATION.md#step-by-step-installation) for what each
component does and how to install a subset deliberately.

## Root Makefile Commands (Recommended)

The repository includes a root Makefile for easy orchestration across all services and agents:

```bash
# Quick deployment from root directory
cd ~/runtime/orpheus
make status-all       # Check status of all services
make update-all       # Update all services and agents after git pull
make logs-all         # Stream logs from all Orpheus services

# Full installation (first-time setup)
make services-install # Install all systemd services
make services-start   # Start all services

# Service control
make services-stop    # Stop all services
make services-restart # Restart all services
```

## Updating After Git Pull

### One-time cleanup: removing the legacy `orpheus-dashboard` service

The `orpheus-dashboard` service was retired — all of its
responsibilities now live in `orpheus-ui` (`services/orpheus_ui/`),
which serves the UI (now on port 8082). Existing Jetson deployments
still have the systemd unit installed and enabled from a previous
release. After your first `git pull` past commit `10c32ce`, do this
on each host **before** running `make update-all`:

```bash
sudo systemctl stop    orpheus-dashboard
sudo systemctl disable orpheus-dashboard
sudo rm -f /etc/systemd/system/orpheus-dashboard.service
sudo systemctl daemon-reload
```

`status-all` should then show `orpheus-ui` listening on port 8082
without the failed-state `orpheus-dashboard` entry. This is a one-
time step — once the unit file is gone, future `make update-all` runs
proceed normally.

### Update Platform + Config

```bash
cd ~/runtime/orpheus/platform/orpheus-common
git pull
make install-service  # Redeploys library, and leaves an existing
                      # /opt/orpheus/config/orpheus.yaml alone
```

`make update` is not the config path. It depends on `force-update-config`,
which **overwrites the live config**, and which cannot currently run at all —
it copies `config/orpheus.yaml` relative to `platform/orpheus-common/`, a
directory that does not exist in the repo. Edit
`/opt/orpheus/config/orpheus.yaml` in place instead.

### Update Specific Service

```bash
cd ~/runtime/orpheus/services/orpheus_ui
make update  # pulls the whole monorepo, reinstalls, rebuilds the frontend
             # (needs Node on PATH) and restarts. `make update-all` is the
             # orchestrated version across every component.
```

### Update Agent

```bash
cd ~/runtime/orpheus/agents/orpheus-agent-audio-motion
git pull
make install-service
sudo systemctl restart orpheus-agent-audio-motion
```

## Check Status

```bash
# All services
systemctl status orpheus-backplane orpheus-ui orpheus-agent-audio-motion orpheus-agent-video-snapshotter orpheus-agent-video-timelapser

# Logs
sudo journalctl -u orpheus-agent-audio-motion -f
sudo journalctl -u orpheus-agent-video-timelapser -f

# Dashboard
http://<jetson-ip>:8082
```

## After a deploy: check retention

`make services-install` installs and enables `orpheus-storage-sweep.timer` along
with the platform library. It is the only thing on the station that deletes a
recording — no agent trims its own directory — so it is worth one look after every
deploy:

```bash
systemctl status orpheus-storage-sweep.timer   # must be active, next elapse within 15 min
make storage-report                            # per-category table; deletes nothing
```

The `orpheus-storage-sweep.service` the timer triggers is a `Type=oneshot` and
reads `inactive (dead)` between runs. That is correct — `make verify-deploy`
checks the timer rather than the one-shot for exactly this reason, and reports the
last run's result.

It runs from `/opt/orpheus/platform/orpheus-common/venv`, which the platform's
own installer builds; `make storage-report` uses that same interpreter when one
is deployed, so the dry run answers for the code that will do the deleting
rather than for your working tree. `make verify-deploy` checks that every
installed unit's `ExecStart` binary exists — a one-shot with a missing
interpreter is invisible to `is-active`, since it is idle between runs either
way.

`storage-report` should show each category under its ceiling with "nothing to do".
For the first 24 hours after the timer is installed
(`storage.retention.first_run_grace_hours`) the sweep is **report-only**: it writes
its report, logs at CRITICAL if it would have removed anything, and deletes
nothing. That is the window in which to correct a ceiling you disagree with.
`orpheus-storage-sweep --force` starts enforcement early;
`sudo systemctl disable --now orpheus-storage-sweep.timer` or
`storage.retention.sweep_enabled: false` stops all deletion. See
[Data & retention](operator-manual/index.md#7-data-retention).

## Architecture

```shell
/opt/orpheus/
├── config/
│   └── orpheus.yaml                 # Single source of truth
├── platform/
│   └── orpheus-common/              # Shared library
├── services/
│   ├── orpheus_ui/
│   └── orpheus-backplane/
└── agents/
    ├── orpheus-agent-audio-motion/
    ├── orpheus-agent-video-snapshotter/
    └── orpheus-agent-video-timelapser/

Each service has its own venv but shares orpheus-common + config
```

## Config Search Order

The full search order is documented once, in
[Installation](INSTALLATION.md#config-file-not-found) — it begins with
`$ORPHEUS_CONFIG_PATH` and `$ORPHEUS_CONFIG_DIR`, and notes that there is no
`~/.config/orpheus/` lookup.

## Service Names

- `orpheus-backplane` - Messaging backplane (NATS + JetStream by default; the mosquitto
  fallback installs under the same unit name, so dependencies resolve either way)
- `orpheus-ui` - Web UI (FastAPI + React)
- `orpheus-agent-audio-motion` - Audio motion detector
- `orpheus-agent-video-snapshotter` - Periodic camera snapshots
- `orpheus-agent-video-timelapser` - Timelapse video generation
- `orpheus-storage-sweep.timer` - Retention. Drives a `Type=oneshot`
  `orpheus-storage-sweep.service` every 15 minutes; enable the **timer**, never
  the service, or it runs once at boot and never again

## Systemd Service Design Principles

All Orpheus services follow these patterns:

### Time Synchronization

Most services include `After=time-sync.target` so the system clock is synchronized
before they start. Three units do not yet: `orpheus-agent-video-snapshotter`,
`orpheus-agent-video-timelapser`, and `orpheus-bluetooth-autoconnect`. Ordering
against the clock prevents:

- Log timestamps showing Unix epoch (1970)
- Incorrect timestamps in recorded events
- Issues with certificate validation

### Loose Coupling

Services use `Wants=` instead of `Requires=` for inter-service dependencies:

```ini
# ✅ Correct: Loose coupling
After=network.target time-sync.target orpheus-backplane.service
Wants=orpheus-backplane.service

# ❌ Incorrect: Tight coupling
After=network.target orpheus-backplane.service
Requires=orpheus-backplane.service
```

**Why `Wants=` over `Requires=`:**

- Services can start even if dependencies aren't running
- If the backplane crashes, agents aren't forcibly stopped
- Dashboard remains accessible for diagnostics even if the backplane is down
- Each service handles connection failures gracefully in code

### Subscriptions Survive a Cold or Flapping Backplane

Loose coupling only works if a service that starts before the backplane ends up
genuinely subscribed once the backplane appears. The NATS bus enforces that:

- Each connection attempt is bounded by `connect_timeout` (10s). `nats-py` does
  not fail fast on a cold broker — it sits in its own retry loop and never
  returns — so a service starting first pauses for up to that long, then comes
  up disconnected and keeps retrying in the background. **An unbounded attempt
  is why a cold-broker start used to end as a hard connect failure** rather than
  the documented self-healing start.
- A `subscribe()` issued before the connection exists is buffered and applied on
  attach.
- A registration the broker refuses is retried by a background sweep, and again
  after any reconnect. `nats-py` restores only the subscriptions it registered
  itself, so one it never accepted would otherwise stay dead for the life of the
  process.
- Every application logs which subjects it restored, and warns (at `warning`)
  about any that are still not registered while the connection is up.

Check what a running service is actually subscribed to — not just whether it is
connected — via the UI's `/api/diagnostics/bus`, whose `subscriptions` block
reports `subscribed`, `pending`, and `requested`. **A non-empty `pending` while
`connected` is `true` means that service is not receiving those subjects.**

Starting the backplane before its consumers is still the right order (it avoids
a window of dropped publishes), but the cost of getting it wrong is now a short
recoverable gap rather than a service that silently serves stale data until
someone restarts it.

### Restart Policy

All services use `Restart=always` or `Restart=on-failure` with appropriate `RestartSec=` delays to handle transient failures without overwhelming the system.

## Systemd Journal Logging

Orpheus services automatically integrate with systemd journal for production logging.

### Requirements

To enable journal integration on Jetson, install systemd-python:

```bash
sudo apt-get install -y libsystemd-dev pkg-config
/opt/orpheus/<component>/venv/bin/pip install systemd-python>=235
```

This step is **optional** - services will work without it, logging to stdout/stderr. With systemd-python installed, logs are sent directly to the journal with proper metadata and also to stdout for backwards compatibility.

### Viewing Logs

```bash
# Follow logs for a service
sudo journalctl -u orpheus-ui -f

# View logs from the last hour
sudo journalctl -u orpheus-agent-audio-motion --since "1 hour ago"

# View logs from all Orpheus services
sudo journalctl -u "orpheus-*" -f
```

### Log Behavior

- **Development mode** (not under systemd): Logs to console with timestamps
- **Production mode** (under systemd without systemd-python): Logs to stdout/stderr, captured by journal
- **Production mode** (under systemd with systemd-python): Logs directly to journal with structured metadata + stdout

See [INSTALLATION.md](INSTALLATION.md) for full details.
