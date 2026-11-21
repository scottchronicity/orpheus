#!/usr/bin/env bats
# deploy/clock/install-clock-guard.sh and scripts/verify-clock-guard.sh: Orpheus
# must start on a real clock after a cold boot (jetson1, 2026-11-21: NVIDIA's
# nvrtc-sync-boot set the clock back to 1970 and nothing waited for NTP).
# A fake systemctl stands in for systemd; the installer writes into a sandbox root.

load 'test_helper'

INSTALL="$REPO_ROOT/deploy/clock/install-clock-guard.sh"
CHECK="$REPO_ROOT/scripts/verify-clock-guard.sh"

setup() {
  SB="$BATS_TEST_TMPDIR"
  mkdir -p "$SB/state"
  # state/<unit>.<Property> holds what `systemctl show` reports; state/enabled
  # what is-enabled reports for systemd-time-wait-sync. Every call is logged.
  cat > "$SB/systemctl" <<EOF2
#!/bin/bash
echo "\$*" >> "$SB/calls"
case "\$1" in
  is-enabled) cat "$SB/state/enabled" 2>/dev/null || echo disabled ;;
  show) cat "$SB/state/\$2.\$4" 2>/dev/null ;;
esac
EOF2
  chmod +x "$SB/systemctl"
  export SYSTEMCTL="$SB/systemctl"
}

set_prop() { printf '%s\n' "$3" > "$SB/state/$1.$2"; }

# A host as the guard leaves it: wait-sync enabled and bounded, nvrtc first,
# both data-root units installed and ordered after time-sync.target.
guarded_host() {
  echo enabled > "$SB/state/enabled"
  set_prop systemd-time-wait-sync.service TimeoutStartUSec 5min
  set_prop nvrtc-sync-boot.service LoadState loaded
  set_prop nvrtc-sync-boot.service Before "systemd-timesyncd.service sysinit.target time-set.target"
  for u in orpheus-agent-audio-motion orpheus-ui; do
    set_prop "$u.service" LoadState loaded
    set_prop "$u.service" After "network.target time-sync.target orpheus-backplane.service"
  done
}

@test "verify: passes on a guarded Jetson" {
  guarded_host
  run "$CHECK"
  [ "$status" -eq 0 ]
  [[ "$output" == *"✅ systemd-time-wait-sync is enabled"* ]]
  [[ "$output" == *"bounded (5min)"* ]]
  [[ "$output" == *"✅ nvrtc-sync-boot runs before timesyncd"* ]]
  [[ "$output" == *"all 2 installed data-root services start after time-sync.target"* ]]
}

@test "verify: fails as jetson1 stood on 2026-11-21 (wait-sync off, nvrtc unordered)" {
  guarded_host
  echo disabled > "$SB/state/enabled"
  set_prop systemd-time-wait-sync.service TimeoutStartUSec infinity
  set_prop nvrtc-sync-boot.service Before ""
  run "$CHECK"
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌ systemd-time-wait-sync is disabled"* ]]
  [[ "$output" == *"❌ the wait for NTP is unbounded (infinity)"* ]]
  [[ "$output" == *"❌ nvrtc-sync-boot can run after timesyncd"* ]]
  [[ "$output" == *"make install-clock-guard"* ]]
}

@test "verify: names an installed data-root unit that does not wait for the clock" {
  guarded_host
  set_prop orpheus-agent-video-timelapser.service LoadState loaded
  set_prop orpheus-agent-video-timelapser.service After "network.target orpheus-backplane.service"
  run "$CHECK"
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌ not ordered after time-sync.target"*"orpheus-agent-video-timelapser.service"* ]]
}

@test "verify: a host without NVIDIA's RTC unit is not asked for its ordering" {
  guarded_host
  rm "$SB/state/nvrtc-sync-boot.service.LoadState"
  run "$CHECK"
  [ "$status" -eq 0 ]
  [[ "$output" != *"nvrtc-sync-boot"* ]]
}

@test "install: writes both drop-ins on a Jetson, enables wait-sync, restarts nothing" {
  set_prop nvrtc-sync-boot.service LoadState loaded
  ORPHEUS_CLOCK_ROOT="$SB/root" run "$INSTALL"
  [ "$status" -eq 0 ]
  cmp "$REPO_ROOT/deploy/clock/time-wait-sync.conf" \
      "$SB/root/etc/systemd/system/systemd-time-wait-sync.service.d/10-orpheus.conf"
  cmp "$REPO_ROOT/deploy/clock/nvrtc-sync-boot.conf" \
      "$SB/root/etc/systemd/system/nvrtc-sync-boot.service.d/10-orpheus.conf"
  grep -qx "daemon-reload" "$SB/calls"
  grep -qx "enable systemd-time-wait-sync.service" "$SB/calls"
  ! grep -qE '^(start|stop|restart|reload-or-restart|try-restart)|--now' "$SB/calls"
}

@test "install: off a Jetson, only the wait-sync drop-in is written" {
  ORPHEUS_CLOCK_ROOT="$SB/root" run "$INSTALL"
  [ "$status" -eq 0 ]
  [ -f "$SB/root/etc/systemd/system/systemd-time-wait-sync.service.d/10-orpheus.conf" ]
  [ ! -e "$SB/root/etc/systemd/system/nvrtc-sync-boot.service.d" ]
  [[ "$output" == *"not a Jetson"* ]]
}

@test "install: is idempotent" {
  set_prop nvrtc-sync-boot.service LoadState loaded
  ORPHEUS_CLOCK_ROOT="$SB/root" run "$INSTALL"
  ORPHEUS_CLOCK_ROOT="$SB/root" run "$INSTALL"
  [ "$status" -eq 0 ]
  [ "$(ls "$SB/root/etc/systemd/system/nvrtc-sync-boot.service.d")" = "10-orpheus.conf" ]
}

@test "the shipped drop-ins bound the wait and order nvrtc before timesyncd" {
  grep -qx 'TimeoutStartSec=300' "$REPO_ROOT/deploy/clock/time-wait-sync.conf"
  grep -qx 'DefaultDependencies=no' "$REPO_ROOT/deploy/clock/nvrtc-sync-boot.conf"
  grep -qE '^Before=.*systemd-timesyncd\.service' "$REPO_ROOT/deploy/clock/nvrtc-sync-boot.conf"
}
