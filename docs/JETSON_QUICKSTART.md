# Jetson Quick Start

Get the Orpheus Observe stack running on an NVIDIA Jetson Orin NX. This guide covers both **development** (run from the repo) and **production** (systemd services under `/opt/orpheus`).

For macOS development, see [macOS Quick Start](MACOS_QUICKSTART.md). For Windows (WSL2), see [Windows Quick Start](WINDOWS_QUICKSTART.md) (untested). For generic Linux, see [Linux Quick Start](LINUX_QUICKSTART.md) (untested). For full development guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Prerequisites

| Requirement | Why | Install |
| --- | --- | --- |
| **NVIDIA Jetson Orin NX** | Edge GPU for real-time inference | [Yahboom dev board](https://www.yahboom.net/) or similar |
| **JetPack 5.x** | Provides Python 3.9.5, CUDA, cuDNN | [NVIDIA JetPack](https://developer.nvidia.com/embedded/jetpack) |
| **Python 3.9.5** | System Python from JetPack (do NOT replace) | Included with JetPack |
| **libportaudio2** | Audio I/O (sounddevice) | `sudo apt install libportaudio2` |
| **libsndfile1** | Audio file reading/writing | `sudo apt install libsndfile1` |
| **mosquitto** | MQTT broker | `sudo apt install mosquitto mosquitto-clients` |
| **Git LFS** | ML model storage | `sudo apt install git-lfs && git lfs install` |
| **ffmpeg** | Timelapse video generation | `sudo apt install ffmpeg` |

> **Important:** The system Python 3.9.5 from JetPack carries CUDA and cuDNN bindings. Do **not** install Python via pyenv, uv, or conda on the Jetson — always use the system interpreter. The Makefiles detect this automatically.

---

## Clone and Install

```bash
cd ~
git clone https://github.com/scottchronicity/orpheus.git
cd orpheus
git lfs pull          # Fetch ML models (~500MB)
make install          # Create venvs, install all dependencies
```

This creates a Python virtual environment inside each component directory. Expect 5–10 minutes for the first install.

Verify:

```bash
make test-common      # Should pass
```

---

## Configure

Orpheus uses one canonical config (`config/orpheus.example.yaml`). Copy it to the system config location:

```bash
sudo mkdir -p /etc/orpheus
sudo cp config/orpheus.example.yaml /etc/orpheus/orpheus.yaml
sudo nano /etc/orpheus/orpheus.yaml
```

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

### 1. Install the platform library first

```bash
cd ~/orpheus/platform/orpheus-common
sudo ./systemd/install.sh
```

This installs the shared library to `/opt/orpheus/platform/orpheus-common` and deploys the default config to `/opt/orpheus/config/`.

### 2. Install services

```bash
# MQTT broker
cd ~/orpheus/services/orpheus-mqtt
sudo make install-service
sudo systemctl start orpheus-mqtt

# Dashboard
cd ~/orpheus/services/orpheus-dashboard
sudo make install-service
sudo systemctl start orpheus-dashboard
```

### 3. Install agents

```bash
# Audio motion detection
cd ~/orpheus/agents/orpheus-agent-audio-motion
sudo make install-service
sudo systemctl start orpheus-agent-audio-motion

# Bird detection (BirdNET ONNX)
cd ~/orpheus/agents/orpheus-agent-bird-detection
sudo make install-service
sudo systemctl start orpheus-agent-bird-detection

# Crow detection (AVES classifier)
cd ~/orpheus/agents/orpheus-agent-crow-detection
sudo make install-service
sudo systemctl start orpheus-agent-crow-detection

# Video motion detection
cd ~/orpheus/agents/orpheus-agent-video-motion
sudo make install-service
sudo systemctl start orpheus-agent-video-motion

# Video snapshotter (periodic camera images)
cd ~/orpheus/agents/orpheus-agent-video-snapshotter
sudo make install-service
sudo systemctl start orpheus-agent-video-snapshotter

# Video timelapser (generates timelapses from snapshots)
cd ~/orpheus/agents/orpheus-agent-video-timelapser
sudo make install-service
sudo systemctl start orpheus-agent-video-timelapser

# Event correlator (fuses detections into entity-level events)
cd ~/orpheus/agents/orpheus-agent-event-correlator
sudo make install-service
sudo systemctl start orpheus-agent-event-correlator
```

### Managing services

```bash
# Check status of all Orpheus services
systemctl list-units 'orpheus-*' --type=service

# View logs
sudo journalctl -u orpheus-agent-audio-motion -f
sudo journalctl -u orpheus-dashboard -f

# Restart a service after config change
sudo systemctl restart orpheus-agent-audio-motion

# Stop everything
sudo systemctl stop 'orpheus-*'
```

---

## See It Work

1. Open `http://<jetson-ip>:8080` in a browser (diagnostic dashboard).
2. Make some noise near the microphones — audio motion events should appear within seconds.
3. If cameras are connected, video motion and snapshots will populate automatically.
4. BirdNET identifications appear when bird calls are detected.

> **Note:** GPU inference on the Jetson Orin NX is significantly faster than CPU on a laptop — expect BirdNET results in under 1 second.

---

## Updating

```bash
cd ~/orpheus
git pull
git lfs pull

# Update platform library
cd platform/orpheus-common
sudo ./systemd/install.sh

# Update an agent
cd ~/orpheus/agents/orpheus-agent-audio-motion
sudo make install-service
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
sudo ./systemd/install.sh
```

### No audio input device

Check the Behringer UMC404HD is connected and recognized:

```bash
arecord -l                          # List ALSA capture devices
cat /proc/asound/cards              # Check sound cards
```

### Config file not found

The system looks for config in this order:

1. `ORPHEUS_CONFIG_PATH` environment variable
2. `/etc/orpheus/orpheus.yaml`
3. `config/orpheus.yaml` (relative to cwd)

### Permission errors

Services run as the `orpheus` user. Check permissions on the storage path:

```bash
ls -la /data/orpheus/
sudo chown -R orpheus:orpheus /data/orpheus/
```

### Camera RTSP connection failures

```bash
# Test RTSP connectivity
ffprobe rtsp://orpheus:orpheus-station-2025@orpheus-eye-1/cam/realmonitor?channel=1&subtype=1
```

Check that cameras are powered, on the same network, and credentials are correct in `/etc/orpheus/orpheus.yaml`.

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
sudo make install-service       # Install systemd unit (from agent/service dir)
systemctl list-units 'orpheus-*' --type=service
sudo journalctl -u <service> -f
sudo systemctl restart <service>
```

---

*For full development guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md). For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md). For detailed installation steps, see [INSTALLATION.md](INSTALLATION.md).*
