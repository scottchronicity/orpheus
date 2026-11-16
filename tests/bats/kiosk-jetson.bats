#!/usr/bin/env bats
# deploy/kiosk/jetson — the kiosk on a Jetson's own monitor. A fake xrandr
# serves recorded output; nothing on the host is read or changed.

load 'test_helper'

J="$REPO_ROOT/deploy/kiosk/jetson"

setup() {
  mkdir -p "$BATS_TEST_TMPDIR/bin"
  cat > "$BATS_TEST_TMPDIR/bin/xrandr" <<'EOF2'
#!/bin/bash
cat "$XRANDR_FIXTURE"
EOF2
  chmod +x "$BATS_TEST_TMPDIR/bin/xrandr"
  PATH="$BATS_TEST_TMPDIR/bin:$PATH"
}

# Recorded on jetson1 with the 800x480 HCT panel on DisplayPort.
connected_fixture() {
  cat > "$BATS_TEST_TMPDIR/xrandr.txt" <<'EOF2'
Screen 0: minimum 8 x 8, current 800 x 480, maximum 32767 x 32767
DP-0 connected primary 800x480+0+0 (normal left inverted right x axis y axis) 152mm x 91mm
   800x480       60.58*+
   1920x1080     60.00    59.90    50.00    23.98
DP-1 disconnected (normal left inverted right x axis y axis)
EOF2
  export XRANDR_FIXTURE="$BATS_TEST_TMPDIR/xrandr.txt"
}

@test "finds the attached monitor's mode" {
  connected_fixture
  source "$J/orpheus-kiosk-session.sh"
  run connected_mode
  [ "$output" = "800x480" ]
}

@test "reports no monitor when every output is disconnected" {
  printf 'Screen 0: minimum 8 x 8, current 640 x 480, maximum 32767 x 32767\nDP-0 disconnected (normal)\nDP-1 disconnected (normal)\n' > "$BATS_TEST_TMPDIR/xrandr.txt"
  export XRANDR_FIXTURE="$BATS_TEST_TMPDIR/xrandr.txt"
  source "$J/orpheus-kiosk-session.sh"
  run connected_mode
  [ -z "$output" ]
}

@test "the kiosk unit is independent of every wildlife service" {
  run grep -E '^(Requires|Wants|BindsTo|PartOf|Requisite)=' "$J/orpheus-kiosk.service"
  [ "$status" -ne 0 ]
  run grep -E '^WantedBy=multi-user.target$' "$J/orpheus-kiosk.service"
  [ "$status" -eq 0 ]
}

@test "the kiosk runs unprivileged, off the GPU, first in line for the OOM killer" {
  grep -qx 'User=orpheus-kiosk' "$J/orpheus-kiosk.service"
  grep -qx 'Environment=ORPHEUS_KIOSK_GPU=0' "$J/orpheus-kiosk.service"
  grep -qE '^OOMScoreAdjust=([5-9][0-9]{2}|1000)$' "$J/orpheus-kiosk.service"
  grep -qx 'Environment=ORPHEUS_KIOSK_URL=http://127.0.0.1:8082/kiosk' "$J/orpheus-kiosk.service"
}

@test "no credentials in the kiosk files" {
  run grep -riE 'guest@|password *[=:]|_password|token *[=:]|secret *[=:]' "$J"
  [ "$status" -ne 0 ]
}

@test "the update job puts the kiosk back the way it found it" {
  grep -q 'was_active=' "$J/orpheus-kiosk-update.sh"
  grep -q "systemctl start orpheus-kiosk" "$J/orpheus-kiosk-update.sh"
  grep -qx 'Persistent=false' "$J/orpheus-kiosk-update.timer"
}

# A fake `snap info`, in the format the store returned on jetson1.
fake_snap() {  # fake_snap <store-revision-for-chromium> | fake_snap unreachable
  cat > "$BATS_TEST_TMPDIR/bin/snap" <<EOF2
#!/bin/bash
[ "\$1" = info ] || exit 2
[ "$1" = unreachable ] && { echo 'error: unable to contact snap store' >&2; exit 1; }
rev=3594; [ "\$2" = chromium ] && rev=$1
cat <<INFO
name:      \$2
tracking:     latest/stable
installed:          1.0             (3594) 195MB -
channels:
  latest/stable:    1.1 2026-11-20 (\$rev) 195MB -
  latest/candidate: 1.2 2026-11-21 (9999) 195MB -
INFO
EOF2
  chmod +x "$BATS_TEST_TMPDIR/bin/snap"
}

@test "update job: nothing pending when every snap is at its channel's revision" {
  fake_snap 3594
  source "$J/orpheus-kiosk-update.sh"
  run pending_snaps
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

@test "update job: names a snap whose channel has a newer revision (held or not)" {
  fake_snap 3600
  source "$J/orpheus-kiosk-update.sh"
  run pending_snaps
  [ "$status" -eq 0 ]
  [ "$output" = "chromium" ]
}

@test "update job: an unreachable store is a failure, not 'up to date'" {
  fake_snap unreachable
  source "$J/orpheus-kiosk-update.sh"
  run pending_snaps
  [ "$status" -ne 0 ]
}

@test "update job: a refresh that fails still puts the kiosk back, and reports failure" {
  fake_snap 3600                                   # chromium has an update waiting
  # snap refresh always fails; snap info as above.
  sed -i 's/^\[ "\$1" = info \] || exit 2$/[ "$1" = refresh ] \&\& exit 1; [ "$1" = list ] \&\& exit 0; [ "$1" = info ] || exit 2/' "$BATS_TEST_TMPDIR/bin/snap"
  cat > "$BATS_TEST_TMPDIR/bin/systemctl" <<EOF2
#!/bin/bash
echo "\$*" >> "$BATS_TEST_TMPDIR/systemctl.log"
[ "\$1" = is-active ] && echo active
exit 0
EOF2
  chmod +x "$BATS_TEST_TMPDIR/bin/systemctl"
  ORPHEUS_KIOSK_UPDATE_PAUSE=0 run bash "$J/orpheus-kiosk-update.sh"
  [ "$status" -ne 0 ]
  [[ "$output" == *"updating chromium"* ]]
  [[ "$output" == *"snap refresh attempt 3 failed"* ]]
  run cat "$BATS_TEST_TMPDIR/systemctl.log"
  [[ "$output" == *"stop orpheus-kiosk"*"start orpheus-kiosk"* ]]
}
