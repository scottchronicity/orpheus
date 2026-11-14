#!/usr/bin/env bats
# services/orpheus-audio-output/systemd/lifecycle.sh — the host steps the
# installer and rollback perform: lingering for the audio user, masking that
# user's stock PulseAudio units, retiring orpheus-bluetooth-autoconnect and
# other units that connect the same speaker, and undoing exactly those changes.
#
# Runs against a sandbox root ($SYSROOT under BATS_TEST_TMPDIR) with mocked
# systemctl / loginctl / getent / id. No real unit, user or file is touched.

load 'test_helper'

LIFECYCLE="$REPO_ROOT/services/orpheus-audio-output/systemd/lifecycle.sh"
MAC="FC:58:FA:02:AF:28"

setup() {
  export SYSROOT="$BATS_TEST_TMPDIR/root"
  export MOCK_LOG="$BATS_TEST_TMPDIR/calls"
  mkdir -p "$SYSROOT/etc/systemd/system" "$SYSROOT/usr/local/bin" "$SYSROOT/home/orpheus"
  BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$BIN"
  cat > "$BIN/systemctl" <<'EOF'
#!/bin/bash
echo "systemctl $*" >> "$MOCK_LOG"
if [ "$1" = is-enabled ]; then
  shift; [ "$1" = --quiet ] && shift
  grep -qx "enabled:$1" "$MOCK_LOG.state" 2>/dev/null
  exit $?
fi
exit 0
EOF
  cat > "$BIN/loginctl" <<'EOF'
#!/bin/bash
echo "loginctl $*" >> "$MOCK_LOG"
if [ "$1" = show-user ]; then cat "$MOCK_LOG.linger" 2>/dev/null || echo no; fi
exit 0
EOF
  cat > "$BIN/getent" <<'EOF'
#!/bin/bash
[ "$1" = passwd ] && echo "$2:x:1001:1002::/home/$2:/bin/bash"
EOF
  cat > "$BIN/id" <<'EOF'
#!/bin/bash
case "$1" in -u) echo 1001;; -g) echo 1002;; *) echo "uid=1001";; esac
EOF
  chmod +x "$BIN"/*
  export PATH="$BIN:$PATH"
  # shellcheck source=/dev/null
  source "$LIFECYCLE"
}

legacy_install() {
  printf '[Service]\nExecStart=/usr/local/bin/orpheus-bluetooth-connect\n' > "$UNIT_DIR/$LEGACY_UNIT"
  echo '#!/bin/bash' > "$LEGACY_SCRIPT"
}

@test "retiring the legacy service moves it aside and records it" {
  legacy_install
  run retire_legacy_autoconnect
  assert_success
  [ ! -e "$UNIT_DIR/$LEGACY_UNIT" ]
  [ ! -e "$LEGACY_SCRIPT" ]
  [ -f "$BACKUP_DIR/$LEGACY_UNIT" ]
  [ -f "$BACKUP_DIR/orpheus-bluetooth-connect" ]
  grep -qx "retired:$LEGACY_UNIT" "$CHANGES"
  grep -q "systemctl disable $LEGACY_UNIT" "$MOCK_LOG"
}

@test "retiring is a no-op when the legacy service is not installed" {
  run retire_legacy_autoconnect
  assert_success
  [ ! -e "$CHANGES" ]
}

@test "a hand-made unit connecting the same speaker is disabled; others are left alone" {
  printf '[Service]\nExecStart=/usr/bin/bluetoothctl connect %s\n' "$MAC" > "$UNIT_DIR/bluetooth-speaker-connect.service"
  printf '[Service]\nExecStart=/usr/bin/bluetoothctl connect 11:22:33:44:55:66\n' > "$UNIT_DIR/other-speaker.service"
  printf 'enabled:bluetooth-speaker-connect.service\nenabled:other-speaker.service\n' > "$MOCK_LOG.state"
  run disable_competing_units "$MAC"
  assert_success
  assert_output --partial "disabling competing unit bluetooth-speaker-connect.service"
  grep -qx "disabled:bluetooth-speaker-connect.service" "$CHANGES"
  run grep -q "other-speaker" "$CHANGES"
  assert_failure
}

@test "lingering is enabled once and only recorded when the installer enabled it" {
  run ensure_linger orpheus
  assert_success
  grep -q "loginctl enable-linger orpheus" "$MOCK_LOG"
  grep -qx "linger:orpheus" "$CHANGES"

  rm -f "$CHANGES" "$MOCK_LOG"
  echo yes > "$MOCK_LOG.linger"
  run ensure_linger orpheus
  assert_output --partial "already enabled"
  run grep -q "enable-linger" "$MOCK_LOG"
  assert_failure
  [ ! -e "$CHANGES" ]
}

@test "the user's stock PulseAudio units are masked, without touching other files" {
  mkdir -p "$SYSROOT/home/orpheus/.config/systemd/user"
  ln -s /dev/null "$SYSROOT/home/orpheus/.config/systemd/user/pulseaudio.service"
  run mask_stock_pulseaudio orpheus
  assert_success
  [ "$(readlink "$SYSROOT/home/orpheus/.config/systemd/user/pulseaudio.socket")" = /dev/null ]
  # The pre-existing mask (from the audio-motion setup) is not recorded as ours.
  grep -qx "mask:$SYSROOT/home/orpheus/.config/systemd/user/pulseaudio.socket" "$CHANGES"
  run grep -q "pulseaudio.service" "$CHANGES"
  assert_failure
}

@test "a real unit file in place of a mask is never overwritten" {
  mkdir -p "$SYSROOT/home/orpheus/.config/systemd/user"
  echo "[Unit]" > "$SYSROOT/home/orpheus/.config/systemd/user/pulseaudio.socket"
  run mask_stock_pulseaudio orpheus
  assert_output --partial "exists and is not a mask; leaving it alone"
  grep -qx "\[Unit\]" "$SYSROOT/home/orpheus/.config/systemd/user/pulseaudio.socket"
}

@test "rollback undoes every recorded change and restores the legacy service" {
  legacy_install
  printf '[Service]\nExecStart=/usr/bin/bluetoothctl connect %s\n' "$MAC" > "$UNIT_DIR/bluetooth-speaker-connect.service"
  echo "enabled:bluetooth-speaker-connect.service" > "$MOCK_LOG.state"
  ensure_linger orpheus
  mask_stock_pulseaudio orpheus
  retire_legacy_autoconnect
  disable_competing_units "$MAC"

  run undo_changes 1
  assert_success
  [ -f "$UNIT_DIR/$LEGACY_UNIT" ]
  [ -f "$LEGACY_SCRIPT" ]
  [ ! -e "$SYSROOT/home/orpheus/.config/systemd/user/pulseaudio.socket" ]
  grep -q "loginctl disable-linger orpheus" "$MOCK_LOG"
  grep -q "systemctl enable bluetooth-speaker-connect.service" "$MOCK_LOG"
  grep -q "systemctl enable $LEGACY_UNIT" "$MOCK_LOG"
  [ ! -e "$CHANGES" ]
}

@test "uninstall without restore keeps the legacy backup for a later rollback" {
  legacy_install
  retire_legacy_autoconnect
  ensure_linger orpheus
  run undo_changes 0
  assert_success
  [ ! -e "$UNIT_DIR/$LEGACY_UNIT" ]
  [ -f "$BACKUP_DIR/$LEGACY_UNIT" ]
  [ "$(cat "$CHANGES")" = "retired:$LEGACY_UNIT" ]

  run undo_changes 1
  [ -f "$UNIT_DIR/$LEGACY_UNIT" ]
  [ ! -e "$CHANGES" ]
}

@test "re-running the install steps does not duplicate records" {
  legacy_install
  ensure_linger orpheus
  retire_legacy_autoconnect
  echo yes > "$MOCK_LOG.linger"
  ensure_linger orpheus
  retire_legacy_autoconnect
  mask_stock_pulseaudio orpheus
  mask_stock_pulseaudio orpheus
  [ "$(sort "$CHANGES" | uniq -d | wc -l)" -eq 0 ]
}
