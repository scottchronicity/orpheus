#!/usr/bin/env bash
# verify-broker.sh <orpheus.yaml> — probe the configured event-bus broker.
#
# The verify-deploy gap this closes: `make update-services` restarts agents that
# hard-require their broker at startup (Actor.start() -> bus.connect()), but
# nothing verified the broker actually answers before declaring the upgrade
# healthy — a missing backplane crash-loops every agent while systemd says
# "activating". Called from `make verify-deploy`; standalone-runnable for tests.
#
# Resolution order (mirrors OrpheusConfig: env wins over yaml, defaults last):
#   backend:  $ORPHEUS_EVENT_BUS__BACKEND > yaml event_bus.backend > "nats"
#   nats url: $ORPHEUS_EVENT_BUS__NATS_URL > <config dir>/.env (the systemd
#             EnvironmentFile upsert-backbone-env writes) > yaml event_bus.nats_url
#             > nats://127.0.0.1:4222
#   mqtt:     yaml mqtt.broker_host/broker_port > localhost:1883
#
# Exit 0: broker reachable, or no deployed config (not a deployed host — skip).
# Exit 1: config present but the configured broker does not answer.
# Best-effort yaml parsing (awk, top-level section + 1-deep key) — enough for the
# flat event_bus/mqtt sections; exotic yaml should set the env overrides instead.
set -u

CONFIG_FILE="${1:-/opt/orpheus/config/orpheus.yaml}"
PROBE_TIMEOUT="${PROBE_TIMEOUT:-3}"

if [ ! -f "$CONFIG_FILE" ]; then
  echo "⚠️  no deployed config at $CONFIG_FILE — broker probe skipped (not a deployed host)"
  exit 0
fi

# yaml_key <file> <section> <key> — first "key:" scalar inside a top-level
# "section:" block, quotes/comments stripped. Empty when absent.
yaml_key() {
  awk -v section="$2" -v key="$3" '
    $0 ~ "^"section":" { insec = 1; next }
    insec && /^[^[:space:]#]/ { insec = 0 }
    insec {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      if (line ~ "^"key":") {
        sub("^"key":[[:space:]]*", "", line)
        sub(/[[:space:]]*#.*$/, "", line)
        gsub(/["'\'']/, "", line)
        print line
        exit
      }
    }' "$1"
}

backend="${ORPHEUS_EVENT_BUS__BACKEND:-$(yaml_key "$CONFIG_FILE" event_bus backend)}"
backend="${backend:-nats}"

if [ "$backend" = "mqtt" ]; then
  host="$(yaml_key "$CONFIG_FILE" mqtt broker_host)"
  port="$(yaml_key "$CONFIG_FILE" mqtt broker_port)"
  host="${host:-localhost}"
  port="${port:-1883}"
  label="mqtt broker"
else
  # The per-host env file (upsert-backbone-env) outranks yaml, like systemd's
  # EnvironmentFile does at agent startup.
  env_file="$(dirname "$CONFIG_FILE")/.env"
  env_url=""
  if [ -f "$env_file" ]; then
    env_url="$(sed -n 's/^ORPHEUS_EVENT_BUS__NATS_URL=//p' "$env_file" | tail -n 1)"
  fi
  url="${ORPHEUS_EVENT_BUS__NATS_URL:-${env_url:-$(yaml_key "$CONFIG_FILE" event_bus nats_url)}}"
  url="${url:-nats://127.0.0.1:4222}"
  # nats://[user:pass@]host[:port] -> host, port (credentials never printed).
  hostport="${url#*://}"
  hostport="${hostport##*@}"
  host="${hostport%%:*}"
  port="${hostport##*:}"
  [ "$port" = "$host" ] && port=4222
  label="nats broker"
fi

if python3 -c "import socket,sys; socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=float(sys.argv[3])).close()" \
    "$host" "$port" "$PROBE_TIMEOUT" 2>/dev/null; then
  echo "✅ $label answers on $host:$port (event_bus.backend: $backend)"
  exit 0
fi

echo "❌ $label does NOT answer on $host:$port (event_bus.backend: $backend)"
echo "   Agents come up disconnected and publish NOTHING until it appears"
echo "   (silent by default; set event_bus.connect_required: true to hard-fail)."
if [ "$backend" = "mqtt" ]; then
  echo "   Check mosquitto: systemctl status mosquitto"
else
  echo "   Install/start the backplane: make install-backbone  (or: make -C services/orpheus-backplane restart)"
fi
exit 1
