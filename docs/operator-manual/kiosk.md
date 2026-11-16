# Kiosk display

This page covers the optional always-on station display: what it is, how to open
it from any browser, how to configure it with its URL, where to run the screen,
and what each choice costs. What the screen shows is described in the
[User Guide](../user-guide/index.md#kiosk-display).

## What it is

`/kiosk` is a page of the existing dashboard. It is not a separate service. It
uses the same read-only API endpoints as the dashboard and adds nothing to the
backend:
- recent sightings and today's counts;
- live microphone levels;
- the latest saved camera snapshot;
- station health.

A station that never opens `/kiosk` pays nothing: no extra process, unit or
package, and its code loads only when a browser opens it.

Orpheus runs normally with no monitor, no desktop and no kiosk anything. Keep the
Jetson headless. The kiosk is a browser tab pointed at the station.

## Open it

From any browser on the station's network, for example a laptop:

```
http://jetson1:8080/kiosk
```

It signs itself in as the read-only guest, the same account as the login page's
guest button. It renews that session when it expires and never interrupts a
signed-in operator in the same browser. To go full screen, use the browser's own
full-screen mode: Ctrl-Cmd-F in Safari and Chrome on a Mac, F11 elsewhere.

To try it with no station at all, run `make -C services/orpheus_ui kiosk-demo` and
open `http://localhost:5173/kiosk?demo=1`. That page uses built-in sample data,
says so on screen, and makes no API calls.

## Configure

Everything is set in the URL, so each screen is configured by its bookmark or
launcher. Unknown or out-of-range values fall back to the defaults.

| Parameter | Default | Meaning |
|---|---|---|
| `panels` | all | Comma list of `sightings`, `today`, `audio`, `cameras`, `system` |
| `cameras` | all the station reports | Comma list of camera names to rotate through |
| `rotate` | `20` | Seconds per camera (5–600) |
| `hours` | `24` | Window for the counts, in hours (1–168) |
| `self` | `0` | `1` also lists sounds Orpheus played itself (tagged by corollary discharge) |
| `night` | off | `22-6` dims the screen between those local hours |
| `shift` | `1` | `0` turns off the slow few-pixel drift that protects always-on screens from burn-in |
| `scale` | `1` | Text scale for a distant or tiny screen (0.75–2) |
| `demo` | `0` | `1` uses built-in sample data; no station needed |

Example, for a small screen by the window:
`/kiosk?panels=sightings,cameras,audio&night=22-6&rotate=30`.

Screens narrower than 900 px or shorter than 640 px (the 7-inch 800×480 panel,
a phone) get a compact layout: four panels in a 2×2 grid, with the station
summary on one line in the footer.

The refresh rates follow the dashboard's `dashboard.poll_interval` (default 5 s):
- microphone levels every 5 s;
- sightings and health every 30 s;
- the service list every 60 s;
- the camera snapshot every 60 s;
- the camera list every 10 minutes.

A screen on the default settings makes about 19 requests a minute. Most of them
go to the in-memory microphone-level endpoint; the sightings query is the one
real database read, every 30 s. Raising `dashboard.poll_interval` slows the kiosk
along with the dashboard. Camera images are the snapshotter's saved files, so a
kiosk never makes a camera take a picture.

**Access.** The kiosk relies on `ui.guest_quick_login` (on by default). With it
off, the screen asks for a viewer sign-in once and keeps that session; sign in
there with a viewer account. Anyone who can reach the port can see the kiosk
exactly as they can see the guest dashboard. It shows nothing the guest
dashboard doesn't.

## Where to run the screen

Choose by what the Jetson can spare. The kiosk page itself is the same in every
case.

| Option | Cost to the Jetson | Needs |
|---|---|---|
| **Another device's browser** (Raspberry Pi, laptop, tablet, old phone) pointed at `http://jetson1:8080/kiosk` | API requests only | That device's own display and browser |
| **Chromium on the Jetson** with a minimal kiosk session | Browser about 400 MB of RAM (measured in headless Chromium showing the kiosk at 1080p: about 400–440 MiB across six processes, 10 MiB of page heap), plus a display server or compositor, plus CPU for rendering; GPU memory unless the GPU is disabled | A display session (Xorg or a Wayland kiosk compositor such as `cage`), Chromium, and the monitor attached and detected |
| **The Jetson's GNOME desktop** | GNOME was stopped on 2026-11-12 to give inference its memory back; a full desktop costs far more than a kiosk session (not measured here) | Not recommended |

jetson1 runs the kiosk on its own monitor; see
[On the Jetson's own monitor](#on-the-jetsons-own-monitor) for the setup and its
measured cost. A separate device costs the Jetson nothing beyond API requests: a
Raspberry Pi with auto-login to its desktop and the user unit below is the
simplest one.

Running a display on the Jetson itself is a deployment decision. Before
enabling it on another station, measure there:
- memory with the browser and session running, against the inference memory
  floors in [PANNs GPU worker](panns-gpu.md);
- CPU while the audio and video agents are busy.

Start the browser with the GPU off (`ORPHEUS_KIOSK_GPU=0`, below), so it takes
no GPU memory from inference.

### Finding the monitor

`deploy/kiosk/linux/orpheus-display-info.sh` reports, read-only:
- the display connectors the kernel exposes, and which have a monitor
  attached;
- USB display adapters;
- whether any graphical session is running.

On the Jetson (L4T), the display driver is `nvidia_modeset` without `nvidia_drm`,
so the kernel lists no connectors. The script says so rather than claiming
nothing is attached. Only a running display session can confirm the monitor
there.

On jetson1 the station's 7-inch 800×480 screen reports itself as `HCT HDMI`
and is driven from the Jetson's own DisplayPort output (`DP-0`): X reads its
EDID there and sets 800×480. A USB port carries no video on this carrier board
(it has no USB-C DisplayPort Alt Mode), so whatever the cabling, the picture
comes from the DisplayPort output. With no display session running nothing
drives that output, which is why the screen went dark when GNOME was stopped.

### On the Jetson's own monitor

`deploy/kiosk/jetson/` runs the kiosk on the attached screen without a desktop:
a bare X server and one full-screen Chromium, started at boot by
`orpheus-kiosk.service`. Measured on jetson1 (800×480, GPU off, PANNs on the
GPU worker): X and Chromium together about 285 MiB (PSS); MemAvailable through
the 13:00 and 14:00 timelapse encodes stayed far above the worker's floor, with
no worker stops or rejected clips.

- It runs as the unprivileged `orpheus-kiosk` user, which must be in the
  `video` group (as `gdm` is) or X fails with "Failed to initialize the NVIDIA
  graphics device".
- The browser starts only while a monitor is attached and closes when it is
  unplugged; a headless station carries only an idle X server.
- Nice 10 and `OOMScoreAdjust=900` reach X and every browser process. The memory
  and CPU caps go on the kiosk user's slice, because PAM and the Chromium snap
  move those processes out of the service's own cgroup.
- It signs in as the read-only guest by itself (`ui.guest_quick_login`); no
  credentials are stored anywhere.
- It plays no sound and must not run an audio server: the install step below
  masks PulseAudio for `orpheus-kiosk`. Confirm with
  `make -C services/orpheus-audio-output health` that `capture_isolation` is
  `ok` with the kiosk running.
- `orpheus-kiosk-update.timer` applies the browser's snap security updates every
  Sunday at 03:10, after the 03:00 encode. snapd's automatic refresh is held for
  those snaps so it never replaces the browser mid-day.

Install, check or remove it with `deploy/kiosk/jetson/install.sh`, as root,
from the repository checkout. It is safe to run again, and sets up everything
above: the Chromium snap and its update hold, the `orpheus-kiosk` user (video
group, locked password, PulseAudio masked), the slice caps, the units and the
weekly update timer, and the Ctrl+Alt+Del protection below.

```bash
sudo deploy/kiosk/jetson/install.sh --no-start   # install; enabled at boot, not started yet
sudo systemctl start orpheus-kiosk               # try it on the monitor
sudo deploy/kiosk/jetson/install.sh --check      # every installed piece matches the checkout
sudo deploy/kiosk/jetson/install.sh              # after an update: reinstall and restart
sudo deploy/kiosk/jetson/install.sh --uninstall  # remove it (keeps the user and snaps)
```

The snap store sometimes refuses connections; the installer and the update job
retry, and the update job leaves the kiosk running when it cannot reach the
store.

List `orpheus-kiosk` in `dashboard.services` so the dashboard and the kiosk's
own footer show its state with the other services.

Turn it off and get its memory back, without touching any wildlife service:
`sudo systemctl disable --now orpheus-kiosk`.

**Remote access.** The kiosk opens no network port. An `x11vnc` unit left over
from a desktop install would, once the kiosk's X server is running, share the
screen on every interface. Check with `systemctl is-enabled x11vnc`, and turn it
off unless you use it: `sudo systemctl disable --now x11vnc`.

**Keyboard reboots.** With a keyboard attached, Ctrl+Alt+Del reboots the
station by default. The installer masks `ctrl-alt-del.target` and installs
`50-orpheus-no-ctrl-alt-del.conf`, which also stops the seven-presses forced
reboot. `kernel.sysrq` is left as it is.

Undo: `sudo systemctl unmask ctrl-alt-del.target`, delete the file, and
`sudo systemctl daemon-reexec`.

## Launchers (optional, platform-specific)

Nothing installs these.

- **Linux with a desktop session** (Pi, mini PC):
  `deploy/kiosk/linux/orpheus-kiosk-browser.sh [URL]` starts Chromium or Chrome
  full screen on the kiosk URL, with its own profile:
  - it refuses to run without `DISPLAY` or `WAYLAND_DISPLAY`;
  - it never installs a browser;
  - `ORPHEUS_KIOSK_GPU=0` keeps it off the GPU;
  - `ORPHEUS_KIOSK_WINDOW=W,H` places the window at 0,0 with that size, for an
    X session with no window manager (`--kiosk` alone leaves a margin there);
  - `ORPHEUS_KIOSK_DRY_RUN=1` prints the command instead of running it.

  To start it automatically with the desktop, install the user unit
  `deploy/kiosk/linux/orpheus-kiosk.service` as the desktop user. Its header
  has the commands. It is a `graphical-session.target` unit, so it does
  nothing on a headless machine.
- **macOS:** `deploy/kiosk/macos/open-orpheus-kiosk.sh [URL]` opens Chrome in
  kiosk mode (Cmd-Q to leave) if it is installed. Otherwise it opens the URL
  in the default browser.

## Turn it off

On a station running the kiosk on its own monitor:
`sudo systemctl disable --now orpheus-kiosk` stops X and the browser and frees
their memory; the wildlife services are not touched. Otherwise there is nothing
to turn off on the station. Close the tab, or on a display machine run
`systemctl --user disable --now orpheus-kiosk`. To stop
unauthenticated viewing altogether (dashboard and kiosk), set
`ui.guest_quick_login: false`.

## Troubleshooting

| On screen | Meaning |
|---|---|
| "Connecting to the station…" that never clears | The browser cannot reach the UI at that address; open `http://<host>:8080/` to check |
| "This display needs a viewer sign-in" | Guest viewing is off (`ui.guest_quick_login`), or was turned off while it ran; sign in once with a viewer account |
| "Station unreachable · showing data from HH:MM" | The last refreshes failed; the screen keeps the last data and recovers by itself |
| "*N* services need attention" | Those units are not running; the Station panel names them |
| "No snapshot saved yet" | The snapshotter has not saved one for that camera today (or yesterday, just after UTC midnight) |
| "No cameras configured" | The station reports no cameras; list `panels` without `cameras` to drop the panel |
| Nothing heard yet in this window | No sightings in the last `hours`; sounds Orpheus played itself are hidden unless `self=1` |

## Deployment requirements

The kiosk ships with the UI. It reaches a station when the UI's frontend is
rebuilt and deployed, with no backend, configuration or database change. Rolling
the UI back removes it.

It is tested with:
- frontend unit tests;
- a real-browser suite: `make -C services/orpheus_ui test-kiosk-e2e`, run in
  Chromium with the backend mocked at the network layer, covering 800×480 and
  1080p layouts;
- launcher tests in `tests/bats/kiosk-launchers.bats`.

Checking it on a live station from a Mac's browser is a manual step.
