#!/usr/bin/env bats
# services/orpheus-bluetooth-autoconnect/scripts/orpheus-bluetooth-connect.sh
#
# Drives the real supervision loop (poll_once) against stateful mocks of
# bluetoothctl, su and id under BATS_TEST_TMPDIR. Each test changes the mock
# "world" between polls (speaker drops, bluetoothd hangs, PulseAudio goes
# away, ...) and checks what the script does next. No real Bluetooth, audio
# server or system configuration is touched.

load 'test_helper'

SCRIPT="$REPO_ROOT/services/orpheus-bluetooth-autoconnect/scripts/orpheus-bluetooth-connect.sh"
MAC="AA:BB:CC:DD:EE:FF"
SINK="bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink"

setup() {
  export BT_STATE="$BATS_TEST_TMPDIR/state"
  MOCK_BIN="$BATS_TEST_TMPDIR/bin"
  mkdir -p "$BT_STATE" "$MOCK_BIN"

  # World defaults: controller up, speaker paired + trusted + disconnected,
  # connects on request, PulseAudio running.
  echo up > "$BT_STATE/controller"
  echo disconnected > "$BT_STATE/device"
  echo yes > "$BT_STATE/trusted"
  echo ok > "$BT_STATE/connect_mode"

  cat > "$MOCK_BIN/bluetoothctl" <<'EOF'
#!/bin/bash
S="$BT_STATE"
echo "$*" >> "$S/calls"
if [ $# -eq 0 ]; then
  # Interactive (stdin) mode grows readline history without bound.
  echo "interactive" >> "$S/violations"
  cat > /dev/null
  exit 2
fi
ctl=$(cat "$S/controller")
if [ "$ctl" = hang ]; then exec /bin/sleep 30; fi
if [ "$ctl" = absent ]; then echo "No default controller available"; exit 1; fi
if [ "$1" = --timeout ]; then shift 2; fi
dev=$(cat "$S/device")
case "$1" in
  info)
    if [ "$dev" = unknown ]; then echo "Device $2 not available"; exit 1; fi
    echo "Device $2 (public)"
    echo "	Name: Test Speaker"
    if [ "$dev" = unpaired ]; then echo "	Paired: no"; else echo "	Paired: yes"; fi
    echo "	Trusted: $(cat "$S/trusted")"
    if [ "$dev" = connected ]; then echo "	Connected: yes"; else echo "	Connected: no"; fi
    ;;
  connect)
    echo "connect" >> "$S/connects"
    echo "Attempting to connect to $2"
    mode=$(cat "$S/connect_mode")
    if [ "$ctl" = off ]; then mode="fail:org.bluez.Error.NotReady"; fi
    if [ "$mode" = ok_after_scan ]; then
      if [ -f "$S/scanned" ]; then mode=ok; else mode="fail:org.bluez.Error.Failed"; fi
    fi
    case "$mode" in
      ok) echo connected > "$S/device"; echo "Connection successful" ;;
      fail:*) echo "Failed to connect: ${mode#fail:}"; exit 1 ;;
    esac
    ;;
  scan) echo scan >> "$S/scans"; touch "$S/scanned"; echo "Discovery started" ;;
  trust) echo yes > "$S/trusted"; echo "Changing $2 trust succeeded" ;;
  show)
    echo "Controller 00:00:00:00:00:01 (public)"
    if [ "$ctl" = off ]; then echo "	Powered: no"; else echo "	Powered: yes"; fi
    ;;
  power) echo up > "$S/controller"; echo "Changing power on succeeded" ;;
  *) echo "Invalid command"; exit 1 ;;
esac
EOF

  # su - <user> -c "<command>": records the user and answers pactl.
  cat > "$MOCK_BIN/su" <<'EOF'
#!/bin/bash
S="$BT_STATE"
[ "$1" = "-" ] && [ "$3" = "-c" ] || exit 1
echo "$2 :: $4" >> "$S/su.log"
cmd="$4"
if [ -f "$S/pulse_down" ]; then echo "Connection failure: Connection refused" >&2; exit 1; fi
case "$cmd" in
  *"pactl list sinks short"*)
    echo "0	alsa_output.platform-sound.analog-stereo	module-alsa-card.c	s16le 2ch 44100Hz	IDLE"
    if [ "$(cat "$S/device")" = connected ] && [ ! -f "$S/no_sink" ]; then
      echo "1	bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink	module-bluez5-device.c	s16le 2ch 44100Hz	SUSPENDED"
    fi
    ;;
  *"pactl set-default-sink"*)
    if [ -f "$S/set_sink_fail" ]; then echo "Failure: No such entity" >&2; exit 1; fi
    echo "${cmd##* }" > "$S/default_sink"
    ;;
esac
exit 0
EOF

  cat > "$MOCK_BIN/id" <<'EOF'
#!/bin/bash
[ "$1" = -u ] && [ "$2" != nosuchuser ] && { echo 1000; exit 0; }
echo "id: '$2': no such user" >&2
exit 1
EOF

  # Polls must not wait in tests; the SIGTERM test uses a PATH without this.
  cat > "$MOCK_BIN/sleep" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "$MOCK_BIN"/*

  export PULSE_RUNTIME_ROOT="$BATS_TEST_TMPDIR/run"
  pulse_up

  export PATH="$MOCK_BIN:$PATH"
  export BLUETOOTH_SPEAKER_MAC="$MAC"
  export AUDIO_USER=orpheus
  export ORPHEUS_BLUETOOTH_CONFIG="$BATS_TEST_TMPDIR/absent.env"
  export RECONNECT_DELAY=10 MAX_RECONNECT_DELAY=80 BT_COMMAND_TIMEOUT=2 BT_CONNECT_TIMEOUT=2
  export SINK_WAIT_SECONDS=3 STARTUP_DELAY=0
  export HOME="$BATS_TEST_TMPDIR/home"
}

# A real AF_UNIX socket where the script looks for the user's PulseAudio.
pulse_up() {
  mkdir -p "$PULSE_RUNTIME_ROOT/1000/pulse"
  python3 -c 'import socket,sys; socket.socket(socket.AF_UNIX).bind(sys.argv[1])' \
    "$PULSE_RUNTIME_ROOT/1000/pulse/native"
}

pulse_down() {
  rm -f "$PULSE_RUNTIME_ROOT/1000/pulse/native"
}

world() { echo "$2" > "$BT_STATE/$1"; }

# drive '<bash>' — source the script (without starting its loop) and run the
# snippet in one shell, so loop state carries across several poll_once calls.
# `report` prints the loop state for assertions.
drive() {
  run bash -c "source '$SCRIPT'
report() { echo \"REPORT state=\$DEVICE_STATE failures=\$FAILURES delay=\$NEXT_DELAY routed=\$AUDIO_ROUTED\"; }
$1"
}

count() { if [ -f "$BT_STATE/$1" ]; then wc -l < "$BT_STATE/$1" | tr -d ' '; else echo 0; fi; }

@test "connects at startup and routes audio to the speaker" {
  drive 'poll_once; report'
  assert_success
  assert_output --partial "state: startup -> disconnected"
  assert_output --partial "Connected to $MAC"
  assert_output --partial "Audio output switched to $SINK"
  assert_output --partial "REPORT state=connected failures=0 delay=10 routed=true"
  assert_equal "$(cat "$BT_STATE/default_sink")" "$SINK"
  grep -q '^orpheus :: export XDG_RUNTIME_DIR=' "$BT_STATE/su.log"
}

@test "never drives bluetoothctl interactively (unbounded history regression)" {
  world connect_mode "fail:org.bluez.Error.Failed br-connection-page-timeout"
  drive 'poll_once; poll_once; echo ok > "$BT_STATE/connect_mode"; poll_once; poll_once'
  assert_success
  [ ! -e "$BT_STATE/violations" ]
  [ ! -e "$HOME/.cache/.bluetoothctl_history" ]
}

@test "a healthy connection is polled quietly, without reconnecting" {
  drive 'poll_once; echo ---; poll_once; poll_once; report'
  assert_success
  quiet="${output#*---}"
  [[ "$quiet" != *"[INFO]"* && "$quiet" != *"[ERROR]"* ]]
  assert_output --partial "REPORT state=connected failures=0 delay=10 routed=true"
  assert_equal "$(count connects)" 1
}

@test "reconnects and re-routes audio after the speaker drops" {
  drive 'poll_once; rm -f "$BT_STATE/default_sink"; echo disconnected > "$BT_STATE/device"; poll_once; report'
  assert_success
  assert_output --partial "state: connected -> disconnected"
  assert_output --partial "Successfully connected to $MAC"
  assert_output --partial "REPORT state=connected failures=0 delay=10 routed=true"
  assert_equal "$(count connects)" 2
  assert_equal "$(cat "$BT_STATE/default_sink")" "$SINK"
}

@test "an unavailable speaker backs off exponentially, scanning once per outage" {
  world connect_mode "fail:org.bluez.Error.Failed br-connection-page-timeout"
  drive 'for i in 1 2 3 4 5 6; do poll_once; echo "DELAY $NEXT_DELAY"; done'
  assert_success
  assert_equal "$(echo "$output" | grep '^DELAY' | tr '\n' ' ')" "DELAY 10 DELAY 20 DELAY 40 DELAY 80 DELAY 80 DELAY 80 "
  assert_output --partial "br-connection-page-timeout"
  assert_equal "$(count scans)" 1
  # 2 connects on the first attempt (before and after the scan), then 1 each.
  assert_equal "$(count connects)" 7
}

@test "recovers when an unavailable speaker comes back, resetting the backoff" {
  world connect_mode "fail:org.bluez.Error.Failed br-connection-page-timeout"
  drive 'poll_once; poll_once; poll_once; echo ok > "$BT_STATE/connect_mode"; poll_once; report'
  assert_success
  assert_output --partial "Successfully connected to $MAC"
  assert_output --partial "REPORT state=connected failures=0 delay=10 routed=true"
}

@test "a speaker that only answers after a cache refresh connects on the first attempt" {
  world connect_mode ok_after_scan
  drive 'poll_once; report'
  assert_success
  assert_output --partial "Refreshing Bluetooth cache with scan"
  assert_output --partial "REPORT state=connected failures=0"
}

@test "without an audio server it does not attempt to connect, then recovers" {
  pulse_down
  drive 'poll_once; report; poll_once; report'
  assert_success
  assert_output --partial "No PulseAudio socket for orpheus"
  assert_output --partial "REPORT state=disconnected failures=2 delay=20 routed=false"
  assert_equal "$(count connects)" 0

  pulse_up
  drive 'poll_once; report'
  assert_success
  assert_output --partial "REPORT state=connected failures=0 delay=10 routed=true"
}

@test "REQUIRE_AUDIO_SERVER=false connects without probing for PulseAudio" {
  pulse_down
  export REQUIRE_AUDIO_SERVER=false
  world no_sink 1
  drive 'poll_once; report'
  assert_success
  assert_equal "$(count connects)" 1
  assert_output --partial "REPORT state=connected failures=1"
  assert_output --partial "did not become available"
}

@test "a hung bluetoothd is bounded by the command timeout and recovers" {
  world controller hang
  export BT_COMMAND_TIMEOUT=1
  drive 'poll_once; report'
  assert_success
  assert_output --partial "BlueZ did not answer (bluetoothctl timed out after 1s)"
  assert_output --partial "REPORT state=unavailable failures=1"
  assert_equal "$(count connects)" 0

  # bluetooth.service restarted: the speaker reconnects on the next poll.
  world controller up
  drive 'poll_once; report'
  assert_success
  assert_output --partial "REPORT state=connected failures=0"
}

@test "a missing controller is reported and retried without connecting" {
  world controller absent
  drive 'poll_once; report'
  assert_success
  assert_output --partial "No Bluetooth controller available"
  assert_output --partial "REPORT state=no_controller failures=1"
  assert_equal "$(count connects)" 0
}

@test "a powered-off controller is powered on before connecting" {
  world controller off
  drive 'poll_once; report'
  assert_success
  assert_output --partial "powering it on"
  grep -qx 'power on' "$BT_STATE/calls"
  assert_output --partial "REPORT state=connected failures=0"
}

@test "a device BlueZ no longer knows gets a pairing hint and a scan" {
  world device unknown
  world connect_mode "fail:org.bluez.Error.DoesNotExist"
  drive 'poll_once; report'
  assert_success
  assert_output --partial "is not known to BlueZ. Pair it once"
  assert_output --partial "REPORT state=missing failures=1"
  assert_equal "$(count scans)" 1
}

@test "an unpaired device gets a pairing hint" {
  world device unpaired
  world connect_mode "fail:org.bluez.Error.AuthenticationFailed"
  drive 'poll_once; report'
  assert_success
  assert_output --partial "known but not paired"
}

@test "an untrusted device is trusted before connecting" {
  world trusted no
  drive 'poll_once; report'
  assert_success
  assert_output --partial "Device $MAC trusted"
  assert_equal "$(cat "$BT_STATE/trusted")" yes
  assert_output --partial "REPORT state=connected failures=0"
}

@test "a failing set-default-sink no longer kills the loop and is retried" {
  world set_sink_fail 1
  drive 'poll_once; report; rm -f "$BT_STATE/set_sink_fail"; poll_once; report'
  assert_success
  assert_output --partial "Failed to switch audio output to $SINK: Failure: No such entity"
  assert_output --partial "REPORT state=connected failures=1 delay=10 routed=false"
  assert_output --partial "REPORT state=connected failures=0 delay=10 routed=true"
  # The link was kept: one connect only.
  assert_equal "$(count connects)" 1
}

@test "an unknown audio user does not stop the Bluetooth connection" {
  export AUDIO_USER=nosuchuser REQUIRE_AUDIO_SERVER=false
  drive 'poll_once; report'
  assert_success
  assert_output --partial "Unable to get UID for user: nosuchuser"
  assert_output --partial "REPORT state=connected failures=1"
}

@test "pactl runs as AUDIO_USER, and an unsafe AUDIO_USER is refused" {
  export AUDIO_USER=birder
  drive 'poll_once; report'
  assert_success
  grep -q '^birder :: export XDG_RUNTIME_DIR=' "$BT_STATE/su.log"

  rm -f "$BT_STATE/su.log"
  world device disconnected
  export AUDIO_USER='bad;user' REQUIRE_AUDIO_SERVER=false
  drive 'poll_once; report'
  assert_success
  assert_output --partial "Invalid AUDIO_USER: bad;user"
  [ ! -e "$BT_STATE/su.log" ]
}

@test "settings come from the config file" {
  cat > "$BATS_TEST_TMPDIR/config.env" <<EOF
BLUETOOTH_SPEAKER_MAC=11:22:33:44:55:66
RECONNECT_DELAY=7
EOF
  export ORPHEUS_BLUETOOTH_CONFIG="$BATS_TEST_TMPDIR/config.env"
  drive 'echo "$BLUETOOTH_MAC $RECONNECT_DELAY"'
  assert_success
  assert_output "11:22:33:44:55:66 7"
}

@test "an invalid MAC exits 78 so systemd does not restart-loop" {
  export BLUETOOTH_SPEAKER_MAC="not-a-mac"
  run bash "$SCRIPT"
  assert_failure 78
  assert_output --partial "Invalid BLUETOOTH_SPEAKER_MAC 'not-a-mac'"
}

@test "SIGTERM during a backoff sleep stops the service promptly" {
  rm -f "$MOCK_BIN/sleep"
  world connect_mode "fail:org.bluez.Error.Failed br-connection-page-timeout"
  export RECONNECT_DELAY=300 MAX_RECONNECT_DELAY=300
  bash "$SCRIPT" > "$BATS_TEST_TMPDIR/svc.log" 2>&1 &
  pid=$!
  for _ in $(seq 1 100); do
    grep -q "will retry in 300 seconds" "$BATS_TEST_TMPDIR/svc.log" && break
    /bin/sleep 0.1
  done
  grep -q "will retry in 300 seconds" "$BATS_TEST_TMPDIR/svc.log"
  start=$(date +%s)
  kill -TERM "$pid"
  rc=0
  wait "$pid" || rc=$?
  [ "$rc" -eq 0 ]
  [ $(( $(date +%s) - start )) -le 3 ]
  grep -q "stopping" "$BATS_TEST_TMPDIR/svc.log"
}
