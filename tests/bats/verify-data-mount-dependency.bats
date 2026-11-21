#!/usr/bin/env bats
# scripts/verify-data-mount-dependency.sh — services using the data root must
# wait for its drive. A fake systemctl reports what systemd has loaded.

load 'test_helper'

CHECK="$REPO_ROOT/scripts/verify-data-mount-dependency.sh"

setup() {
  SB="$BATS_TEST_TMPDIR"
  mkdir -p "$SB/units"
  cat > "$SB/systemctl" <<EOF2
#!/bin/bash
f="$SB/units/\$2"
case "\$4" in
  LoadState) [ -f "\$f" ] && echo loaded || echo not-found ;;
  RequiresMountsFor) [ -f "\$f" ] && cat "\$f" ;;
esac
EOF2
  chmod +x "$SB/systemctl"
  export SYSTEMCTL="$SB/systemctl"
}

# unit <name> <RequiresMountsFor value>: an installed, loaded unit.
unit() { printf '%s\n' "$2" > "$SB/units/$1.service"; }

@test "passes when every installed data-root service waits for the drive" {
  unit orpheus-agent-audio-motion "/opt/orpheus/agents/orpheus-agent-audio-motion /data/orpheus"
  unit orpheus-ui "/data/orpheus /opt/orpheus/ui"
  run "$CHECK" /data/orpheus
  [ "$status" -eq 0 ]
  [[ "$output" == *"✅ orpheus-agent-audio-motion.service waits for /data/orpheus"* ]]
  [[ "$output" == *"✅ orpheus-ui.service"* ]]
}

@test "fails on a loaded unit without the dependency (installed but never updated)" {
  unit orpheus-agent-event-correlator "/opt/orpheus/agents/orpheus-agent-event-correlator"
  run "$CHECK" /data/orpheus
  [ "$status" -eq 1 ]
  [[ "$output" == *"❌ orpheus-agent-event-correlator.service does not require /data/orpheus"* ]]
}

@test "a path that only starts with the data root does not count" {
  unit orpheus-storage-sweep "/data/orpheus-old"
  run "$CHECK" /data/orpheus
  [ "$status" -eq 1 ]
}

@test "services not installed on this host are skipped" {
  run "$CHECK" /data/orpheus
  [ "$status" -eq 0 ]
  [ -z "$output" ]
}
