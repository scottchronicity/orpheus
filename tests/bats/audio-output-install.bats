#!/usr/bin/env bats
# services/orpheus-audio-output/systemd/install-service.sh + uninstall-service.sh,
# run end to end in a sandbox root (see audio_output_helper.bash): preflight
# changes nothing, a failed install restores the previous installation and
# every service's enabled/running state, masks are verified through the user's
# systemd manager, and rollback restores what was running before.

load 'test_helper'
load 'audio_output_helper'

SVC="$REPO_ROOT/services/orpheus-audio-output/systemd"
LEGACY=orpheus-bluetooth-autoconnect.service
NEW=orpheus-audio-output.service
COMPETING=bluetooth-speaker-connect.service

setup() {
  audio_output_sandbox
  UNITS="$SYSROOT/etc/systemd/system"
  DEPLOY="$SYSROOT/opt/orpheus/services/orpheus-audio-output"
  STATE="$SYSROOT/var/lib/orpheus-audio-output"
  MASKS="$SYSROOT/home/orpheus/.config/systemd/user"
}

install_new() { run bash "$SVC/install-service.sh"; }

assert_host_untouched() {
  [ -f "$UNITS/$LEGACY" ]
  [ ! -e "$UNITS/$NEW" ]
  [ ! -e "$STATE/changes" ]
  [ ! -e "$STATE/changes.run" ]
  [ ! -e "$MASKS/pulseaudio.socket" ]
  run grep -E "systemctl (stop|disable|enable|restart|start) |loginctl enable-linger|pkill" "$MOCK_LOG"
  assert_failure
  is_enabled "$LEGACY"
  is_active "$LEGACY"
}

# --- preflight -----------------------------------------------------------------
@test "an invalid configuration changes nothing" {
  legacy_installed; unit_on "$LEGACY" enabled active
  echo '{"valid": false, "error": "audio_output.server.type '"'"'pipewire'"'"' is not supported"}' > "$FAKE_CHECK_JSON"
  export FAKE_CHECK_RC=78
  install_new
  assert_failure
  assert_output --partial "preflight failed: nothing on this host was changed"
  assert_host_untouched
  [ -z "$(ls -d "$DEPLOY".stage.* 2>/dev/null)" ]  # staging cleaned up
}

@test "a missing PulseAudio Bluetooth module fails preflight and changes nothing" {
  legacy_installed; unit_on "$LEGACY" enabled active
  rm "$SYSROOT/usr/lib/pulse-13.99.1/modules/module-bluetooth-discover.so"
  install_new
  assert_failure
  assert_output --partial "module-bluetooth-discover not found"
  assert_host_untouched
}

@test "a missing audio user fails preflight and changes nothing" {
  legacy_installed; unit_on "$LEGACY" enabled active
  export FAKE_NO_USER=1
  install_new
  assert_failure
  assert_output --partial "user 'orpheus' does not exist"
  assert_host_untouched
}

@test "a real unit file where a mask must go fails preflight" {
  legacy_installed; unit_on "$LEGACY" enabled active
  mkdir -p "$MASKS"; echo "[Unit]" > "$MASKS/pulseaudio.socket"
  install_new
  assert_failure
  assert_output --partial "is a real unit file"
  run grep -q "systemctl stop" "$MOCK_LOG"
  assert_failure
}

@test "an existing deployment is untouched until preflight passes" {
  mkdir -p "$DEPLOY"; echo previous > "$DEPLOY/sentinel"
  export FAKE_CHECK_RC=78
  install_new
  assert_failure
  [ "$(cat "$DEPLOY/sentinel")" = previous ]
}

# --- successful install --------------------------------------------------------
@test "a successful install records prior states and verifies the masks" {
  legacy_installed; unit_on "$LEGACY" enabled active
  competing_unit; unit_on "$COMPETING" enabled
  touch "$MOCK/stock-pa"
  install_new
  assert_success
  [ -f "$DEPLOY/venv/bin/python" ]
  [ ! -e "$DEPLOY.previous" ]
  is_enabled "$NEW"
  is_active "$NEW"
  refute_enabled "$LEGACY"
  refute_active "$LEGACY"
  [ ! -e "$UNITS/$LEGACY" ]
  [ -f "$STATE/legacy/$LEGACY" ]
  refute_enabled "$COMPETING"
  grep -qx "retired:$LEGACY:yes:yes" "$STATE/changes"
  grep -qx "unit:$COMPETING:yes:no" "$STATE/changes"
  grep -qx "linger:orpheus" "$STATE/changes"
  grep -qx "pulseaudio-stopped:orpheus" "$STATE/changes"
  [ ! -e "$STATE/changes.run" ]
  # Masks were followed by a reload of orpheus's manager, and verified.
  [ -s "$MOCK/user-reloads" ]
  assert_output --partial "stock pulseaudio.socket/.service are masked and inactive"
}

@test "an active stock pulseaudio.socket is stopped before verification" {
  touch "$MOCK/user-manager" "$MOCK/user-socket-active"
  install_new
  assert_success
  grep -q "runuser .* systemctl --user stop pulseaudio.socket" "$MOCK_LOG"
  [ ! -e "$MOCK/user-socket-active" ]
}

# --- failed install restores the previous installation -------------------------
@test "masks that the user manager does not honour abort and restore" {
  legacy_installed; unit_on "$LEGACY" enabled active
  export FAKE_USER_LOADSTATE=loaded
  install_new
  assert_failure
  assert_output --partial "reports pulseaudio.socket LoadState=loaded, not masked"
  assert_output --partial "previous installation restored"
  [ -f "$UNITS/$LEGACY" ]
  is_enabled "$LEGACY"
  is_active "$LEGACY"
  [ ! -e "$MASKS/pulseaudio.socket" ]
  [ ! -e "$UNITS/$NEW" ]
  [ ! -e "$DEPLOY" ]
}

@test "a server that never becomes ready restores every prior service state" {
  legacy_installed; unit_on "$LEGACY" enabled active
  competing_unit; unit_on "$COMPETING" enabled active
  echo '{"status": "unhealthy", "server": {"state": "failed", "detail": "PulseAudio exited during startup with code 1", "consecutive_failures": 2}, "capture_isolation": {"ok": true}}' > "$FAKE_HEALTH"
  install_new
  assert_failure
  assert_output --partial "server failed: PulseAudio exited during startup"
  # Legacy back in place, enabled and running as before.
  [ -f "$UNITS/$LEGACY" ]
  [ -f "$SYSROOT/usr/local/bin/orpheus-bluetooth-connect" ]
  is_enabled "$LEGACY"
  is_active "$LEGACY"
  # The competing unit was enabled and running: both restored.
  is_enabled "$COMPETING"
  is_active "$COMPETING"
  # This run's host changes undone; the new service gone.
  [ ! -e "$MASKS/pulseaudio.socket" ]
  [ ! -e "$MOCK/linger" ]
  refute_enabled "$NEW"
  refute_active "$NEW"
  [ ! -e "$UNITS/$NEW" ]
  [ ! -e "$DEPLOY" ]
  [ ! -e "$STATE/changes" ]
  [ ! -e "$STATE/changes.run" ]
}

@test "capture isolation failing at startup restores the previous installation" {
  legacy_installed; unit_on "$LEGACY" enabled active
  echo '{"server": {"state": "ready"}, "capture_isolation": {"ok": false, "problems": ["PulseAudio loaded module-udev-detect"]}}' > "$FAKE_HEALTH"
  install_new
  assert_failure
  assert_output --partial "capture isolation not ok"
  is_active "$LEGACY"
}

@test "a unit that dies on start restores the previous installation" {
  legacy_installed; unit_on "$LEGACY" enabled active
  export FAKE_UNIT_DIES=1
  install_new
  assert_failure
  assert_output --partial "is not running"
  is_enabled "$LEGACY"
  is_active "$LEGACY"
}

@test "a failed update restores the previous version and keeps older records" {
  mkdir -p "$DEPLOY"; echo v0.1 > "$DEPLOY/sentinel"
  echo "# previous unit" > "$UNITS/$NEW"
  unit_on "$NEW" enabled active
  mkdir -p "$STATE"; printf 'linger:orpheus\nretired:%s:yes:yes\n' "$LEGACY" > "$STATE/changes"
  touch "$MOCK/linger" "$MOCK/user-manager"
  mkdir -p "$MASKS"; ln -s /dev/null "$MASKS/pulseaudio.socket"; ln -s /dev/null "$MASKS/pulseaudio.service"
  echo '{"server": {"state": "failed", "detail": "boom", "consecutive_failures": 3}, "capture_isolation": {"ok": true}}' > "$FAKE_HEALTH"
  install_new
  assert_failure
  [ "$(cat "$DEPLOY/sentinel")" = v0.1 ]
  [ "$(cat "$UNITS/$NEW")" = "# previous unit" ]
  is_enabled "$NEW"
  is_active "$NEW"
  [ "$(cat "$STATE/changes")" = "$(printf 'linger:orpheus\nretired:%s:yes:yes' "$LEGACY")" ]
  [ -e "$MOCK/linger" ]
  [ -L "$MASKS/pulseaudio.socket" ]  # earlier install's changes kept
}

# --- rollback ------------------------------------------------------------------
@test "rollback restores each service's enabled and running state" {
  legacy_installed; unit_on "$LEGACY" enabled          # enabled, not running
  competing_unit; unit_on "$COMPETING" enabled active  # enabled and running
  install_new
  assert_success
  RESTORE_LEGACY=1 run bash "$SVC/uninstall-service.sh"
  assert_success
  [ -f "$UNITS/$LEGACY" ]
  is_enabled "$LEGACY"
  refute_active "$LEGACY"                                 # it was not running before
  is_enabled "$COMPETING"
  is_active "$COMPETING"
  [ ! -e "$UNITS/$NEW" ]
  refute_active "$NEW"
  [ ! -e "$DEPLOY" ]
  [ ! -e "$MASKS/pulseaudio.socket" ]
  [ ! -e "$MOCK/linger" ]
  [ ! -e "$STATE/changes" ]
}

@test "uninstall without restore leaves the legacy service retired, restorable later" {
  legacy_installed; unit_on "$LEGACY" enabled active
  install_new
  run bash "$SVC/uninstall-service.sh"
  assert_success
  [ ! -e "$UNITS/$LEGACY" ]
  refute_active "$LEGACY"
  grep -qx "retired:$LEGACY:yes:yes" "$STATE/changes"
  RESTORE_LEGACY=1 run bash "$SVC/uninstall-service.sh"
  is_enabled "$LEGACY"
  is_active "$LEGACY"
}
