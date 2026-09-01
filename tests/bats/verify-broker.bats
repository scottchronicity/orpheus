#!/usr/bin/env bats
# scripts/verify-broker.sh — the verify-deploy event-bus broker probe.
#
# The script is read-only and takes its config path as $1, so the tests run it
# in place against throwaway yaml/.env fixtures under BATS_TEST_TMPDIR, probing
# real loopback TCP ports (a python listener for "answers", a bound-then-closed
# port for "does not answer"). No real config or broker is touched.

load 'test_helper'

PROBE="$REPO_ROOT/scripts/verify-broker.sh"

setup() {
  CONFIG="$BATS_TEST_TMPDIR/orpheus.yaml"
  export PROBE_TIMEOUT=1
  # Never let the developer's real environment leak into a test.
  unset ORPHEUS_EVENT_BUS__BACKEND ORPHEUS_EVENT_BUS__NATS_URL
}

teardown() {
  if [ -n "${LISTENER_PID:-}" ]; then
    kill "$LISTENER_PID" 2>/dev/null || true
    LISTENER_PID=""
  fi
}

# Start a loopback TCP listener on a free port; sets LISTENER_PORT.
start_listener() {
  local port_file="$BATS_TEST_TMPDIR/listener_port"
  python3 -c '
import socket, sys, time
s = socket.socket()
s.bind(("127.0.0.1", 0))
s.listen(5)
with open(sys.argv[1], "w") as f:
    f.write(str(s.getsockname()[1]))
time.sleep(60)
' "$port_file" &
  LISTENER_PID=$!
  for _ in $(seq 1 50); do
    [ -s "$port_file" ] && break
    sleep 0.1
  done
  LISTENER_PORT="$(cat "$port_file")"
  [ -n "$LISTENER_PORT" ]
}

# A port nothing is listening on (bind ephemeral, close, reuse the number).
closed_port() {
  python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()'
}

@test "no deployed config: skips with a warning and exits 0" {
  run "$PROBE" "$BATS_TEST_TMPDIR/does-not-exist.yaml"
  assert_success
  assert_output --partial "broker probe skipped"
}

@test "mqtt backend: probes yaml broker_host/broker_port and succeeds when listening" {
  start_listener
  printf 'event_bus:\n  backend: "mqtt"\nmqtt:\n  broker_host: "127.0.0.1"\n  broker_port: %s\n' "$LISTENER_PORT" > "$CONFIG"
  run "$PROBE" "$CONFIG"
  assert_success
  assert_output --partial "✅ mqtt broker answers on 127.0.0.1:$LISTENER_PORT"
}

@test "mqtt backend: unreachable broker exits 1 and names mosquitto" {
  local port; port="$(closed_port)"
  printf 'event_bus:\n  backend: "mqtt"\nmqtt:\n  broker_host: "127.0.0.1"\n  broker_port: %s\n' "$port" > "$CONFIG"
  run "$PROBE" "$CONFIG"
  assert_failure 1
  assert_output --partial "❌ mqtt broker does NOT answer on 127.0.0.1:$port"
  assert_output --partial "mosquitto"
}

@test "nats is the default backend when yaml has no event_bus section" {
  start_listener
  printf 'site:\n  name: "x"\n' > "$CONFIG"
  ORPHEUS_EVENT_BUS__NATS_URL="nats://127.0.0.1:$LISTENER_PORT" run "$PROBE" "$CONFIG"
  assert_success
  assert_output --partial "nats broker answers"
  assert_output --partial "event_bus.backend: nats"
}

@test "nats url from yaml event_bus.nats_url; unreachable exits 1 pointing at install-backbone" {
  local port; port="$(closed_port)"
  printf 'event_bus:\n  backend: "nats"\n  nats_url: "nats://127.0.0.1:%s"\n' "$port" > "$CONFIG"
  run "$PROBE" "$CONFIG"
  assert_failure 1
  assert_output --partial "❌ nats broker does NOT answer on 127.0.0.1:$port"
  assert_output --partial "install-backbone"
}

@test "sibling .env (upsert-backbone-env) outranks the yaml nats_url" {
  start_listener
  local dead; dead="$(closed_port)"
  printf 'event_bus:\n  backend: "nats"\n  nats_url: "nats://127.0.0.1:%s"\n' "$dead" > "$CONFIG"
  printf 'ORPHEUS_EVENT_BUS__NATS_URL=nats://127.0.0.1:%s\n' "$LISTENER_PORT" > "$BATS_TEST_TMPDIR/.env"
  run "$PROBE" "$CONFIG"
  assert_success
  assert_output --partial "nats broker answers on 127.0.0.1:$LISTENER_PORT"
}

@test "process env outranks both the .env file and yaml" {
  start_listener
  local dead; dead="$(closed_port)"
  printf 'event_bus:\n  backend: "nats"\n  nats_url: "nats://127.0.0.1:%s"\n' "$dead" > "$CONFIG"
  printf 'ORPHEUS_EVENT_BUS__NATS_URL=nats://127.0.0.1:%s\n' "$dead" > "$BATS_TEST_TMPDIR/.env"
  ORPHEUS_EVENT_BUS__NATS_URL="nats://127.0.0.1:$LISTENER_PORT" run "$PROBE" "$CONFIG"
  assert_success
  assert_output --partial "nats broker answers on 127.0.0.1:$LISTENER_PORT"
}

@test "credentials in the backbone URL are never echoed (ADR 0018)" {
  start_listener
  printf 'event_bus:\n  backend: "nats"\n  nats_url: "nats://user:hunter2@127.0.0.1:%s"\n' "$LISTENER_PORT" > "$CONFIG"
  run "$PROBE" "$CONFIG"
  assert_success
  refute_output --partial "hunter2"
  assert_output --partial "nats broker answers on 127.0.0.1:$LISTENER_PORT"
}
