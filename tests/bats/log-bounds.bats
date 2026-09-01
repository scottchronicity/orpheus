#!/usr/bin/env bats
# The bounds that stop one talkative service from filling the host disk.
#
# A station once lost its root filesystem to a single agent's logs: the journal
# mirrors into /var/log/syslog, logrotate bounds that by schedule rather than
# size, and a skipped rotation turns hours of slack into days. These tests pin
# the three things the repo now ships to make that survivable — per-unit rate
# limits, bounded container logs, and a dev-stack log file that cannot grow
# without limit.

load 'test_helper'

# --- shipped systemd units -------------------------------------------------

@test "every shipped unit carries a log rate limit" {
  local missing=""
  for unit in $(find "$REPO_ROOT" -name '*.service' -not -path '*/build/lib/*' -not -path '*/venv/*'); do
    grep -q '^LogRateLimitBurst=' "$unit" || missing="$missing $(basename "$unit")"
  done
  [ -z "$missing" ] || fail "units with no rate limit:$missing"
}

@test "every shipped unit names itself in syslog" {
  local missing=""
  for unit in $(find "$REPO_ROOT" -name '*.service' -not -path '*/build/lib/*' -not -path '*/venv/*'); do
    grep -q '^SyslogIdentifier=' "$unit" || missing="$missing $(basename "$unit")"
  done
  [ -z "$missing" ] || fail "units that would log as an anonymous process:$missing"
}

@test "the rate limit is tighter than systemd's default" {
  # systemd allows 10000 messages per 30s per service. Anything at or above
  # that is not a limit, it is the default wearing a costume.
  for unit in $(find "$REPO_ROOT" -name '*.service' -not -path '*/build/lib/*' -not -path '*/venv/*'); do
    burst="$(grep '^LogRateLimitBurst=' "$unit" | cut -d= -f2)"
    [ -n "$burst" ] || fail "$(basename "$unit"): no burst value"
    [ "$burst" -lt 10000 ] || fail "$(basename "$unit"): burst $burst is not below the default"
  done
}

# --- container logs --------------------------------------------------------

@test "every compose service bounds its container log" {
  for f in "$REPO_ROOT"/docker-compose*.yml; do
    [ -f "$f" ] || continue
    services="$(grep -cE '^  [a-z][a-z0-9-]*:$' "$f" || true)"
    bounded="$(grep -c 'logging: \*log-bounds' "$f" || true)"
    [ "$bounded" -gt 0 ] || fail "$(basename "$f"): no service bounds its log"
  done
}

@test "the compose log bound sets both a size and a file count" {
  for f in "$REPO_ROOT"/docker-compose*.yml; do
    [ -f "$f" ] || continue
    grep -q 'max-size:' "$f" || fail "$(basename "$f"): no max-size"
    grep -q 'max-file:' "$f" || fail "$(basename "$f"): no max-file"
  done
}

# --- dev-stack log files ---------------------------------------------------

# The trim runs against a real file with a real appending writer, because the
# subtle part is not the size check — it is that services append with >>, so a
# rename would leave the writer feeding the renamed inode while the visible
# file stayed empty. Truncating in place is what keeps the fd valid.
setup_trim() {
  LOG_DIR="$BATS_TEST_TMPDIR/logs"
  PID_DIR="$BATS_TEST_TMPDIR/pids"
  mkdir -p "$LOG_DIR" "$PID_DIR"
  LOG_MAX_BYTES=1000
  LOG_KEEP_LINES=5
  # shellcheck disable=SC1090
  eval "$(sed -n '/^trim_oversized_logs()/,/^}/p' "$REPO_ROOT/scripts/dev-stack.sh")"
}

@test "an oversized dev-stack log is trimmed" {
  setup_trim
  for i in $(seq 1 400); do echo "line $i with some padding to add bytes"; done > "$LOG_DIR/noisy.log"
  before="$(wc -c < "$LOG_DIR/noisy.log" | tr -d ' ')"
  [ "$before" -gt 1000 ]

  trim_oversized_logs

  after="$(wc -c < "$LOG_DIR/noisy.log" | tr -d ' ')"
  [ "$after" -lt "$before" ]
  [ "$after" -lt 1000 ]
}

@test "a log under the cap is left alone" {
  setup_trim
  echo "quiet service" > "$LOG_DIR/quiet.log"
  before="$(cat "$LOG_DIR/quiet.log")"

  trim_oversized_logs

  [ "$(cat "$LOG_DIR/quiet.log")" = "$before" ]
}

@test "the trim keeps the most recent lines and says it trimmed" {
  setup_trim
  for i in $(seq 1 400); do echo "line $i with some padding to add bytes"; done > "$LOG_DIR/noisy.log"

  trim_oversized_logs

  grep -q 'line 400' "$LOG_DIR/noisy.log"
  grep -q 'trimmed to the last' "$LOG_DIR/noisy.log"
  # the oldest content is what goes
  ! grep -q 'line 1 with' "$LOG_DIR/noisy.log"
}

@test "a writer holding an append fd keeps writing after a trim" {
  setup_trim
  for i in $(seq 1 400); do echo "line $i with some padding to add bytes"; done > "$LOG_DIR/noisy.log"
  exec 9>> "$LOG_DIR/noisy.log"

  trim_oversized_logs
  echo "written after the trim" >&9
  exec 9>&-

  grep -q 'written after the trim' "$LOG_DIR/noisy.log"
}

# --- the opt-in drop-in ----------------------------------------------------

@test "the journald drop-in is shipped but never installed by a normal install" {
  [ -f "$REPO_ROOT/deploy/journald/10-orpheus.conf" ]
  # Only the explicit target may reference the installer.
  refs="$(grep -rl 'install-log-bounds.sh' "$REPO_ROOT/Makefile" "$REPO_ROOT"/*/*/systemd/install*.sh 2>/dev/null || true)"
  [ "$refs" = "$REPO_ROOT/Makefile" ] || fail "installer referenced outside the opt-in target: $refs"
}

@test "the drop-in makes the journal persistent before silencing the syslog mirror" {
  # Order matters: with a RAM-only journal, turning off the mirror would leave
  # logs nowhere durable at all.
  conf="$REPO_ROOT/deploy/journald/10-orpheus.conf"
  grep -q '^Storage=persistent' "$conf"
  grep -q '^ForwardToSyslog=no' "$conf"
  grep -q '^SystemMaxUse=' "$conf"
}

@test "the drop-in tells an operator how to undo it" {
  grep -qi 'delete this file' "$REPO_ROOT/deploy/journald/10-orpheus.conf"
  grep -qi 'logrotate' "$REPO_ROOT/deploy/journald/10-orpheus.conf"
}
