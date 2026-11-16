#!/usr/bin/env bats
# scripts/check-dashboard-services.sh — stale dashboard.services entries.
# A fake systemctl answers `systemctl show` from fixtures; configs are written
# into the test sandbox. Nothing on the host is read or changed.

load 'test_helper'

CHECK="$REPO_ROOT/scripts/check-dashboard-services.sh"

setup() {
  SB="$BATS_TEST_TMPDIR"
  cat > "$SB/systemctl" <<'EOF2'
#!/bin/bash
case "$2" in
  orpheus-backplane.service) printf 'Id=orpheus-backplane.service\nLoadState=loaded\n' ;;
  orpheus-mqtt.service) printf 'Id=orpheus-backplane.service\nLoadState=loaded\n' ;;
  orpheus-audio-output.service) printf 'Id=orpheus-audio-output.service\nLoadState=loaded\n' ;;
  *) printf 'Id=%s\nLoadState=not-found\n' "$2" ;;
esac
EOF2
  chmod +x "$SB/systemctl"
  export SYSTEMCTL="$SB/systemctl"
}

config() { printf 'dashboard:\n  services:\n' > "$SB/orpheus.yaml"; for s in "$@"; do echo "    - \"$s\"" >> "$SB/orpheus.yaml"; done; }

@test "current inventory passes" {
  config orpheus-backplane orpheus-audio-output
  run "$CHECK" "$SB/orpheus.yaml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"✅ orpheus-backplane"* ]]
  [[ "$output" != *"⚠️"* ]]
}

@test "renamed unit left as an alias is flagged with its replacement" {
  config orpheus-mqtt
  run "$CHECK" "$SB/orpheus.yaml"
  [ "$status" -eq 1 ]
  [[ "$output" == *"orpheus-mqtt: an alias of orpheus-backplane.service"* ]]
  [[ "$output" == *"list 'orpheus-backplane'"* ]]
}

@test "retired unit is flagged as not installed" {
  config orpheus-bluetooth-autoconnect
  run "$CHECK" "$SB/orpheus.yaml"
  [ "$status" -eq 1 ]
  [[ "$output" == *"orpheus-bluetooth-autoconnect: not installed"* ]]
}

@test "no dashboard.services means the built-in default, not an error" {
  printf 'dashboard:\n  port: 8080\n' > "$SB/orpheus.yaml"
  run "$CHECK" "$SB/orpheus.yaml"
  [ "$status" -eq 0 ]
  [[ "$output" == *"built-in default"* ]]
}

@test "the shipped example config has no stale entries" {
  run "$CHECK" "$REPO_ROOT/config/orpheus.example.yaml"
  [[ "$output" != *"alias of"* ]]
}
