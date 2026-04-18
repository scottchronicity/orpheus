# Linux Quick Start

> ⚠️ **Untested guide.** Orpheus has been tested on macOS and NVIDIA Jetson
> Orin NX. This Linux guide is our best guess at what *should* work — no one
> has actually run it end-to-end yet. Expect rough edges. If you hit one,
> please open an issue or PR so the next person has a better time. We
> thought an imperfect starting point was friendlier than no guide at all.

Get the Orpheus Observe stack running on desktop/laptop Linux in ~15 minutes. This guide targets **development and demo** use — production/systemd deployment is only documented for Jetson today (see [Jetson Quick Start](JETSON_QUICKSTART.md)).

For macOS development, see [macOS Quick Start](MACOS_QUICKSTART.md). For Windows (WSL2), see [Windows Quick Start](WINDOWS_QUICKSTART.md). For full development guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Prerequisites

Instructions below assume **Ubuntu 22.04 / Debian 12** (apt). Fedora (`dnf`), Arch (`pacman`), and openSUSE (`zypper`) all ship equivalent packages under slightly different names — adapt as needed. If you work out a clean recipe for another distro, please PR it.

| Requirement | Why | Install (apt) |
| --- | --- | --- |
| **make** | Build automation | `sudo apt install make` |
| **libportaudio2** | Audio I/O (sounddevice) | `sudo apt install libportaudio2` |
| **libsndfile1** | Audio file reading/writing | `sudo apt install libsndfile1` |
| **mosquitto** | MQTT broker | `sudo apt install mosquitto mosquitto-clients` |
| **Git LFS** | ML model storage | `sudo apt install git-lfs && git lfs install` |
| **ffmpeg** | Timelapse video generation | `sudo apt install ffmpeg` |
| **build-essential** | Compile native Python extensions | `sudo apt install build-essential` |

### Python 3.9.5 via uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv python install 3.9.5
uv python find 3.9.5    # Should print the path to the installed interpreter
```

The repo's `.python-version` file tells uv (and the Makefiles) which version to use.

> **Note:** On Jetson, you use the system Python 3.9.5 from JetPack (which carries CUDA/cuDNN bindings). On generic Linux without a CUDA-aware Python, uv-managed 3.9.5 is the right default — see [Jetson Quick Start](JETSON_QUICKSTART.md) if you're on NVIDIA hardware.

---

## Clone and Install

```bash
git clone https://github.com/scottchronicity/orpheus.git
cd orpheus
git lfs pull          # Fetch ML models (~500MB)
make install          # Create venvs, install all dependencies
```

This creates a Python virtual environment inside each component directory. Expect 5–10 minutes for the first install (model downloads + compilation of native extensions).

Verify:

```bash
make test-common      # Should pass
```

---

## Configure for Linux

Orpheus uses one canonical config (`config/orpheus.example.yaml`). Linux-specific overrides go in a small `.env` file.

```bash
cp config/.env.orpheus.example config/.env.orpheus
$EDITOR config/.env.orpheus
```

### Likely overrides

| Setting | Jetson Default | Linux Override | Reason |
| --- | --- | --- | --- |
| Audio channels | 4-channel Behringer UMC404HD | Single mic (laptop/USB) | Most desktop Linux boxes have one mic |
| Storage path | `/data/orpheus` | `~/data/orpheus` | Avoid needing root for a dev setup |
| Sample rate | 48000 Hz | (optional) 44100 Hz | Match your input device |

Everything else — cameras, MQTT, retention, dashboard, bird detection — is identical across environments.

### Camera credentials

The video agents connect to cameras over **RTSP** on your LAN. The config ships with 4 cameras pre-configured (`orpheus-eye-1` through `orpheus-eye-4`) using credentials `orpheus` / `orpheus-station-2025`. Without RTSP cameras the video agents start but stay idle — everything else (audio, bird/crow classification, event correlation, UI) works without them.

### Running individual agents (without dev-stack)

```bash
export ORPHEUS_CONFIG_PATH="$(pwd)/config/orpheus.example.yaml"
cd agents/orpheus-agent-audio-motion
make run
```

---

## Run the Stack

```bash
make dev-stack
```

Starts all Observe components as **background processes**:

| # | Service | What it does |
| --- | --- | --- |
| 1 | **mosquitto** | MQTT broker (checks if already running) |
| 2 | **audio-motion** | Captures from mic, detects sound events |
| 3 | **audio-playback** | Plays deterrent/test audio |
| 4 | **bird-detection** | BirdNET ONNX inference on audio clips |
| 5 | **crow-detection** | AVES classifier (skipped if model missing) |
| 6 | **video-motion** | RTSP video motion detection |
| 7 | **video-snapshotter** | Periodic RTSP snapshots |
| 8 | **video-timelapser** | Timelapse generation from snapshots |
| 9 | **event-correlator** | Fuses detections into entity-level events |
| 10 | **gps** | GPS/location service |
| 11 | **orpheus-ui-backend** | FastAPI API at [http://localhost:8082](http://localhost:8082) |
| 12 | **orpheus-ui-frontend** | Vite/React dev server at [http://localhost:5173](http://localhost:5173) |

Models are stored in `~/data/orpheus/models/`. On first run, `dev-stack` symlinks them from `artifacts/models/` (fetched by `git lfs pull`).

Each component logs to `logs/` and PIDs are tracked in `.dev-stack/pids/`.

### Managing the stack

```bash
make dev-status                       # Show what's running
make dev-logs                         # Tail all service logs
make dev-logs SVC=orpheus-ui-backend  # Tail one service
make dev-stop                         # Stop everything
make dev-restart                      # Restart everything
make dev-restart SVC=bird-detection   # Restart one service
```

---

## See It Work

1. Open [http://localhost:5173](http://localhost:5173).
2. Play a YouTube video of bird calls near your mic.
3. Within 10–20 seconds you should see audio motion events and BirdNET identifications in the UI.

> **Note:** CPU inference on a typical laptop/desktop is 2–10x slower than the Jetson Orin NX. Expect BirdNET results in 2–10 seconds per clip. If you have an NVIDIA GPU, the ONNX runtime can use it — GPU acceleration on non-Jetson Linux isn't documented here; contributions welcome.

---

## Known Limitations

| Limitation | Impact | Workaround |
| --- | --- | --- |
| No GPU acceleration path documented | CPU inference is slow | See [Jetson Quick Start](JETSON_QUICKSTART.md) for CUDA/cuDNN setup; adapt for your hardware |
| `audio-playback` uses `afplay` on Mac | Won't work on Linux out of the box | Likely needs a Linux audio player (`paplay`, `aplay`, `mpv`) — unverified, probably needs an agent patch |
| systemd production path is Jetson-tuned | Services' `install.sh` scripts may not work cleanly on non-Jetson Linux | Use `make dev-stack` for development; adapt `systemd/install.sh` per-service if you need production |
| Bluetooth auto-connect is Jetson-focused | `orpheus-bluetooth-autoconnect` may not work on your distro | Disable or skip the service if Bluetooth isn't needed |
| Package names vary by distro | `libportaudio2` / `libsndfile1` are Debian/Ubuntu names | Fedora: `portaudio-devel`, `libsndfile`. Arch: `portaudio`, `libsndfile`. |

---

## Troubleshooting

### Python version mismatch

```bash
ERROR: Python 3.9.5+ required, found 3.12.x
```

If you installed Python via uv, the Makefiles should find it automatically. If not:

```bash
export PYTHON_SYSTEM=$(uv python find 3.9.5)
make clean && make install
```

### portaudio / libsndfile missing

```bash
ImportError: No module named 'sounddevice' / could not find portaudio
```

```bash
sudo apt install libportaudio2 libsndfile1
make clean && make install
```

On Fedora: `sudo dnf install portaudio libsndfile`. On Arch: `sudo pacman -S portaudio libsndfile`.

### MQTT connection refused

```bash
Connection refused: localhost:1883
```

Mosquitto isn't running:

```bash
sudo systemctl start mosquitto
# or foreground:
mosquitto -v
```

### No audio input device

List ALSA capture devices:

```bash
arecord -l
cat /proc/asound/cards
```

If nothing shows up, your user may not be in the `audio` group:

```bash
sudo usermod -a -G audio $USER
# log out and back in
```

If you use PulseAudio/PipeWire, `pactl list sources` shows the sources Python will see via `sounddevice`.

### BirdNET model not found

```bash
FileNotFoundError: birdnet.onnx not found
```

```bash
git lfs pull
```

### UI shows no events

1. Verify MQTT is seeing traffic: `mosquitto_sub -t '#' -v`
2. Check audio-motion logs: `cat logs/audio-motion.log`
3. Confirm your mic is picking up sound: `arecord -d 5 -f cd test.wav && aplay test.wav`

### `make install` fails compiling numpy/scipy

```bash
sudo apt install build-essential python3-dev
make clean && make install
```

---

## Quick Reference

```bash
make dev-stack          # Start everything (background)
make dev-status         # See what's running
make dev-logs           # Tail all logs
make dev-stop           # Stop everything
make dev-restart        # Restart everything
make install            # Install/reinstall all components
make test               # Run all tests
make clean              # Remove all venvs (full reinstall)

# Individual agents
make dev-restart SVC=bird-detection
make dev-logs SVC=dashboard
cd agents/orpheus-agent-audio-motion
make run                # Run single agent (foreground)
make test               # Test single agent
```

---

*For full development guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md). For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md). For Jetson/production deployment, see [INSTALLATION.md](INSTALLATION.md) and [Jetson Quick Start](JETSON_QUICKSTART.md).*
