#!/usr/bin/env bats
# services/orpheus-audio-output/systemd/lifecycle.sh — the individual host
# steps: lingering, masking the audio user's stock PulseAudio units (and
# verifying them through that user's systemd manager), retiring
# orpheus-bluetooth-autoconnect, disabling units that connect the same
# speaker, and undoing each change with the prior enabled/running state.
# Sandbox root and mocks: audio_output_helper.bash.

load 'test_helper'
load 'audio_output_helper'

MAC="FC:58:FA:02:AF:28"

setup() {
  audio_output_sandbox
  # shellcheck source=/dev/null
  source "$REPO_ROOT/services/orpheus-audio-output/systemd/lifecycle.sh"
  HOME_UNITS="$SYSROOT/home/orpheus/.config/systemd/user"
}

@test "retiring the legacy service records whether it was enabled and running" {
  legacy_installed
  unit_on "$LEGACY_UNIT" enabled
  run retire_legacy_autoconnect
  assert_success
  [ ! -e "$UNIT_DIR/$LEGACY_UNIT" ]
  [ -f "$BACKUP_DIR/$LEGACY_UNIT" ]
  [ -f "$BACKUP_DIR/orpheus-bluetooth-connect" ]
  grep -qx "retired:$LEGACY_UNIT:yes:no" "$CHANGES"
  refute_enabled "$LEGACY_UNIT"
}

@test "retiring is a no-op when the legacy service is not installed" {
  run retire_legacy_autoconnect
  assert_success
  [ ! -e "$CHANGES" ]
}

@test "only units connecting the same speaker are stopped, with their state recorded" {
  competing_unit
  unit_on bluetooth-speaker-connect.service enabled active
  printf '[Service]\nExecStart=/usr/bin/bluetoothctl connect 11:22:33:44:55:66\n' > "$UNIT_DIR/other.service"
  unit_on other.service enabled active
  run disable_competing_units "$MAC"
  assert_success
  grep -qx "unit:bluetooth-speaker-connect.service:yes:yes" "$CHANGES"
  refute_active bluetooth-speaker-connect.service
  refute_enabled bluetooth-speaker-connect.service
  is_active other.service
  run grep -q other.service "$CHANGES"
  assert_failure
}

@test "a matching unit that is neither enabled nor running is left alone" {
  competing_unit
  run disable_competing_units "$MAC"
  assert_success
  [ ! -e "$CHANGES" ]
}

@test "lingering is enabled once and only recorded when the installer enabled it" {
  run ensure_linger orpheus
  grep -qx "linger:orpheus" "$CHANGES"
  rm -f "$CHANGES"
  run ensure_linger orpheus
  assert_output --partial "already enabled"
  [ ! -e "$CHANGES" ]
}

@test "masks are created, recorded with their user, and never replace a real file" {
  mkdir -p "$HOME_UNITS"
  ln -s /dev/null "$HOME_UNITS/pulseaudio.service"   # the audio-motion setup's mask
  run mask_stock_pulseaudio orpheus
  assert_success
  [ "$(readlink "$HOME_UNITS/pulseaudio.socket")" = /dev/null ]
  grep -qx "mask:orpheus:$HOME_UNITS/pulseaudio.socket" "$CHANGES"
  run grep -q "pulseaudio.service" "$CHANGES"
  assert_failure

  rm "$HOME_UNITS/pulseaudio.socket"
  echo "[Unit]" > "$HOME_UNITS/pulseaudio.socket"
  run mask_stock_pulseaudio orpheus
  assert_failure
  assert_output --partial "refusing to replace it"
}

@test "mask verification reloads the running user manager first" {
  touch "$MOCK/user-manager"
  mask_stock_pulseaudio orpheus
  run reload_and_verify_masks orpheus
  assert_success
  [ -s "$MOCK/user-reloads" ]
  grep -q "runuser -u orpheus -- env XDG_RUNTIME_DIR=/run/user/1001 .* systemctl --user daemon-reload" "$MOCK_LOG"
}

@test "verification fails if the manager still loads the stock socket" {
  touch "$MOCK/user-manager"
  mask_stock_pulseaudio orpheus
  export FAKE_USER_LOADSTATE=loaded
  run reload_and_verify_masks orpheus
  assert_failure
  assert_output --partial "LoadState=loaded, not masked"
}

@test "verification fails when a unit is not masked on disk" {
  run reload_and_verify_masks orpheus
  assert_failure
  assert_output --partial "pulseaudio.socket is not masked"
}

@test "without a running user manager the masks cannot be verified" {
  mask_stock_pulseaudio orpheus
  run reload_and_verify_masks orpheus
  assert_failure
  assert_output --partial "cannot verify the masks"
}

@test "undo restores each unit's prior state, newest change first" {
  legacy_installed
  unit_on "$LEGACY_UNIT" enabled active
  competing_unit
  unit_on bluetooth-speaker-connect.service enabled
  touch "$MOCK/user-manager"
  ensure_linger orpheus
  mask_stock_pulseaudio orpheus
  retire_legacy_autoconnect
  disable_competing_units "$MAC"

  run undo_changes "$CHANGES" 1
  assert_success
  [ -f "$UNIT_DIR/$LEGACY_UNIT" ]
  [ -f "$LEGACY_SCRIPT" ]
  is_enabled "$LEGACY_UNIT"
  is_active "$LEGACY_UNIT"
  is_enabled bluetooth-speaker-connect.service
  refute_active bluetooth-speaker-connect.service      # it was not running before
  [ ! -e "$HOME_UNITS/pulseaudio.socket" ]
  [ ! -e "$MOCK/linger" ]
  [ ! -e "$CHANGES" ]
}

@test "undo without restore keeps the legacy backup and its record" {
  legacy_installed
  unit_on "$LEGACY_UNIT" enabled active
  retire_legacy_autoconnect
  ensure_linger orpheus
  run undo_changes "$CHANGES" 0
  assert_success
  [ -f "$BACKUP_DIR/$LEGACY_UNIT" ]
  [ "$(cat "$CHANGES")" = "retired:$LEGACY_UNIT:yes:yes" ]
}

@test "a run's changes merge into the record only when committed" {
  export RUN_CHANGES="$STATE_DIR/changes.run"
  mkdir -p "$STATE_DIR"
  echo "linger:orpheus" > "$CHANGES"
  record "mask:orpheus:/x"
  [ "$(cat "$CHANGES")" = "linger:orpheus" ]
  commit_run_changes
  [ "$(cat "$CHANGES")" = "$(printf 'linger:orpheus\nmask:orpheus:/x')" ]
  [ ! -e "$RUN_CHANGES" ]
}

@test "PulseAudio modules are found in any installed version directory" {
  run find_pulse_module module-bluetooth-discover
  assert_success
  run find_pulse_module module-alsa-card
  assert_failure
}

@test "a real venv renamed into place keeps working scripts" {
  stage="$BATS_TEST_TMPDIR/opt/svc.stage.a1B2c3"
  final="$BATS_TEST_TMPDIR/opt/svc"
  python3 -m venv "$stage/venv"
  grep -qF "$stage" "$stage/venv/bin/pip"            # pip's shebang names the stage
  relocate_venv "$stage/venv" "$stage" "$final"
  mv "$stage" "$final"
  run verify_venv "$final/venv" "$stage"
  assert_success
  run "$final/venv/bin/pip" --version
  assert_success
  assert_output --partial "$final/venv"
  run grep -rlF "$stage" "$final/venv/bin"
  assert_failure
}

@test "without relocation the renamed venv's scripts are caught as broken" {
  stage="$BATS_TEST_TMPDIR/opt/svc.stage.zz9"
  final="$BATS_TEST_TMPDIR/opt/svc"
  python3 -m venv "$stage/venv"
  mv "$stage" "$final"
  run verify_venv "$final/venv" "$stage"
  assert_failure
  assert_output --partial "still references $stage"
  assert_output --partial "is not executable"
  run "$final/venv/bin/pip" --version
  assert_failure
}
