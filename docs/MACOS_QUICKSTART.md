# macOS Quick Start

Get the Orpheus Observe stack running on your Mac in ~15 minutes. This guide is self-contained — you do not need to read anything else to reach a working dashboard with live detections.

For full development guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md) and [CODING_AGENT_CONTEXT.md](../CODING_AGENT_CONTEXT.md).

---

## Prerequisites

| Requirement | Why | Install |
| --- | --- | --- |
| **make** | Build automation (used everywhere) | `xcode-select --install` |
| **uv** | Python version & package manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Homebrew** | Package manager | [brew.sh](https://brew.sh) |
| **portaudio** | Audio I/O (PyAudio/sounddevice) | `brew install portaudio` |
| **libsndfile** | Audio file reading/writing | `brew install libsndfile` |
| **mosquitto** | MQTT broker | `brew install mosquitto` |
| **Git LFS** | ML model storage | `brew install git-lfs && git lfs install` |
| **ffmpeg** | Timelapse video generation (optional) | `brew install ffmpeg` |

> **Note on `make`:** This repo uses `make` extensively — nearly every workflow (`make install`, `make test`, `make dev-stack`, etc.) goes through it. On macOS, `make` is bundled with the Xcode Command Line Tools and is **not installed by default**. Run `xcode-select --install` and follow the prompts. If you already have Xcode installed, you may already have it — verify with `make --version`.

### Install Python 3.9.5 via uv

```bash
uv python install 3.9.5
```

That's it. uv downloads a standalone CPython 3.9.5 build and manages it for you. The repo's `.python-version` file tells uv (and the Makefiles) which version to use.

Verify:

```bash
uv python find 3.9.5    # Should print the path to the installed interpreter
```

#### Alternatives

<details>
  <summary>Click here for alternative python installs</summary>

##### Pyenv

If you prefer pyenv:

```bash
brew install pyenv
echo 'eval "$(pyenv init -)"' >> ~/.zshrc
source ~/.zshrc

pyenv install 3.9.5
pyenv local 3.9.5
python3 --version   # Should show 3.9.5
```

Then set `PYTHON_SYSTEM` so the Makefiles find it:

```bash
export PYTHON_SYSTEM=$(pyenv which python3)
```

</details>

---

## Clone and Install

```bash
git clone https://github.com/scottchronicity/orpheus.git
cd orpheus
git lfs pull          # Fetch ML models (~500MB)
make install          # Create venvs, install all dependencies
```

This creates a Python virtual environment inside each component directory. Expect 5–10 minutes for the first install (model downloads + compilation of native extensions).

Verify the install:

```bash
make test-common      # Should pass
```

---

## Configure for macOS

Orpheus uses one canonical config (`config/orpheus.example.yaml`) for all environments. macOS-specific overrides go in a small `.env` file.

### Quick setup

```bash
cp config/.env.orpheus.example config/.env.orpheus
$EDITOR config/.env.orpheus
```

`make dev-stack` loads the Jetson config automatically. OrpheusConfig picks up `config/.env.orpheus` and applies your overrides on top.

### What the `.env` overrides (and why)

| Setting | Jetson Default | macOS Override | Reason |
| --- | --- | --- | --- |
| Audio channels | 4-channel Behringer UMC404HD | Single laptop mic | MacBooks have one mic |
| Storage path | `/data/orpheus` | `~/data/orpheus` | No root partition on Mac |
| Sample rate | 48000 Hz | (optional) 44100 Hz | Some Mac mics don't support 48kHz |

Everything else — cameras, MQTT, retention, dashboard, bird detection — is identical across environments.

### Camera credentials

The video agents connect to cameras over **RTSP**. They do **not** use the Mac's built-in camera — you need network-accessible RTSP cameras (like the Amcrest IP5M-B1186EW cameras used in production).

The config ships with 4 cameras pre-configured (`orpheus-eye-1` through `orpheus-eye-4`) using credentials `orpheus` / `orpheus-station-2025`.

If you **don't** have access to RTSP cameras, the video agents will start but remain idle. Everything else (audio detection, bird/crow classification, event correlation, the UI) works without them.

### Running individual agents (without dev-stack)

If you want to run a single agent outside of `make dev-stack`, point it to the config:

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

This starts all Observe stack components as **background processes**:

| # | Service | What it does |
| --- | --- | --- |
| 1 | **mosquitto** | MQTT broker (checks if already running) |
| 2 | **audio-motion** | Captures from laptop mic, detects sound events |
| 3 | **audio-playback** | Plays deterrent/test audio via `afplay` |
| 4 | **bird-detection** | BirdNET ONNX inference on audio clips (skipped if model missing) |
| 5 | **crow-detection** | AVES classifier (skipped if model missing) |
| 6 | **video-motion** | RTSP video motion detection |
| 7 | **video-snapshotter** | Periodic RTSP snapshots |
| 8 | **video-timelapser** | Timelapse generation from snapshots |
| 9 | **event-correlator** | Fuses detections into entity-level events |
| 10 | **gps** | GPS/location service |
| 11 | **orpheus-ui-backend** | FastAPI API server at [http://localhost:8082](http://localhost:8082) |
| 12 | **orpheus-ui-frontend** | Vite/React dev server at [http://localhost:5173](http://localhost:5173) |

Models are stored in `~/data/orpheus/models/`. On first run, `dev-stack` automatically symlinks them from `artifacts/models/` (fetched by `git lfs pull`).

Each component logs to its own file in `logs/` and PIDs are tracked in `.dev-stack/pids/`.

### Managing the stack

```bash
make dev-status                       # Show what's running
make dev-logs                         # Tail all service logs
make dev-logs SVC=orpheus-ui-backend  # Tail just the UI backend log
make dev-stop                         # Stop everything
make dev-restart                      # Restart everything
make dev-restart SVC=bird-detection   # Restart just bird-detection
```

---

## See It Work

1. Open [http://localhost:5173](http://localhost:5173) in your browser.
2. Play a YouTube video of bird calls near your laptop (search "bird calls identification") e.g. [https://www.youtube.com/watch?v=K3OdL-lAjeM](https://www.youtube.com/watch?v=K3OdL-lAjeM).
3. Within 10–20 seconds, you should see:
   - Audio motion events appearing in the UI
   - BirdNET species identifications for detected calls

> **Note:** CPU inference is slower than GPU. On a MacBook Pro M-series, expect BirdNET results in 2–5 seconds per clip. On Intel Macs, up to 10 seconds.

---

## Known Limitations

| Limitation | Impact | Workaround |
| --- | --- | --- |
| No GPU acceleration | CPU inference is 2–10x slower than Jetson | Acceptable for demo/development |
| Video agents require RTSP cameras | Won't use your Mac's webcam | Cameras use credentials from `config/orpheus.example.yaml` or ignore the failures |
| No Bluetooth | No speaker auto-connect | Use `afplay` for local playback testing |
| Crow detection requires AVES model | Agent skipped if model not downloaded | Download `aves-base-bio.pt` and `mt_70.pt` to `data/orpheus/models/` |
| Single audio channel | Jetson uses 4-channel USB interface | Laptop mic is sufficient for development |

---

## Troubleshooting

### Python version mismatch

```bash
ERROR: Python 3.9.5+ required, found 3.12.x
```

If you installed Python via uv, the Makefiles should find it automatically. If not, set `PYTHON_SYSTEM` explicitly:

```bash
export PYTHON_SYSTEM=$(uv python find 3.9.5)
make clean && make install
```

### uv not finding Python after install

If `uv python find 3.9.5` returns nothing after `uv python install 3.9.5`:

```bash
uv python list            # See all installed versions
uv python install 3.9.5   # Re-run to be sure
```

### portaudio missing

```bash
ImportError: No module named 'sounddevice' / could not find portaudio
```

```bash
brew install portaudio
make clean && make install   # Reinstall to pick up portaudio
```

### MQTT connection refused

```bash
Connection refused: localhost:1883
```

Mosquitto isn't running. Start it manually:

```bash
brew services start mosquitto
# or
mosquitto -d
```

### No audio input device found

```bash
sounddevice.PortAudioError: No default input device
```

Check System Preferences > Sound > Input and ensure a microphone is selected. Some Macs with no built-in mic (Mac Mini, Mac Pro) need an external USB mic.

### BirdNET model not found

```bash
FileNotFoundError: birdnet.onnx not found
```

```bash
git lfs pull    # Fetch models from LFS
```

### "make install" fails on numpy/scipy

On Apple Silicon, some packages need the correct architecture:

```bash
# If using uv — it handles architecture automatically
uv python install 3.9.5   # Re-install to ensure ARM-native build

# If using pyenv
arch -arm64 pyenv install 3.9.5
```

### UI shows no events

1. Verify MQTT is running: `mosquitto_sub -t '#' -v` should show messages
2. Check audio-motion logs: `cat logs/audio-motion.log`
3. Ensure your mic is picking up sound (use QuickTime Player > New Audio Recording to test)

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
make dev-restart SVC=bird-detection   # Restart one service
make dev-logs SVC=dashboard           # Tail one log
cd agents/orpheus-agent-audio-motion
make run                # Run single agent (foreground)
make test               # Test single agent
```

---

*For full development guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md). For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md).*
