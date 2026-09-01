#!/usr/bin/env bash
# Validate the distributed deployment config in docker-compose — no real hosts.
# Proves two things the per-host topology depends on:
#   1. cold-broker (E3): an agent pointed at a REMOTE backbone starts even when the
#      broker is down, and attaches when it appears (connect_required derived False).
#   2. env-seam topology: the agent connects via ORPHEUS_EVENT_BUS__NATS_URL
#      (nats://backbone-nuc:4222) — the production override, not sim.yaml's nats_url.
#
# Self-contained: tears the stack down on exit (success or failure).
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.dev.yml -f docker-compose.distributed.yml"

cleanup() { $COMPOSE --profile demo --profile fleet down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

fail() { echo "❌ FAIL: $1"; $COMPOSE logs orpheus-correlator 2>&1 | tail -25; exit 1; }

echo "==> 0. overlay config is valid"
$COMPOSE config -q

echo "==> 1. cold-broker (E3): start the correlator with NO backbone (remote env URL)"
$COMPOSE down -v >/dev/null 2>&1 || true
$COMPOSE up -d --build --no-deps orpheus-correlator
# The agent only logs 'starting disconnected and retrying' after its ~10s
# connect window expires — poll (up to 30s) rather than racing it with a
# fixed sleep (a 10s sleep vs the 10s window lost by milliseconds).
ok=""
for _ in $(seq 1 15); do
  if $COMPOSE logs orpheus-correlator 2>&1 | grep -q "starting disconnected"; then ok=1; break; fi
  sleep 2
done
state=$(docker inspect -f '{{.State.Status}}' "$($COMPOSE ps -q orpheus-correlator)" 2>/dev/null || echo missing)
echo "    correlator state with no broker: $state"
[ "$state" = "running" ] || fail "correlator exited without a broker (connect_required not honored)"
[ "$ok" = 1 ] || fail "no cold-broker 'starting disconnected and retrying' log"
echo "    PASS: survived a cold broker + logged the disconnected-retry"

echo "==> 2. env-seam: bring up the backbone (alias backbone-nuc); correlator must attach via the env URL"
$COMPOSE --profile demo up -d --build
ok=""
for _ in $(seq 1 30); do
  if $COMPOSE logs orpheus-correlator 2>&1 | grep -q "Connected to NATS.*backbone-nuc"; then ok=1; break; fi
  sleep 2
done
[ "$ok" = 1 ] || fail "correlator never connected via nats://backbone-nuc:4222 (env seam)"
echo "    PASS: correlator connected through the env-seam URL (backbone-nuc), not sim.yaml's nats_url"

echo "==> 3. cascade over the remote backbone (soft): sim-source -> correlator entity activity"
casc=""
for _ in $(seq 1 30); do
  if $COMPOSE logs orpheus-correlator 2>&1 | grep -qiE "entity|cluster|detection"; then casc=1; break; fi
  sleep 2
done
[ "$casc" = 1 ] && echo "    PASS: entity activity over the remote backbone" \
  || echo "    (note) no entity log seen in window — connection already proven in step 2"

echo "✅ sim-distributed-validate passed (cold-broker + env-seam topology)"
