# Jetson Quick Start

Get the Orpheus Observe stack running on an NVIDIA Jetson Orin NX. This guide covers both **development** (run from the repo) and **production** (systemd services under `/opt/orpheus`).

For macOS development, see [macOS Quick Start](MACOS_QUICKSTART.md). For Windows (WSL2), see [Windows Quick Start](WINDOWS_QUICKSTART.md) (untested). For generic Linux, see [Linux Quick Start](LINUX_QUICKSTART.md) (untested). For full development guidelines, see [CONTRIBUTING.md](contributing.md).

---

## Prerequisites

| Requirement | Why | Install |
| --- | --- | --- |
| **NVIDIA Jetson Orin NX** | Edge GPU for real-time inference | [Yahboom dev board](https://www.yahboom.net/) or similar |
| **JetPack + L4T** | CUDA and cuDNN for the board | The version this project targets is recorded in [`platform/jetson-orin-nx-yahboom/README.md`](https://github.com/scottchronicity/orpheus/blob/main/platform/jetson-orin-nx-yahboom/README.md) — that file is the authority for the board's OS and JetPack, and this page does not restate it |
| **Python 3.9.x** | Every component pins `>=3.9, <3.10` | See the note below |
| **libportaudio2** | Audio I/O (sounddevice) | `sudo apt install libportaudio2` |
| **libsndfile1** | Audio file reading/writing | `sudo apt install libsndfile1` |
| **mosquitto** (optional) | Only for the `mqtt` fallback backplane — the default NATS broker is downloaded by the backplane's `make install` | `sudo apt install mosquitto mosquitto-clients` |
| **Git LFS** | ML model storage | `sudo apt install git-lfs && git lfs install` |
| **Node.js 20+** | Only for a developer-style `make install` — `make install-service` fetches its own Node. See [Node.js: what needs it, and when](ORPHEUS_UI.md#nodejs-what-needs-it-and-when) | `curl -fsSL https://deb.nodesource.com/setup_20.x \| sudo -E bash - && sudo apt install nodejs` |
| **ffmpeg** | Timelapse video generation | `sudo apt install ffmpeg` |

> **Where `python3.9` comes from.** The Makefiles look for an interpreter named
> `python3.9` on `PATH` (`PYTHON_SYSTEM`, default `python3.9`) and require at
> least 3.9.5 (`PYTHON_REQUIRED_VERSION`). If your JetPack image already ships
> one, use it — a system interpreter built for the board is the one that carries
> working CUDA and cuDNN bindings, and replacing it is how people break GPU
> inference. If it does not ship one, install 3.9.5 with uv and point the build
> at it: `uv python install 3.9.5` then
> `export PYTHON_SYSTEM=$(uv python find 3.9.5)`. Check which case you are in
> before you start: `python3.9 --version`.

---

## Clone and Install

```bash
cd ~
git clone https://github.com/scottchronicity/orpheus.git
cd orpheus
git lfs pull          # Fetch ML models (~1.5 GB)
make install          # Create venvs, install all dependencies
```

This creates a Python virtual environment inside each component directory. Expect 5–10 minutes for the first install.

Verify:

```bash
make test-common      # Should pass
```

---

## Configure

Orpheus uses one canonical config (`config/orpheus.example.yaml`). On a production box
it lives at `/opt/orpheus/config/orpheus.yaml` — the first path in the search order, and
the one every runbook edits:

```bash
sudo mkdir -p /opt/orpheus/config
sudo cp config/orpheus.example.yaml /opt/orpheus/config/orpheus.yaml
sudo nano /opt/orpheus/config/orpheus.yaml
```

> **Note:** installing the platform library (Production Mode below) seeds this same
> file for you if it does not exist yet, and leaves it alone if it does — so doing it
> by hand now just lets you edit before anything starts. Every component resolves the
> config the same way: `$ORPHEUS_CONFIG_PATH` if you set it, then
> `/opt/orpheus/config/orpheus.yaml`, then `/etc/orpheus/orpheus.yaml`. Keep one copy.
> A stale `/etc/orpheus/orpheus.yaml` left over from an older install is harmless while
> the `/opt` copy exists, but delete it rather than editing it — every runbook, and the
> rollback procedure, assume the `/opt` copy is the live one.

Key settings to review:

| Setting | What to check |
| --- | --- |
| `site.lat` / `site.lon` | Your deployment coordinates |
| `cameras.auth` | RTSP camera credentials |
| `cameras.orpheus-eye-*` | Camera hostnames — update to match your network |
| `audio.channels` | Verify Behringer UMC404HD channel mapping |
| `storage.base_path` | Default `/data/orpheus` — ensure the drive is mounted |

### Storage setup

Orpheus writes audio clips, video, snapshots, and detection data continuously. An external SSD is recommended.

```bash
# Example: Samsung T7 mounted at /data
sudo mkdir -p /data/orpheus
sudo chown $USER:$USER /data/orpheus
```

Ensure `storage.base_path` in your config points to this path.

---

## Development Mode

Run agents directly from the repo (foreground, no systemd):

```bash
cd agents/orpheus-agent-audio-motion
make install       # Create venv, install deps
make run           # Run in foreground (Ctrl+C to stop)
make test          # Run tests
```

For development, point agents to the repo config:

```bash
export ORPHEUS_CONFIG_PATH="$(pwd)/config/orpheus.example.yaml"
```

---

## Production Mode (systemd)

For persistent, auto-starting services that survive reboots.

Run `make` as your normal user — never `sudo make`. Targets that need
root (like `install-service`) invoke `sudo` internally for just those
steps, and `make install` actively rejects running as root.

### 1. Install the platform library first

```bash
cd ~/orpheus/platform/orpheus-common
make install-service
```

This installs the shared library to `/opt/orpheus/platform/orpheus-common` and deploys the default config to `/opt/orpheus/config/`.

### 2. Install services

```bash
# Messaging backplane (NATS + JetStream by default; BACKPLANE_BROKER=mqtt for mosquitto)
cd ~/orpheus/services/orpheus-backplane
make install    # installs, enables + starts orpheus-backplane

# Dashboard
cd ~/orpheus/services/orpheus_ui
make install-service
sudo systemctl start orpheus-ui
```

### 3. Install agents

On a station, install the whole set in one line:

```bash
cd ~/orpheus
make services-install    # every component, including audio-events, audio-playback,
                         # gps and bluetooth-autoconnect, which the list below omits
make services-start
```

The per-component sequence below is the alternative for installing a subset
deliberately. Note that it leaves out `audio-events` — the PANNs classifier —
so a station built from it alone identifies birds but not other sounds.

```bash
# Audio motion detection
cd ~/orpheus/agents/orpheus-agent-audio-motion
make install-service
sudo systemctl start orpheus-agent-audio-motion

# General sound classification (PANNs / AudioSet)
cd ~/orpheus/agents/orpheus-agent-audio-events
make install-service
sudo systemctl start orpheus-agent-audio-events

# Bird detection (BirdNET ONNX)
cd ~/orpheus/agents/orpheus-agent-bird-detection
make install-service
sudo systemctl start orpheus-agent-bird-detection

# Crow detection (AVES classifier)
cd ~/orpheus/agents/orpheus-agent-crow-detection
make install-service
sudo systemctl start orpheus-agent-crow-detection

# Video motion detection
cd ~/orpheus/agents/orpheus-agent-video-motion
make install-service
sudo systemctl start orpheus-agent-video-motion

# Video snapshotter (periodic camera images)
cd ~/orpheus/agents/orpheus-agent-video-snapshotter
make install-service
sudo systemctl start orpheus-agent-video-snapshotter

# Video timelapser (generates timelapses from snapshots)
cd ~/orpheus/agents/orpheus-agent-video-timelapser
make install-service
sudo systemctl start orpheus-agent-video-timelapser

# Event correlator (fuses detections into entity-level events)
cd ~/orpheus/agents/orpheus-agent-event-correlator
make install-service
sudo systemctl start orpheus-agent-event-correlator
```

### Managing services

```bash
# Check status of all Orpheus services
systemctl list-units 'orpheus-*' --type=service

# View logs
sudo journalctl -u orpheus-agent-audio-motion -f
sudo journalctl -u orpheus-ui -f

# Restart a service after config change
sudo systemctl restart orpheus-agent-audio-motion

# Stop everything
sudo systemctl stop 'orpheus-*'
```

---

## See It Work

1. Open `http://<jetson-ip>:8082` in a browser (the Orpheus UI).

   When the dashboard opens it asks you to sign in. The seeded accounts and the
   environment variables that set their passwords are documented in
   [Signing in to the dashboard](INSTALLATION.md#signing-in-to-the-dashboard) — set
   those before you expose this to anyone else.

2. Make some noise near the microphones — audio motion events should appear within seconds.
3. If cameras are connected, video motion and snapshots will populate automatically.
4. BirdNET identifications appear when bird calls are detected.

> **Note:** BirdNET runs on the CPU everywhere, the Jetson included: it is an
> ONNX model and the session is built with the default CPU provider. Expect a
> couple of seconds per clip. The GPU is used by the two torch models,
> crow-detection and audio-events, which take a `device` setting.

---

## Updating

```bash
cd ~/orpheus
git pull
git lfs pull

# Update platform library
cd platform/orpheus-common
make install-service

# Update an agent
cd ~/orpheus/agents/orpheus-agent-audio-motion
make install-service
sudo systemctl restart orpheus-agent-audio-motion
```

---

## Troubleshooting

### Service won't start

```bash
sudo systemctl status orpheus-agent-audio-motion
sudo journalctl -u orpheus-agent-audio-motion -n 50 --no-pager
```

### orpheus-common not found

Ensure you installed the platform library first:

```bash
cd ~/orpheus/platform/orpheus-common
make install-service
```

### No audio input device

Check the Behringer UMC404HD is connected and recognized:

```bash
arecord -l                          # List ALSA capture devices
cat /proc/asound/cards              # Check sound cards
```

### Config file not found

The full search order is documented once, in
[Installation](INSTALLATION.md#config-file-not-found) — it begins with
`$ORPHEUS_CONFIG_PATH` and `$ORPHEUS_CONFIG_DIR`, and notes that there is no
`~/.config/orpheus/` lookup.

### Permission errors

Services run as the `orpheus` user. Check permissions on the storage path:

```bash
ls -la /data/orpheus/
sudo chown -R orpheus:orpheus /data/orpheus/
```

### Camera RTSP connection failures

```bash
# Test RTSP connectivity
ffprobe "rtsp://orpheus:orpheus-station-2025@orpheus-eye-1:554/cam/realmonitor?channel=1&subtype=0"
```

Check that cameras are powered, on the same network, and credentials are correct in `/opt/orpheus/config/orpheus.yaml`.

---

## Quick Reference

```bash
# Development
make install                    # Install all components
make test                       # Run all tests
make clean                      # Remove all venvs

# Single agent
cd agents/orpheus-agent-audio-motion
make run                        # Run in foreground
make test                       # Run tests

# Production (systemd)
make install-service            # Install systemd unit (from agent/service dir)
systemctl list-units 'orpheus-*' --type=service
sudo journalctl -u <service> -f
sudo systemctl restart <service>
```

---

*For full development guidelines, see [CONTRIBUTING.md](contributing.md). For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md). For detailed installation steps, see [INSTALLATION.md](INSTALLATION.md).*
