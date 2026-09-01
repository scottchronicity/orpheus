#!/bin/bash
#
# Install the NATS + JetStream broker for the Orpheus messaging backplane.
#
# Linux (Jetson/production): downloads the pinned nats-server binary for the
#   host arch into /usr/local/bin, installs the JetStream config + systemd unit,
#   creates the file-storage dir, enables + starts the service. Requires root.
# macOS (dev): installs nats-server via Homebrew; the service is run on demand
#   via `make start` / `make run` (no systemd on macOS).
#
set -e

# Pinned; override with NATS_VERSION=... Keep on the 2.x line (Python-3.9 client
# compatible; JetStream stable). brew on macOS tracks its own current 2.x.
NATS_VERSION="${NATS_VERSION:-2.10.22}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="$(dirname "$SCRIPT_DIR")"
OS="$(uname -s)"
ARCH="$(uname -m)"

# Seed the broker config ONCE, then leave it alone. Re-installing must not
# overwrite it: on a host whose broker was opened to the LAN
# (nats.distributed.conf, written by `make install-backbone LISTEN=...
# AUTH_FILE=...`), clobbering it with the shipped loopback config reverts the
# listener and cuts off every remote agent — from a step the rollout runbook
# calls idempotent. Re-run install-backbone with LISTEN=/AUTH_FILE= to change
# an existing listener.
seed_broker_config() {
    local src="$1" dst="$2"
    if [ -f "$dst" ]; then
        log_info "Existing broker config at $dst (left unchanged)"
    else
        install -m 0644 "$src" "$dst"
        log_info "Seeded $dst (loopback default)"
    fi
}

install_macos() {
    if ! command -v brew >/dev/null 2>&1; then
        log_error "Homebrew is required on macOS (https://brew.sh)"
        exit 1
    fi
    if brew list nats-server >/dev/null 2>&1; then
        log_info "nats-server already installed via Homebrew"
    else
        log_info "Installing nats-server via Homebrew..."
        brew install nats-server
    fi
    log_success "nats-server installed. Start the dev backplane with: make start"
    log_info "  (it runs config/nats.conf with JetStream under \$ORPHEUS_DATA_ROOT/backplane)"
}

install_linux() {
    if [[ $EUID -ne 0 ]]; then
        log_error "On Linux this must be run as root (sudo)"
        exit 1
    fi
    case "$ARCH" in
        aarch64 | arm64) nats_arch="arm64" ;;
        x86_64 | amd64) nats_arch="amd64" ;;
        *) log_error "Unsupported arch: $ARCH"; exit 1 ;;
    esac

    if command -v nats-server >/dev/null 2>&1; then
        log_info "nats-server already present: $(nats-server --version 2>&1 | head -1)"
    else
        local tarball="nats-server-v${NATS_VERSION}-linux-${nats_arch}.tar.gz"
        local url="https://github.com/nats-io/nats-server/releases/download/v${NATS_VERSION}/${tarball}"
        local tmp
        tmp="$(mktemp -d)"
        log_info "Downloading nats-server v${NATS_VERSION} (${nats_arch})..."
        curl -fsSL "$url" -o "$tmp/$tarball"
        tar -xzf "$tmp/$tarball" -C "$tmp"
        install -m 0755 "$tmp"/nats-server-v*/nats-server /usr/local/bin/nats-server
        rm -rf "$tmp"
        log_success "Installed $(nats-server --version 2>&1 | head -1) to /usr/local/bin"
    fi

    # Run as the shared 'orpheus' user+group (same as the agents). Create both
    # explicitly — useradd --system doesn't reliably create a matching group, and
    # install -d -g orpheus below needs it.
    if ! getent group orpheus >/dev/null 2>&1; then
        log_info "Creating system group 'orpheus'..."
        groupadd --system orpheus
    fi
    if ! id orpheus >/dev/null 2>&1; then
        log_info "Creating system user 'orpheus'..."
        useradd --system -g orpheus --no-create-home --shell /usr/sbin/nologin orpheus
    fi

    # Shared /etc/orpheus + /var/lib/orpheus, broker-scoped 'backplane' subdirs.
    install -d /etc/orpheus/backplane
    install -d -o orpheus -g orpheus /var/lib/orpheus/backplane/jetstream
    seed_broker_config "$SERVICE_DIR/config/nats.conf" /etc/orpheus/backplane/nats.conf
    install -m 0644 "$SERVICE_DIR/systemd/orpheus-backplane.service" \
        /etc/systemd/system/orpheus-backplane.service

    # Migrate off the old mosquitto-named unit: a leftover real
    # /etc/systemd/system/orpheus-mqtt.service would (a) keep stale mosquitto on
    # :1883 and (b) block the unit's Alias=orpheus-mqtt.service symlink on enable.
    if [ -f /etc/systemd/system/orpheus-mqtt.service ]; then
        log_info "Removing legacy orpheus-mqtt.service (superseded by orpheus-backplane)..."
        systemctl stop orpheus-mqtt.service 2>/dev/null || true
        systemctl disable orpheus-mqtt.service 2>/dev/null || true
        rm -f /etc/systemd/system/orpheus-mqtt.service
    fi

    systemctl daemon-reload
    systemctl enable orpheus-backplane.service
    systemctl restart orpheus-backplane.service

    # Post-install smoke (parity with the mosquitto installer): confirm it's up.
    if systemctl is-active --quiet orpheus-backplane.service; then
        log_success "orpheus-backplane (NATS+JetStream) installed, enabled + started"
        log_info "  config: /etc/orpheus/backplane/nats.conf   data: /var/lib/orpheus/backplane/jetstream"
    else
        log_error "orpheus-backplane failed to start; check: journalctl -u orpheus-backplane -n 50"
        exit 1
    fi
}

# Sourceable: tests exercise seed_broker_config without running the install.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    log_info "Installing Orpheus backplane broker: NATS + JetStream"
    case "$OS" in
        Darwin) install_macos ;;
        Linux) install_linux ;;
        *) log_error "Unsupported OS: $OS"; exit 1 ;;
    esac
fi
