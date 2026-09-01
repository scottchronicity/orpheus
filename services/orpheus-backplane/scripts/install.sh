#!/bin/bash
#
# Orpheus messaging backplane installer.
#
# Installs + configures the broker that carries the Orpheus "stream of
# consciousness". Broker is selectable so the backplane is a stable abstraction
# over the transport (see docs/designs/actor-model-and-control-plane.md):
#
#   BACKPLANE_BROKER=nats   (default)  -> NATS + JetStream
#   BACKPLANE_BROKER=mqtt              -> Mosquitto (fallback / legacy)
#
# Cross-platform: Linux (systemd, production Jetson) + macOS (Homebrew, dev).
#
# Usage:
#   sudo ./install.sh                 # Linux, default nats broker
#   ./install.sh                      # macOS (brew; no sudo)
#   BACKPLANE_BROKER=mqtt sudo ./install.sh
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROKER="${BACKPLANE_BROKER:-nats}"

case "$BROKER" in
    nats)
        exec bash "$SCRIPT_DIR/install-nats.sh"
        ;;
    mqtt | mosquitto)
        exec bash "$SCRIPT_DIR/install-mosquitto.sh"
        ;;
    *)
        echo "Unknown BACKPLANE_BROKER='$BROKER' (expected: nats | mqtt)" >&2
        exit 1
        ;;
esac
