# macOS Quick Start

Get the Orpheus Observe stack running on your Mac in ~15 minutes. This guide is self-contained — you do not need to read anything else to reach a working dashboard with live detections.

On Windows? See [Windows Quick Start](WINDOWS_QUICKSTART.md) (untested). On generic Linux? See [Linux Quick Start](LINUX_QUICKSTART.md) (untested). For Jetson production, see [Jetson Quick Start](JETSON_QUICKSTART.md).

For full development guidelines, see [CONTRIBUTING.md](contributing.md) and [AGENTS.md](agents-index.md).

---

## Prerequisites

| Requirement | Why | Install |
| --- | --- | --- |
| **make** | Build automation (used everywhere) | `xcode-select --install` |
| **uv** | Python version & package manager | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Homebrew** | Package manager | [brew.sh](https://brew.sh) |
| **portaudio** | Audio I/O (PyAudio/sounddevice) | `brew install portaudio` |
| **libsndfile** | Audio file reading/writing | `brew install libsndfile` |
| **nats-server** | Event-bus broker (NATS + JetStream) | `brew install nats-server` (or `make install-backbone`) |
| **Git LFS** | ML model storage | `brew install git-lfs && git lfs install` |
| **Node.js 20+** | Building the dashboard frontend — see [Node.js: what needs it, and when](ORPHEUS_UI.md#nodejs-what-needs-it-and-when) | `brew install node` |
| **ffmpeg** | Timelapse video generation, and audio playback unless you switch the player | `brew install ffmpeg` |

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
git lfs pull          # Fetch ML models (~1.5 GB)
make install          # Create venvs, install all dependencies
```

This creates a Python virtual environment inside each component directory. Expect 5–10 minutes for the first install (model downloads + compilation of native extensions).

`make install` also installs the dashboard frontend's dependencies and the end-to-end test harness, which downloads a private copy of Chromium (a few hundred MB) via Playwright. That is the browser the e2e suite drives; nothing else uses it. It does not produce a
built bundle — `make -C services/orpheus_ui build-frontend` does that, and
`make dev-stack` does not need it because it serves the dashboard from the Vite dev
server. See [Node.js: what needs it, and when](ORPHEUS_UI.md#nodejs-what-needs-it-and-when).

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

`make dev-stack` loads the Jetson config automatically. OrpheusConfig picks up `config/.env.orpheus` and applies your overrides on top. You only need to set `ORPHEUS_CONFIG_PATH` when running individual agents manually outside the dev-stack script.

### What the `.env` overrides (and why)

| Setting | Jetson Default | macOS Override | Reason |
| --- | --- | --- | --- |
| Audio channels | 4-channel Behringer UMC404HD | Single laptop mic | MacBooks have one mic |
| Storage path | `/data/orpheus` | `~/data/orpheus` | No root partition on Mac |
| Sample rate | 48000 Hz | (optional) 44100 Hz | Some Mac mics don't support 48kHz |

Everything else — cameras, the event bus, retention, dashboard, bird detection — is identical across environments.

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
| 1 | **backplane** | NATS + JetStream broker (adopts an already-running `nats-server`) |
| 2 | **audio-motion** | Captures from laptop mic, detects sound events |
| 3 | **audio-events** | PANNs sound-event classifier (AudioSet ontology) |
| 4 | **audio-playback** | Plays deterrent/test audio. The shipped config uses `ffplay`, not `afplay` — see the note below the table |
| 5 | **bird-detection** | BirdNET ONNX inference on audio clips (skipped if model missing) |
| 6 | **crow-detection** | AVES classifier (skipped if model missing) |
| 7 | **video-motion** | RTSP video motion detection |
| 8 | **video-snapshotter** | Periodic RTSP snapshots |
| 9 | **video-timelapser** | Timelapse generation from snapshots |
| 10 | **event-correlator** | Fuses detections into entity-level events |
| 11 | **gps** | GPS/location service |
| 12 | **orpheus-ui-backend** | FastAPI API server at [http://localhost:8082](http://localhost:8082) |
| 13 | **orpheus-ui-frontend** | Vite/React dev server at [http://localhost:5173](http://localhost:5173) — if 5173 is busy, Vite picks the next free port; check `logs/orpheus-ui-frontend.log` |

**Playback uses `ffplay`, not `afplay`.** `audio.playback_command` in the shipped
config is `ffplay`, and there is no macOS special case in the player — so either
install ffmpeg, or put `ORPHEUS_AUDIO__PLAYBACK_COMMAND=afplay` in
`config/.env.orpheus` to use the built-in. Without one of those, playback fails
with a missing binary.

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

   When the dashboard opens it asks you to sign in. The seeded accounts and the
   environment variables that set their passwords are documented in
   [Signing in to the dashboard](INSTALLATION.md#signing-in-to-the-dashboard) — on a
   Mac they go in `config/.env.orpheus`, which `dev-stack` sources. Set them before
   you expose this to anyone else.

2. Play a YouTube video of bird calls near your laptop (search "bird calls identification").
3. Within 10–20 seconds, you should see:
   - Audio motion events appearing in the UI
   - BirdNET species identifications for detected calls

> **Note:** CPU inference is slower than GPU. On a MacBook Pro M-series, expect BirdNET results in 2–5 seconds per clip. On Intel Macs, up to 10 seconds.

---

## Known Limitations

| Limitation | Impact | Workaround |
| --- | --- | --- |
| No GPU acceleration | Only affects the two torch models; BirdNET is CPU everywhere | Acceptable for demo/development |
| Video agents require RTSP cameras | Won't use your Mac's webcam | Cameras use credentials from `config/orpheus.example.yaml` or ignore the failures |
| No Bluetooth | No speaker auto-connect | Set `ORPHEUS_AUDIO__PLAYBACK_COMMAND=afplay` in `config/.env.orpheus` to use the macOS built-in player |
| Crow detection requires AVES model | Agent skipped if model not downloaded | `git lfs pull` — both files ship in `artifacts/models/` and `dev-stack` symlinks them into place on first run |
| Single audio channel | Jetson uses 4-channel USB interface | Laptop mic is sufficient for development |

---

## Troubleshooting

### Python version mismatch

```
❌ Python interpreter 'python3.9' not found.
   Run: uv python install 3.9.5
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

### Everything is running but nothing is ever detected (macOS)

The most common cause is microphone permission. macOS blocks audio capture per
application, and the process that needs permission is the **terminal** you launched
`make dev-stack` from (Terminal, iTerm, VS Code), not Orpheus itself. Capture then
returns silence forever, with no error: agents look healthy, levels sit flat, and
no clip is ever written.

Open **System Settings → Privacy & Security → Microphone** and enable your terminal
app, then restart the stack (`make dev-restart`). Confirm the fix in the audio
levels on the Diagnostics page, or with `make dev-logs SVC=audio-motion` — a
working mic shows the level tracking as you make noise.

### UI shows no events

1. Verify the backplane is up: `make dev-status` shows it running; `cat logs/backplane.log` shows "Server is ready"
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
make test-all           # Run all tests
make clean              # Remove all venvs (full reinstall)

# Individual agents
make dev-restart SVC=bird-detection   # Restart one service
make dev-logs SVC=orpheus-ui-backend  # Tail one log
cd agents/orpheus-agent-audio-motion
make run                # Run single agent (foreground)
make test               # Test single agent
```

---

*For full development guidelines, see [CONTRIBUTING.md](contributing.md). For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md).*
