# Orpheus Installation Guide

This guide covers production deployment of the Orpheus cross-species communication system on edge devices (tested on NVIDIA Jetson Orin NX).

**On a laptop, or not on Linux?** This page is the Linux/Jetson production reference.
For a working install on your own machine, use the quickstart for it — each is
self-contained and gets you to a dashboard with live detections:
[macOS](MACOS_QUICKSTART.md) (~15 minutes, the development and demo path) ·
[Linux](LINUX_QUICKSTART.md) · [Windows](WINDOWS_QUICKSTART.md) ·
[Jetson](JETSON_QUICKSTART.md). To try Orpheus with no install at all, the
[container fleet](operator-manual/index.md#3-deployment-topologies) runs the whole
collective on a laptop.

## Overview

Orpheus uses a **centralized shared library architecture**:

```shell
/opt/orpheus/
├── platform/
│   └── orpheus-common/          # Shared library (install FIRST)
├── config/
│   └── orpheus.yaml             # Central configuration
├── services/
│   ├── orpheus_ui/       # Web dashboard
│   └── orpheus-backplane/       # Messaging backplane (NATS default; mosquitto fallback)
└── agents/
    ├── orpheus-agent-audio-motion/      # Audio motion detection (the source of every clip)
    ├── orpheus-agent-audio-events/      # PANNs general sound classifier
    ├── orpheus-agent-bird-detection/    # BirdNET species classifier
    ├── orpheus-agent-crow-detection/    # Corvid specialist
    ├── orpheus-agent-event-correlator/  # Fuses detections into entities
    ├── orpheus-agent-audio-playback/    # Plays audio at the site
    ├── orpheus-agent-video-motion/      # RTSP motion detection
    ├── orpheus-agent-video-snapshotter/ # Periodic camera snapshots
    └── orpheus-agent-video-timelapser/  # Timelapse video generation
```

The audio chain is what makes Orpheus more than a recorder: audio-motion captures
a clip, the classifiers label it, and the correlator collapses their overlapping
opinions into a single entity. Installing audio-motion without the classifiers and
the correlator gives you a system that records and never identifies anything.

A developer-style `make install` from the repository root additionally installs the
dashboard frontend's dependencies and the end-to-end test harness, which downloads a
private copy of Chromium (a few hundred MB) via Playwright. It does not produce a
built bundle: `make -C services/orpheus_ui build-frontend` does that, and
`make dev-stack` does not need one — it serves the dashboard from the Vite dev
server. The per-service
`make install-service` path used below does not — see
[Node.js: what needs it, and when](ORPHEUS_UI.md#nodejs-what-needs-it-and-when).

Each service/agent has its own Python virtual environment but shares:

- **orpheus-common library** (installed once at `/opt/orpheus/platform/orpheus-common`)
- **Configuration** (single `orpheus.yaml` at `/opt/orpheus/config/orpheus.yaml`)

## Prerequisites

- Ubuntu 20.04+ or Jetson Linux (L4T)
- Python 3.9.x only — every component pins `requires-python = ">=3.9, <3.10"`, so 3.10 and up are rejected by pip, not merely discouraged
- **Node.js 20+ and npm** — needed only for a developer-style `make install`, which
  installs the dashboard frontend's dependencies with the `npm` on your PATH. The per-service
  `make install-service` used below fetches its own Node.js instead. See
  [Node.js: what needs it, and when](ORPHEUS_UI.md#nodejs-what-needs-it-and-when).
- **Git LFS** — the ML model files are stored in LFS. Without it you get 130-byte
  pointer files and every classifier fails to load. Install it *before* cloning, or
  run `git lfs install && git lfs pull` in an existing clone.
- systemd
- sudo access

Pulling the models is roughly 1.5 GB. Plan for that on a metered or slow connection.

## Quick Start (Jetson)

```bash
# Clone the repository
cd ~
mkdir -p runtime/orpheus
cd runtime/orpheus
git clone https://github.com/scottchronicity/orpheus.git .

# Fetch the ML models (~1.5 GB). Skipping this leaves pointer files behind and
# every classifier fails to load its model.
git lfs install
git lfs pull

# Install in order:
# 1. Platform library (REQUIRED FIRST)
cd platform/orpheus-common
make install-service

# 2. Edit configuration for your deployment
sudo nano /opt/orpheus/config/orpheus.yaml

# 3. Messaging backplane (NATS + JetStream by default; BACKPLANE_BROKER=mqtt for mosquitto)
cd ../../services/orpheus-backplane
make install    # installs, enables + starts orpheus-backplane

# 4. Web UI
cd ../orpheus_ui
make install-service
sudo systemctl start orpheus-ui

# 5. Audio Motion Detector Agent — captures the clips everything else works on
cd ../../agents/orpheus-agent-audio-motion
make install-service
sudo systemctl start orpheus-agent-audio-motion

# 6. Classifiers + correlator — without these, clips are recorded but never identified
for agent in orpheus-agent-audio-events orpheus-agent-bird-detection \
             orpheus-agent-crow-detection orpheus-agent-event-correlator; do
  cd ../$agent
  make install-service
  sudo systemctl start $agent
done

# 7. Audio playback (optional — lets Orpheus play sound at the site)
cd ../orpheus-agent-audio-playback
make install-service
sudo systemctl start orpheus-agent-audio-playback

# 8. Video Agents (optional, for camera motion + timelapse generation)
cd ../orpheus-agent-video-motion
make install-service
sudo systemctl start orpheus-agent-video-motion

cd ../orpheus-agent-video-snapshotter
make install-service
sudo systemctl start orpheus-agent-video-snapshotter

cd ../orpheus-agent-video-timelapser
make install-service
sudo systemctl start orpheus-agent-video-timelapser
```

## Step-by-Step Installation

### 1. Install orpheus-common Platform Library

This **must be installed first** as all services depend on it.

```bash
cd ~/runtime/orpheus/platform/orpheus-common
make install-service
```

This will:

- Install the shared library to `/opt/orpheus/platform/orpheus-common`
- Deploy default config to `/opt/orpheus/config/orpheus.yaml`
- Create example configs for reference

### 2. Configure Your Deployment

Edit the central configuration file:

```bash
sudo nano /opt/orpheus/config/orpheus.yaml
```

Key settings to update:

- Event bus backend + broker URL (`event_bus.backend`: `nats` default, `mqtt` fallback; `event_bus.nats_url`)
- Camera hostnames and credentials
- Storage paths
- Audio channel configuration
- Service list for dashboard monitoring

### 3. Install Services

Each service installer will:

- Create isolated Python venv
- Install orpheus-common from central location
- Deploy service-specific files
- Install and enable systemd unit

```bash
# Messaging backplane (NATS + JetStream by default)
cd ~/runtime/orpheus/services/orpheus-backplane
make install    # installs, enables + starts orpheus-backplane

# Dashboard
cd ~/runtime/orpheus/services/orpheus_ui  
make install-service
sudo systemctl start orpheus-ui
```

### 4. Install Agents

Install audio-motion, the three classifiers, and the correlator together — they
are one pipeline.

```bash
# Audio Motion Detector — captures a clip whenever the soundscape changes
cd ~/runtime/orpheus/agents/orpheus-agent-audio-motion
make install-service
sudo systemctl start orpheus-agent-audio-motion

# Audio Events (PANNs) — general sound classification
cd ../orpheus-agent-audio-events
make install-service
sudo systemctl start orpheus-agent-audio-events

# Bird Detection (BirdNET) — species identification
cd ../orpheus-agent-bird-detection
make install-service
sudo systemctl start orpheus-agent-bird-detection

# Crow Detection — corvid specialist
cd ../orpheus-agent-crow-detection
make install-service
sudo systemctl start orpheus-agent-crow-detection

# Event Correlator — fuses the classifiers' output into entities
cd ../orpheus-agent-event-correlator
make install-service
sudo systemctl start orpheus-agent-event-correlator

# Audio Playback (optional) — plays sound at the site
cd ../orpheus-agent-audio-playback
make install-service
sudo systemctl start orpheus-agent-audio-playback

# Video Snapshotter (captures periodic camera images)
cd ~/runtime/orpheus/agents/orpheus-agent-video-snapshotter
make install-service
sudo systemctl start orpheus-agent-video-snapshotter

# Video Timelapser (generates timelapse videos from snapshots)
cd ~/runtime/orpheus/agents/orpheus-agent-video-timelapser
make install-service
sudo systemctl start orpheus-agent-video-timelapser
```

## Signing in to the dashboard

Every dashboard route requires a login, so set the credentials before you start
the UI for the first time. Two accounts are seeded on first boot from the
environment the service runs under:

| Account | Email variable | Password variable | Default if unset |
|---|---|---|---|
| Admin | `ORPHEUS_UI_ADMIN_EMAIL` | `ORPHEUS_UI_ADMIN_PASSWORD` | `admin@orpheus.example.com` / `changeme` |
| Guest | `ORPHEUS_UI_GUEST_EMAIL` | `ORPHEUS_UI_GUEST_PASSWORD` | `guest@orpheus.example.com` / `guest` |

Put these in `/opt/orpheus/config/.env`, which the UI unit reads
(`EnvironmentFile=-/opt/orpheus/config/.env`) — the same file that carries the
backbone URL for every other component. Exporting them in your own shell does not
reach a systemd service. Set them **before** the first start: the defaults exist so a
fresh checkout runs, they are public knowledge, and they must not survive onto
anything reachable by other people. Set `ORPHEUS_UI_JWT_SECRET` there too — without
it the server generates a random secret at each boot, which silently invalidates
every session on restart.

```bash
sudo tee -a /opt/orpheus/config/.env >/dev/null <<'EOF'
ORPHEUS_UI_ADMIN_PASSWORD=<a long random password>
ORPHEUS_UI_GUEST_PASSWORD=<another one>
ORPHEUS_UI_JWT_SECRET=<32+ random bytes>
EOF
sudo systemctl restart orpheus-ui
```

**If the UI has already started with the defaults**, seeding will not run again — it
is guarded on an empty user table, so adding the variables now rotates nothing. The
login page says so, and there are exactly two ways out:

- Sign in and `PATCH /users/me` with a new password. This is the safe one; it keeps
  your data and your existing accounts.
- Or stop the UI, delete the accounts database (`/data/orpheus/users.db` on a station — the backend logs the path it resolved), and
  restart with the variables above set, which re-seeds both accounts from them. This
  destroys any accounts you created by hand.

The dashboard's Settings page shows a Security card, but it is a placeholder — there
is no password field in the UI yet.

**On a development machine** (`make dev-stack`, no systemd) the same variables apply,
but nothing reads `/opt/orpheus/config/.env` — that path exists only on an installed
host. Put them in `config/.env.orpheus` in your checkout, which `dev-stack` sources
before starting anything:

```bash
cat >> config/.env.orpheus <<'EOF'
ORPHEUS_UI_ADMIN_PASSWORD=<a long random password>
ORPHEUS_UI_GUEST_PASSWORD=<another one>
ORPHEUS_UI_JWT_SECRET=<32+ random bytes>
EOF
make dev-restart SVC=orpheus-ui-backend
```

The accounts database follows the same rule as everything else: `users.db` at the
top of `$ORPHEUS_DATA_ROOT` (so `/data/orpheus/users.db` on a station, `~/data/orpheus/users.db`
on a laptop that sets it). An accounts file that already exists somewhere else keeps
being used, so rotating your data root never strands the passwords you seeded; when
nothing exists yet, a fresh one is created under the data root. `ORPHEUS_UI_DATABASE_URL`
overrides all of that, and the shipped systemd unit sets it. The backend logs the file
it resolved on startup — read that before you delete anything.

See [Security](security.md) for what the dashboard does and does not protect.

## Updating After Changes

When you make code or configuration changes:

### Update Platform Library

```bash
cd ~/runtime/orpheus/platform/orpheus-common
git pull
make install-service
```

### Update Configuration

```bash
cd ~/runtime/orpheus/platform/orpheus-common
git pull
make install-service    # leaves an existing /opt/orpheus/config/orpheus.yaml alone
```

Do not use `make update` here. It depends on `force-update-config`, which
**overwrites the live config** — and which currently cannot run at all, because
it copies `config/orpheus.yaml` relative to `platform/orpheus-common/`, a path
that does not exist in the repo. To change the deployed config, edit
`/opt/orpheus/config/orpheus.yaml` in place and restart the affected units.

### Update Individual Services

```bash
cd ~/runtime/orpheus/services/orpheus_ui
make update  # pulls the whole monorepo, reinstalls, rebuilds the frontend
             # (needs Node on PATH) and restarts. `make update-all` is the
             # orchestrated version across every component.
```

### Update Agents

```bash
cd ~/runtime/orpheus/agents/orpheus-agent-audio-motion
git pull
make install-service  # Redeploys and restarts
sudo systemctl restart orpheus-agent-audio-motion
```

## Verification

Check every unit, not a hand-picked five — the classifiers and the correlator
are the ones whose absence you notice as "detections never appear":

```bash
systemctl list-units 'orpheus-*' --type=service
make verify-deploy    # imports, unit states, broker probe, and a data read
```

Then prove the pipeline end to end rather than stopping at "the units are up":
make a noise near the microphone and watch a detection arrive on the dashboard
within ten to twenty seconds.

Access the dashboard:

```shell
http://<jetson-ip>:8082
```

View logs:

```bash
sudo journalctl -u orpheus-backplane -f
sudo journalctl -u orpheus-ui -f
sudo journalctl -u orpheus-agent-audio-motion -f
```

## Uninstallation

```bash
# Stop and disable EVERY orpheus unit, including the storage-sweep timer.
# Naming units individually leaves whichever ones you forgot running against
# deleted venvs, and the sweep is the one that deletes recordings.
sudo systemctl disable --now 'orpheus-*'

# Remove service files. Both patterns: the sweep ships a .timer as well as a
# .service, and a .service-only glob leaves an enabled timer pointing at a
# unit that no longer exists.
sudo rm -f /etc/systemd/system/orpheus-*.service /etc/systemd/system/orpheus-*.timer
sudo systemctl daemon-reload

# Keep your config first if you want it — removing /opt/orpheus takes it too
sudo cp /opt/orpheus/config/orpheus.yaml ~/orpheus.yaml.bak

# Remove the installation (this includes /opt/orpheus/config)
sudo rm -rf /opt/orpheus

# The broker does not live under /opt/orpheus
sudo rm -f /usr/local/bin/nats-server
sudo rm -rf /etc/orpheus/backplane /var/lib/orpheus/backplane
```

Recordings and the detections database are under `$ORPHEUS_DATA_ROOT`
(`/data/orpheus` by default) and are **not** touched by any of the above.

## Development vs Production

**Development** (on laptop/desktop):

- Use `make install` to create local venv
- Uses `-e ../../platform/orpheus-common` editable install
- Config in repo at `config/orpheus.yaml` (repo root)
- Run with `make run`

**Production** (on Jetson):

- Use `make install-service` for systemd deployment
- Installs orpheus-common from `/opt/orpheus/platform/orpheus-common`
- Config at `/opt/orpheus/config/orpheus.yaml`
- Runs as systemd service under `orpheus` user

## Troubleshooting

### Service won't start

```bash
# Check status and recent logs
sudo systemctl status orpheus-agent-audio-motion
sudo journalctl -u orpheus-agent-audio-motion -n 50 --no-pager
```

### orpheus-common not found

Ensure you installed it first:

```bash
sudo /opt/orpheus/platform/orpheus-common/systemd/install.sh
```

### Config file not found

The system looks for config in this order:

1. `$ORPHEUS_CONFIG_PATH` (a full path to a file, if set)
2. `$ORPHEUS_CONFIG_DIR/orpheus.yaml` (if set)
3. `/opt/orpheus/config/orpheus.yaml` (production)
4. `/etc/orpheus/orpheus.yaml` (alternative system location)
5. `./config/orpheus.yaml` (development, from the repo)
6. `./orpheus.yaml` (current directory)

There is no `~/.config/orpheus/` lookup — a config placed there is ignored.
Ensure `/opt/orpheus/config/orpheus.yaml` exists.

### Permission errors

Services run as the `orpheus` user. Check permissions:

```bash
ls -la /opt/orpheus/
ls -la /mnt/data/  # or your storage path
```

## Architecture Notes

Each component gets its own virtualenv, so no two components fight over a
dependency version. The reasoning behind the shared library, the single config file and the
per-component versioning is in [Architecture](ARCHITECTURE.md) and the
[decision records](adr/README.md).
