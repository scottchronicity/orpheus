#!/usr/bin/env bats
# deploy/kiosk/ — the optional kiosk launchers. They only ever start a
# browser: no display means a clear refusal, never an install. A fake
# "chromium" on PATH records how it would be started.

load 'test_helper'

LINUX="$REPO_ROOT/deploy/kiosk/linux/orpheus-kiosk-browser.sh"
MACOS="$REPO_ROOT/deploy/kiosk/macos/open-orpheus-kiosk.sh"
UNIT="$REPO_ROOT/deploy/kiosk/linux/orpheus-kiosk.service"

setup() {
  BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$BIN"
  printf '#!/bin/bash\nprintf "%%s\\n" "$@" > "%s/argv"\n' "$BATS_TEST_TMPDIR" > "$BIN/chromium"
  chmod +x "$BIN/chromium"
  export PATH="$BIN:/usr/bin:/bin"
  export HOME="$BATS_TEST_TMPDIR/home"
  unset DISPLAY WAYLAND_DISPLAY ORPHEUS_KIOSK_URL ORPHEUS_KIOSK_BROWSER ORPHEUS_KIOSK_GPU ORPHEUS_KIOSK_WINDOW
}

@test "refuses to start without a graphical session" {
  run bash "$LINUX"
  assert_failure 3
  assert_output --partial "no graphical session"
  [ ! -e "$BATS_TEST_TMPDIR/argv" ]
}

@test "starts the browser full screen on the kiosk URL with its own profile" {
  export DISPLAY=:0
  run bash "$LINUX" http://jetson1:8080/kiosk?panels=sightings,cameras
  assert_success
  grep -qx -- "--kiosk" "$BATS_TEST_TMPDIR/argv"
  grep -qx -- "--app=http://jetson1:8080/kiosk?panels=sightings,cameras" "$BATS_TEST_TMPDIR/argv"
  grep -qx -- "--user-data-dir=$HOME/.cache/orpheus-kiosk" "$BATS_TEST_TMPDIR/argv"
  run grep -qx -- "--disable-gpu" "$BATS_TEST_TMPDIR/argv"
  assert_failure
}

@test "can keep the browser off the GPU (for a host whose GPU runs inference)" {
  export WAYLAND_DISPLAY=wayland-0 ORPHEUS_KIOSK_GPU=0
  run bash "$LINUX"
  assert_success
  grep -qx -- "--disable-gpu" "$BATS_TEST_TMPDIR/argv"
  grep -qx -- "--app=http://localhost:8080/kiosk" "$BATS_TEST_TMPDIR/argv"
}

@test "fills a window-manager-less screen when given its size" {
  export DISPLAY=:0 ORPHEUS_KIOSK_WINDOW=800,480
  run bash "$LINUX"
  assert_success
  grep -qx -- "--window-position=0,0" "$BATS_TEST_TMPDIR/argv"
  grep -qx -- "--window-size=800,480" "$BATS_TEST_TMPDIR/argv"
}

@test "leaves window placement alone unless asked" {
  export DISPLAY=:0
  run bash "$LINUX"
  assert_success
  ! grep -q -- "--window-size" "$BATS_TEST_TMPDIR/argv"
}

@test "rejects a malformed window size" {
  export DISPLAY=:0 ORPHEUS_KIOSK_WINDOW="800x480"
  run bash "$LINUX"
  [ "$status" -eq 2 ]
  [[ "$output" == *"must be W,H"* ]]
}

@test "rejects a URL that is not an Orpheus kiosk page" {
  export DISPLAY=:0
  run bash "$LINUX" "file:///etc/passwd"
  assert_failure 2
  run bash "$LINUX" "http://jetson1:8080/settings"
  assert_failure 2
}

@test "reports a missing browser instead of installing one" {
  export DISPLAY=:0 ORPHEUS_KIOSK_BROWSER=definitely-not-a-browser
  run bash "$LINUX"
  assert_failure 4
  assert_output --partial "no Chromium or Chrome found"
}

@test "the macOS helper validates its URL" {
  ORPHEUS_KIOSK_DRY_RUN=1 run bash "$MACOS" http://jetson1:8080/kiosk
  assert_success
  assert_output --partial "http://jetson1:8080/kiosk"
  run bash "$MACOS" "javascript:alert(1)"
  assert_failure 2
}

@test "the optional user unit is a graphical-session unit, never a system one" {
  grep -qx "WantedBy=graphical-session.target" "$UNIT"
  grep -qx "PartOf=graphical-session.target" "$UNIT"
  run grep -E "^(User|Group)=" "$UNIT"
  assert_failure
}

@test "the display report is read-only and describes what it finds" {
  root="$BATS_TEST_TMPDIR/sysroot"
  mkdir -p "$root/sys/class/drm/card0-HDMI-A-1" "$root/sys/class/drm/card0-DP-1" "$root/sys/bus/usb/devices/2-4"
  echo connected > "$root/sys/class/drm/card0-HDMI-A-1/status"
  printf '800x480\n640x480\n' > "$root/sys/class/drm/card0-HDMI-A-1/modes"
  echo disconnected > "$root/sys/class/drm/card0-DP-1/status"
  echo 17e9 > "$root/sys/bus/usb/devices/2-4/idVendor"
  echo 4301 > "$root/sys/bus/usb/devices/2-4/idProduct"
  echo "USB Display Adapter" > "$root/sys/bus/usb/devices/2-4/product"
  SYSROOT="$root" run bash "$REPO_ROOT/deploy/kiosk/linux/orpheus-display-info.sh"
  assert_success
  assert_output --partial "card0-HDMI-A-1: connected, preferred mode 800x480"
  assert_output --partial "card0-DP-1: disconnected"
  assert_output --partial "2-4: 17e9:4301 USB Display Adapter"
  assert_output --partial "1 monitor(s) attached"
}

@test "with nothing attached the display report says so" {
  root="$BATS_TEST_TMPDIR/empty"
  mkdir -p "$root/sys/class/drm/card0-HDMI-A-1"
  echo disconnected > "$root/sys/class/drm/card0-HDMI-A-1/status"
  SYSROOT="$root" run bash "$REPO_ROOT/deploy/kiosk/linux/orpheus-display-info.sh"
  assert_success
  assert_output --partial "No monitor reported attached"
}

@test "on a Jetson without nvidia_drm the report says it cannot see monitors" {
  root="$BATS_TEST_TMPDIR/jetson"
  mkdir -p "$root/sys/class/drm" "$root/proc"
  printf 'nvidia_modeset 1093632 0 - Live 0x0\nsnd_soc_tegra210_ope 32768 1 - Live 0x0\n' > "$root/proc/modules"
  SYSROOT="$root" run bash "$REPO_ROOT/deploy/kiosk/linux/orpheus-display-info.sh"
  assert_success
  assert_output --partial "nvidia_modeset) is loaded without nvidia_drm"
  assert_output --partial "Monitor attachment unknown on this host"
}
