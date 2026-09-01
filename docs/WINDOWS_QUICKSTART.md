# Windows Quick Start

> ⚠️ **Untested guide.** Orpheus has been tested on macOS and NVIDIA Jetson
> Orin NX. This Windows guide is our best guess at what *should* work — no
> one has actually run it end-to-end yet. Expect rough edges. If you hit
> one, please open an issue or PR so the next person has a better time. We
> thought an imperfect starting point was friendlier than no guide at all.

Get the Orpheus Observe stack running on Windows in ~20 minutes via **WSL2** (Windows Subsystem for Linux). The repo is heavily Makefile-driven and depends on native audio libraries (portaudio, libsndfile) that install cleanly on Ubuntu but are painful on native Windows — so WSL2 is the pragmatic recommended path.

For macOS development, see [macOS Quick Start](MACOS_QUICKSTART.md). For Jetson production, see [Jetson Quick Start](JETSON_QUICKSTART.md). For generic Linux, see [Linux Quick Start](LINUX_QUICKSTART.md). For full development guidelines, see [CONTRIBUTING.md](contributing.md).

---

## Prerequisites

### 1. WSL2 with Ubuntu 22.04

From an elevated PowerShell:

```powershell
wsl --install -d Ubuntu-22.04
```

Reboot if prompted. Launch Ubuntu from the Start menu and create your UNIX user. All remaining commands run **inside the WSL2 Ubuntu shell**, not PowerShell.

Inside that Ubuntu shell you also need **Node.js 20+**, for building the dashboard frontend ([what needs it, and when](ORPHEUS_UI.md#nodejs-what-needs-it-and-when)):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install nodejs
```

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
| **nats-server** | Event-bus broker (NATS + JetStream) | download the pinned 2.10.22 release binary onto your `PATH` — **do not** use `make install-backbone`, see below |
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

### Getting the broker on WSL2

`make install-backbone` is a systemd installer: it must run as root, creates a
system `orpheus` user, writes to `/etc/systemd/system/`, and exits non-zero
unless the unit reaches active. Stock WSL2 has no systemd unless you set
`systemd=true` in `/etc/wsl.conf`, so on this platform it fails — and this same
page tells you elsewhere to use `make dev-stack` rather than systemd.

Download the pinned binary instead and put it on your `PATH`:

```bash
NATS_VERSION=2.10.22
curl -fsSL "https://github.com/nats-io/nats-server/releases/download/v${NATS_VERSION}/nats-server-v${NATS_VERSION}-linux-amd64.tar.gz" \
  | tar -xz --strip-components=1 -C /tmp "nats-server-v${NATS_VERSION}-linux-amd64/nats-server"
sudo install -m 0755 /tmp/nats-server /usr/local/bin/nats-server
nats-server --version
```

`make dev-stack` starts it from there. Do this after Clone and Install — the
version above is what the repo pins.

---

## Clone and Install

> **Important:** Clone inside your WSL2 home directory (e.g., `~/orpheus`), **not** under `/mnt/c/`. Filesystem performance on `/mnt/c/` is significantly slower, and `git lfs pull` may stall or corrupt on large fetches.

```bash
cd ~
git clone https://github.com/scottchronicity/orpheus.git
cd orpheus
git lfs pull          # Fetch ML models (~1.5 GB)
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

| Setting | Jetson Default | WSL2 Override | Reason |
| --- | --- | --- | --- |
| Audio channels | 4-channel Behringer UMC404HD | Single mic (or none) | WSL2 has no native audio input by default |
| Storage path | `/data/orpheus` | `~/data/orpheus` | Keep data inside the WSL2 filesystem |
| Sample rate | 48000 Hz | (optional) 44100 Hz | Match whatever device you wire up |

### Audio input inside WSL2 (hard part)

WSL2 does **not** passthrough audio devices by default. Options, in rough order of difficulty:

1. **Skip audio capture entirely** — the video agents, UI, event bus, and event correlator all still work. Good for "kick the tires" exploration.
2. **`usbipd-win` USB passthrough** — attach a USB microphone to WSL2. See [dorssel/usbipd-win](https://github.com/dorssel/usbipd-win). Untried for Orpheus; you may also need `udev` rules inside WSL2.
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

   When the dashboard opens it asks you to sign in. The seeded accounts and the
   environment variables that set their passwords are documented in
   [Signing in to the dashboard](INSTALLATION.md#signing-in-to-the-dashboard) — set
   those before you expose this to anyone else.

2. If you got audio capture working, play a YouTube video of bird calls near the mic.
3. Within 10–20 seconds you should see audio motion events and BirdNET identifications in the UI.
4. If cameras are connected, video motion events and snapshots appear automatically.

---

## Known Limitations

| Limitation | Impact | Workaround |
| --- | --- | --- |
| No GPU acceleration assumed | Only affects the two torch models; BirdNET is CPU everywhere | Acceptable for demo/dev |
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
- `nats-server` has a native Windows binary, but the backplane's install/service management targets systemd (WSL2) — native service wiring would need rework.

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

### Event-bus connection refused

The NATS backplane isn't running (`nats: no servers available` or connection
refused on 4222). In WSL2:

```bash
make -C services/orpheus-backplane run   # the genuinely minimal path.
# `make dev-stack SVC=backplane` runs the full preflight first, so it still
# needs nats-server on PATH and every component venv present.
# then check its log:
cat logs/backplane.log
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
make dev-logs SVC=orpheus-ui-backend
cd agents/orpheus-agent-audio-motion
make run                # Run single agent (foreground)
```

---

*For full development guidelines, see [CONTRIBUTING.md](contributing.md). For architecture details, see [ARCHITECTURE.md](ARCHITECTURE.md).*
