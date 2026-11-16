#!/usr/bin/env bats
# deploy/kiosk/jetson/install.sh — option handling and the --check report.
# Install paths point into the test sandbox and every system command is a fake
# reporting a correctly installed host, so only the files decide the result.

load 'test_helper'

INSTALL="$REPO_ROOT/deploy/kiosk/jetson/install.sh"

setup() {
  SB="$BATS_TEST_TMPDIR"
  export ORPHEUS_KIOSK_LIB="$SB/lib" ORPHEUS_KIOSK_UNITDIR="$SB/units" ORPHEUS_KIOSK_CONFD="$SB/confd"
  mkdir -p "$SB/bin" "$SB/lib" "$SB/units" "$SB/confd" "$SB/home/.config/systemd/user" "$SB/home/.config/pulse"
  ln -s /dev/null "$SB/home/.config/systemd/user/pulseaudio.socket"
  ln -s /dev/null "$SB/home/.config/systemd/user/pulseaudio.service"
  echo 'autospawn = no' > "$SB/home/.config/pulse/client.conf"
  fake() { printf '#!/bin/bash\n%s\n' "$2" > "$SB/bin/$1"; chmod +x "$SB/bin/$1"; }
  fake snap 'case "$1" in list) echo "Name Version Rev Tracking Publisher Notes"; echo "$2 1 1 latest/stable canonical held";; services) echo "cups.cupsd disabled inactive -";; esac'
  fake id 'case "$1" in -u) [ -n "$2" ] && echo 1002 || echo 1000;; -nG) echo "orpheus-kiosk video";; *) exit 0;; esac'
  fake getent "echo 'orpheus-kiosk:x:1002:1003::$SB/home:/usr/sbin/nologin'"
  fake passwd 'echo "orpheus-kiosk L 11/16/2026 0 99999 7 -1"'
  fake pgrep 'exit 1'
  fake systemctl 'case "$1" in
    show) case "$4" in MemoryLimit) echo 838860800;; CPUShares) echo 205;; esac;;
    is-enabled) case "$2" in ctrl-alt-del.target) echo masked;; *) echo enabled;; esac;;
    is-active) echo active;; esac'
  PATH="$SB/bin:$PATH"
  # The installed files, identical to the checkout.
  cp "$REPO_ROOT/deploy/kiosk/linux/orpheus-kiosk-browser.sh" "$REPO_ROOT"/deploy/kiosk/jetson/orpheus-kiosk-{session,update}.sh "$SB/lib/"
  cp "$REPO_ROOT"/deploy/kiosk/jetson/orpheus-kiosk{,-update}.service "$REPO_ROOT/deploy/kiosk/jetson/orpheus-kiosk-update.timer" "$SB/units/"
  cp "$REPO_ROOT/deploy/kiosk/jetson/50-orpheus-no-ctrl-alt-del.conf" "$SB/confd/"
}

@test "--check passes on a host that matches the checkout" {
  run bash "$INSTALL" --check
  [ "$status" -eq 0 ]
  [[ "$output" != *"❌"* ]]
  [[ "$output" == *"pulseaudio.socket masked"* ]]
}

@test "--check catches an installed file that drifted from the checkout" {
  echo "# local edit" >> "$SB/units/orpheus-kiosk.service"
  run bash "$INSTALL" --check
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌ $SB/units/orpheus-kiosk.service differs"* ]]
}

@test "--check catches a missing PulseAudio mask (capture isolation)" {
  rm "$SB/home/.config/systemd/user/pulseaudio.socket"
  run bash "$INSTALL" --check
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌ pulseaudio.socket not masked"* ]]
}

@test "install and uninstall refuse to run without root" {
  run bash "$INSTALL"
  [ "$status" -ne 0 ]
  [[ "$output" == *"run as root"* ]]
  run bash "$INSTALL" --uninstall
  [ "$status" -ne 0 ]
}

@test "an unknown option is an error" {
  run bash "$INSTALL" --frobnicate
  [ "$status" -ne 0 ]
  [[ "$output" == *"unknown option"* ]]
}
