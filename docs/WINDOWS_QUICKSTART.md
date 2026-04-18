# Windows Quick Start

> ⚠️ **Untested guide.** Orpheus has been tested on macOS and NVIDIA Jetson
> Orin NX. This Windows guide is our best guess at what *should* work — no
> one has actually run it end-to-end yet. Expect rough edges. If you hit
> one, please open an issue or PR so the next person has a better time. We
> thought an imperfect starting point was friendlier than no guide at all.

Get the Orpheus Observe stack running on Windows in ~20 minutes via **WSL2** (Windows Subsystem for Linux). The repo is heavily Makefile-driven and depends on native audio libraries (portaudio, libsndfile) that install cleanly on Ubuntu but are painful on native Windows — so WSL2 is the pragmatic recommended path.

For macOS development, see [macOS Quick Start](MACOS_QUICKSTART.md). For Jetson production, see [Jetson Quick Start](JETSON_QUICKSTART.md). For generic Linux, see [Linux Quick Start](LINUX_QUICKSTART.md). For full development guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md).

---

## Prerequisites

### 1. WSL2 with Ubuntu 22.04

From an elevated PowerShell:

```powershell
wsl --install -d Ubuntu-22.04
```

Reboot if prompted. Launch Ubuntu from the Start menu and create your UNIX user. All remaining commands run **inside the WSL2 Ubuntu shell**, not PowerShell.

Verify you're in WSL:

```bash
uname -a        # Should show "Linux ... WSL2 ..."
```

### 2. System packages (inside WSL2)

| Requirement | Why | Install |
| --- | --- | --- |
| **make** | Build automation | `sudo apt install make` |
| **libportaudio2** | Audio I/O (sounddevice) | `sudo apt install libportaudio2` |
| **libsndfile1** | Audio file reading/writing | `sudo apt install libsndfile1` |
| **mosquitto** | MQTT broker | `sudo apt install mosquitto mosquitto-clients` |
| **Git LFS** | ML model storage | `sudo apt install git-lfs && git lfs install` |
| **ffmpeg** | Timelapse video generation | `sudo apt install ffmpeg` |
| **build-essential** | Compile native Python extensions | `sudo apt install build-essential` |

### 3. Python 3.9.5 via uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv python install 3.9.5
uv python find 3.9.5    # Should print the path to the installed interpreter
```

The repo's `.python-version` file tells uv (and the Makefiles) which version to use.

---

## Clone and Install

> **Important:** Clone inside your WSL2 home directory (e.g., `~/orpheus`), **not** under `/mnt/c/`. Filesystem performance on `/mnt/c/` is significantly slower, and `git lfs pull` may stall or corrupt on large fetches.

```bash
cd ~
git clone https://github.com/scottchronicity/orpheus.git
cd orpheus
git lfs pull          # Fetch ML models (~500MB)
make install          # Create venvs, install all dependencies
```

Expect 5–10 minutes for the first install (model downloads + compilation of native extensions).

Verify:

```bash
make test-common      # Should pass
```

---

## Configure for Windows/WSL2

Orpheus uses one canonical config (`config/orpheus.example.yaml`) for all environments. Overrides go in a small `.env` file.

```bash
cp config/.env.orpheus.example config/.env.orpheus
$EDITOR config/.env.orpheus
```

### Likely overrides

| Setting | Jetson Default | WSL2 Override | Reason |
| --- | --- | --- | --- |
| Audio channels | 4-channel Behringer UMC404HD | Single mic (or none) | WSL2 has no native audio input by default |
| Storage path | `/data/orpheus` | `~/data/orpheus` | Keep data inside the WSL2 filesystem |
| Sample rate | 48000 Hz | (optional) 44100 Hz | Match whatever device you wire up |

### Audio input inside WSL2 (hard part)

WSL2 does **not** passthrough audio devices by default. Options, in rough order of difficulty:

1. **Skip audio capture entirely** — the video agents, UI, MQTT, and event correlator all still work. Good for "kick the tires" exploration.
2. **`usbipd-win` USB passthrough** — attach a USB microphone to WSL2. See [microsoft/usbipd-win](https://github.com/dorssel/usbipd-win). Untried for Orpheus; you may also need `udev` rules inside WSL2.
3. **Network audio streaming** — stream audio into WSL2 via RTP/PulseAudio over TCP. Niche; only pursue if you need it.

If audio capture isn't working, the `audio-motion` agent will log errors but the rest of the stack continues running.

### Camera credentials

Video agents connect to cameras over **RTSP** over your LAN. WSL2's default NAT networking should reach them fine. The config ships with 4 cameras pre-configured using credentials `orpheus` / `orpheus-station-2025`. Without RTSP cameras, the video agents start but stay idle.

---

## Run the Stack

```bash
make dev-stack
```

This starts all Observe components as **background processes**. Same service list as the [macOS guide](MACOS_QUICKSTART.md#run-the-stack).

The UI backend runs at [http://localhost:8082](http://localhost:8082) and the frontend at [http://localhost:5173](http://localhost:5173). On Windows 11, WSL2 auto-forwards `localhost` — open either URL from your Windows browser and it should just work. On older Windows 10 WSL2 setups you may need to open `http://<wsl2-ip>:5173` instead (find the IP with `ip addr show eth0`).

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

1. Open [http://localhost:5173](http://localhost:5173) in your Windows browser.
2. If you got audio capture working, play a YouTube video of bird calls near the mic.
3. Within 10–20 seconds you should see audio motion events and BirdNET identifications in the UI.
4. If cameras are connected, video motion events and snapshots appear automatically.

---

## Known Limitations

| Limitation | Impact | Workaround |
| --- | --- | --- |
| No GPU acceleration assumed | CPU inference is 2–10x slower than Jetson | Acceptable for demo/dev |
| Audio capture from Windows host | Requires `usbipd-win` or network audio | Skip audio; rest of stack still works |
| No Bluetooth auto-connect | `orpheus-bluetooth-autoconnect` is Linux/Jetson-focused | Untested on WSL2; likely won't work |
| `/mnt/c/` performance | Git LFS and `make install` stall on Windows-mounted drives | Clone inside `~` (WSL2 native filesystem) |
| systemd units | Services' `install.sh` scripts target Jetson | Use `make dev-stack` instead of systemd |

---

## Native Windows (untried)

Running the stack on native Windows (PowerShell/cmd, no WSL2) has **not** been attempted. The obstacles you'd hit:

- `make` isn't on Windows by default. Install via [Chocolatey](https://chocolatey.org/) (`choco install make`) or [Scoop](https://scoop.sh/).
- Most Makefile targets assume a POSIX shell. `dev-stack` in particular uses background-process plumbing (`&`, PID files in `.dev-stack/pids/`) that won't translate to cmd or PowerShell without substantial rework.
- `sounddevice` / `pyaudio` need a portaudio binary. Pre-built wheels exist on PyPI for Windows, but the Makefile-driven install path doesn't know about them — you'd need manual intervention.
- `mosquitto` has a Windows build but service management differs (no systemd, no `brew services`).

If you try this and get it working, a PR adding a "Native Windows" section here would be very welcome.

---

## Troubleshooting

### `localhost:5173` doesn't load from Windows browser

WSL2 forwards `localhost` on Windows 11 by default. On Windows 10 or older builds:

```bash
ip addr show eth0 | grep inet   # Find WSL2's IP
```

Browse to `http://<that-ip>:5173` instead.

### `git lfs pull` hangs or corrupts

Almost always caused by cloning under `/mnt/c/` (the Windows-mounted drive). Re-clone inside your WSL2 home (`~`) and try again.

### `portaudio` / `sounddevice` import error

```bash
sudo apt install libportaudio2 libsndfile1
make clean && make install
```

### MQTT connection refused

Mosquitto isn't running. In WSL2 (which usually has systemd enabled on recent builds):

```bash
sudo systemctl start mosquitto
# or foreground:
mosquitto -v
```

### No audio input device found

WSL2 has no audio by default. Either skip audio (the rest of the stack runs without it) or set up `usbipd-win` USB passthrough. See "Audio input inside WSL2" above.

### `make install` fails compiling numpy/scipy

Missing build tools inside WSL2:

```bash
sudo apt install build-essential
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
```

---

*For full development guidelines, see [CONTRIBUTING.md](../CONTRIBUTING.md). For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md).*
