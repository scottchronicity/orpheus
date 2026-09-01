# Linux Quick Start

> ⚠️ **Untested guide.** Orpheus has been tested on macOS and NVIDIA Jetson
> Orin NX. This Linux guide is our best guess at what *should* work — no one
> has actually run it end-to-end yet. Expect rough edges. If you hit one,
> please open an issue or PR so the next person has a better time. We
> thought an imperfect starting point was friendlier than no guide at all.

Get the Orpheus Observe stack running on desktop/laptop Linux in ~15 minutes. This guide targets **development and demo** use — production/systemd deployment is only documented for Jetson today (see [Jetson Quick Start](JETSON_QUICKSTART.md)).

For macOS development, see [macOS Quick Start](MACOS_QUICKSTART.md). For Windows (WSL2), see [Windows Quick Start](WINDOWS_QUICKSTART.md). For full development guidelines, see [CONTRIBUTING.md](contributing.md).

---

## Prerequisites

Instructions below assume **Ubuntu 22.04 / Debian 12** (apt). Fedora (`dnf`), Arch (`pacman`), and openSUSE (`zypper`) all ship equivalent packages under slightly different names — adapt as needed. If you work out a clean recipe for another distro, please PR it.

| Requirement | Why | Install (apt) |
| --- | --- | --- |
| **make** | Build automation | `sudo apt install make` |
| **libportaudio2** | Audio I/O (sounddevice) | `sudo apt install libportaudio2` |
| **libsndfile1** | Audio file reading/writing | `sudo apt install libsndfile1` |
| **nats-server** | Event-bus broker (NATS + JetStream) | **not** a prerequisite — see the note under this table |
| **Git LFS** | ML model storage | `sudo apt install git-lfs && git lfs install` |
| **Node.js 20+** | Building the dashboard frontend — see [Node.js: what needs it, and when](ORPHEUS_UI.md#nodejs-what-needs-it-and-when) | `curl -fsSL https://deb.nodesource.com/setup_20.x \| sudo -E bash - && sudo apt install nodejs` |
| **ffmpeg** | Timelapse video generation | `sudo apt install ffmpeg` |
| **build-essential** | Compile native Python extensions | `sudo apt install build-essential` |

> **The broker is installed after you clone, not before.** `make install-backbone`
> is a target in this repository, so it cannot run until the Clone and Install
> section below, and its first action builds a Python venv — which needs the 3.9.5
> you are about to install. Run it once both of those are done, or drop the pinned
> `nats-server` binary (2.10.22) on your `PATH` yourself and let `make dev-stack`
> start it.

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
git lfs pull          # Fetch ML models (~1.5 GB)
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

**Set the dashboard passwords now, in this file.** The accounts are seeded the
first time the UI starts, and seeding is guarded on an empty user table — so
once `make dev-stack` has run, adding these rotates nothing and you have to
delete the accounts database to change them. Add to `config/.env.orpheus`:

```bash
ORPHEUS_UI_ADMIN_PASSWORD=<a long random password>
ORPHEUS_UI_GUEST_PASSWORD=<another one>
```

Full detail, including the email variables and how to recover if the UI has
already started: [Signing in to the dashboard](INSTALLATION.md#signing-in-to-the-dashboard).

### Likely overrides

| Setting | Jetson Default | Linux Override | Reason |
| --- | --- | --- | --- |
| Audio channels | 4-channel Behringer UMC404HD | Single mic (laptop/USB) | Most desktop Linux boxes have one mic |
| Storage path | `/data/orpheus` | `~/data/orpheus` | Avoid needing root for a dev setup |
| Sample rate | 48000 Hz | (optional) 44100 Hz | Match your input device |

Everything else — cameras, the event bus, retention, dashboard, bird detection — is identical across environments.

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
| 1 | **backplane** | NATS + JetStream broker (adopts an already-running `nats-server`) |
| 2 | **audio-motion** | Captures from mic, detects sound events |
| 3 | **audio-events** | PANNs sound-event classifier (AudioSet ontology) |
| 4 | **audio-playback** | Plays deterrent/test audio (`ffplay` by default) |
| 5 | **bird-detection** | BirdNET ONNX inference on audio clips |
| 6 | **crow-detection** | AVES classifier (skipped if model missing) |
| 7 | **video-motion** | RTSP video motion detection |
| 8 | **video-snapshotter** | Periodic RTSP snapshots |
| 9 | **video-timelapser** | Timelapse generation from snapshots |
| 10 | **event-correlator** | Fuses detections into entity-level events |
| 11 | **gps** | GPS/location service |
| 12 | **orpheus-ui-backend** | FastAPI API at [http://localhost:8082](http://localhost:8082) |
| 13 | **orpheus-ui-frontend** | Vite/React dev server at [http://localhost:5173](http://localhost:5173) |

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

   When the dashboard opens it asks you to sign in. The seeded accounts and the
   environment variables that set their passwords are documented in
   [Signing in to the dashboard](INSTALLATION.md#signing-in-to-the-dashboard) — set
   those before you expose this to anyone else.

2. Play a YouTube video of bird calls near your mic.
3. Within 10–20 seconds you should see audio motion events and BirdNET identifications in the UI.

> **Note:** Expect BirdNET results in a few seconds per clip. BirdNET runs on
> the CPU on every platform — it ships as ONNX against the CPU-only runtime, so
> an NVIDIA card does not change it. Putting it on a GPU would need the
> `onnxruntime-gpu` package and a code change to request the provider;
> contributions welcome. The two torch models do use a GPU where one is
> available.

---

## Known Limitations

| Limitation | Impact | Workaround |
| --- | --- | --- |
| No GPU path for BirdNET | BirdNET is CPU-only on every platform, so it is the slowest step | Nothing to configure; the two torch models use a GPU if one is present |
| systemd production path is Jetson-tuned | Services' `install.sh` scripts may not work cleanly on non-Jetson Linux | Use `make dev-stack` for development; adapt `systemd/install.sh` per-service if you need production |
| Bluetooth auto-connect is Jetson-focused | `orpheus-bluetooth-autoconnect` may not work on your distro | Disable or skip the service if Bluetooth isn't needed |
| Package names vary by distro | `libportaudio2` / `libsndfile1` are Debian/Ubuntu names | Fedora: `portaudio-devel`, `libsndfile`. Arch: `portaudio`, `libsndfile`. |

---

## Troubleshooting

### Python version mismatch

```
❌ Python interpreter 'python3.9' not found.
   Run: uv python install 3.9.5
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

### Event-bus connection refused

```bash
nats: no servers available for connection    # or: Connection refused: 127.0.0.1:4222
```

The NATS backplane isn't running. `make dev-stack` starts it automatically
(or adopts an already-running `nats-server`); to run just the broker:

```bash
make -C services/orpheus-backplane run   # the genuinely minimal path.
# `make dev-stack SVC=backplane` runs the full preflight first, so it still
# needs nats-server on PATH and every component venv present.
# then check its log:
cat logs/backplane.log
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

1. Verify the backplane is up: `make dev-status`; `cat logs/backplane.log` shows "Server is ready"
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
make dev-logs SVC=orpheus-ui-backend
cd agents/orpheus-agent-audio-motion
make run                # Run single agent (foreground)
make test               # Test single agent
```

---

*For full development guidelines, see [CONTRIBUTING.md](contributing.md). For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md). For Jetson/production deployment, see [INSTALLATION.md](INSTALLATION.md) and [Jetson Quick Start](JETSON_QUICKSTART.md).*
