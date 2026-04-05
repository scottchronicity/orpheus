#!/bin/bash
#
# Orpheus MQTT Broker Installation Script
#
# This script installs and configures the Mosquitto MQTT broker for the
# Orpheus wildlife monitoring system. It sets up persistence, logging, and
# systemd service management.
#
# Usage: sudo ./install.sh
#

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Track post-install test outcome for summary
POST_INSTALL_TEST_STATUS="not-run"

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if script is run as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root or with sudo"
    echo "Usage: sudo $0"
    exit 1
fi

log_info "Starting Orpheus MQTT Broker installation..."

# Determine the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MQTT_BROKER_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration paths
# Note: /etc/orpheus/ and /var/lib/orpheus/ are shared by ALL Orpheus services
ORPHEUS_ROOT_CONFIG_DIR="/etc/orpheus"
ORPHEUS_MQTT_CONFIG_DIR="${ORPHEUS_ROOT_CONFIG_DIR}/mqtt"
MOSQUITTO_CONF="${ORPHEUS_MQTT_CONFIG_DIR}/mosquitto.conf"
SYSTEMD_SERVICE_SRC="${MQTT_BROKER_DIR}/systemd/orpheus-mqtt.service"
SYSTEMD_SERVICE_DEST="/etc/systemd/system/orpheus-mqtt.service"
ORPHEUS_ROOT_DATA_DIR="/var/lib/orpheus"
PERSISTENCE_DIR="${ORPHEUS_ROOT_DATA_DIR}/mqtt"

# Check if mosquitto configuration exists
MOSQUITTO_CONF_SRC="${MQTT_BROKER_DIR}/config/mosquitto.conf"
if [[ ! -f "$MOSQUITTO_CONF_SRC" ]]; then
    log_error "Mosquitto configuration not found at: $MOSQUITTO_CONF_SRC"
    exit 1
fi

# Check if systemd service file exists
if [[ ! -f "$SYSTEMD_SERVICE_SRC" ]]; then
    log_error "Systemd service file not found at: $SYSTEMD_SERVICE_SRC"
    exit 1
fi

# Step 1: Install Mosquitto MQTT broker
log_info "Installing Mosquitto MQTT broker..."
log_info "Mosquitto 2.0+ is required for advanced configuration features"

NEED_PPA_INSTALL=0
CURRENT_VERSION=""

if command -v mosquitto >/dev/null 2>&1; then
    CURRENT_VERSION=$(mosquitto -h 2>&1 | awk '/mosquitto version/ {print $3; exit}')
    if [[ -n "$CURRENT_VERSION" ]]; then
        if dpkg --compare-versions "$CURRENT_VERSION" "ge" "2.0"; then
            log_info "Detected Mosquitto version ${CURRENT_VERSION} (meets requirement)"
        else
            log_warning "Detected Mosquitto version ${CURRENT_VERSION} (< 2.0); upgrading via mosquitto-dev PPA"
            NEED_PPA_INSTALL=1
        fi
    else
        log_warning "Unable to determine current Mosquitto version; upgrading via mosquitto-dev PPA"
        NEED_PPA_INSTALL=1
    fi
else
    log_info "Mosquitto not detected; installing from mosquitto-dev PPA"
    NEED_PPA_INSTALL=1
fi

if [[ $NEED_PPA_INSTALL -eq 1 ]]; then
    if ! command -v apt-add-repository >/dev/null 2>&1; then
        log_info "Installing software-properties-common to enable PPA management..."
        apt-get update -qq
        apt-get install -y software-properties-common
    fi
    log_info "Adding mosquitto-dev PPA for Mosquitto 2.0+..."
    apt-add-repository -y ppa:mosquitto-dev/mosquitto-ppa
    log_info "Refreshing package lists..."
    apt update
    log_info "Installing Mosquitto broker and clients..."
    apt install -y mosquitto mosquitto-clients
else
    log_info "Skipping Mosquitto PPA installation; required version already present"
fi

INSTALLED_VERSION=$(mosquitto -h 2>&1 | awk '/mosquitto version/ {print $3; exit}')
if [[ -z "$INSTALLED_VERSION" ]]; then
    INSTALLED_VERSION="unknown"
    log_warning "Mosquitto installation verified, but version could not be determined"
else
    log_success "Mosquitto installation verified (version: ${INSTALLED_VERSION})"
fi

# Stop the default mosquitto service if it's running
if systemctl is-active --quiet mosquitto.service; then
    log_info "Stopping default mosquitto service..."
    systemctl stop mosquitto.service
    systemctl disable mosquitto.service
    log_success "Default mosquitto service stopped and disabled"
fi

# Step 2: Create Orpheus root configuration directory (shared by all services)
log_info "Creating Orpheus root configuration directory..."
if [ ! -d "$ORPHEUS_ROOT_CONFIG_DIR" ]; then
    mkdir -p "$ORPHEUS_ROOT_CONFIG_DIR"
    log_success "Created shared root directory: $ORPHEUS_ROOT_CONFIG_DIR"
else
    log_info "Shared root directory already exists: $ORPHEUS_ROOT_CONFIG_DIR"
fi

# Step 2b: Create MQTT-specific configuration subdirectory
log_info "Creating MQTT configuration subdirectory..."
mkdir -p "$ORPHEUS_MQTT_CONFIG_DIR"
log_success "Created MQTT config directory: $ORPHEUS_MQTT_CONFIG_DIR"

# Step 3: Copy Mosquitto configuration
log_info "Installing Mosquitto configuration..."
cp "$MOSQUITTO_CONF_SRC" "$MOSQUITTO_CONF"
chmod 644 "$MOSQUITTO_CONF"
log_success "Configuration installed to: $MOSQUITTO_CONF"

# Step 4: Create Orpheus root data directory (shared by all services)
log_info "Creating Orpheus root data directory..."
if [ ! -d "$ORPHEUS_ROOT_DATA_DIR" ]; then
    mkdir -p "$ORPHEUS_ROOT_DATA_DIR"
    log_success "Created shared root data directory: $ORPHEUS_ROOT_DATA_DIR"
else
    log_info "Shared root data directory already exists: $ORPHEUS_ROOT_DATA_DIR"
fi

# Step 4b: Create MQTT persistence subdirectory
log_info "Creating MQTT persistence subdirectory..."
mkdir -p "$PERSISTENCE_DIR"

# Set ownership to mosquitto user (created by mosquitto package)
if id "mosquitto" &>/dev/null; then
    chown -R mosquitto:mosquitto "$PERSISTENCE_DIR"
    chmod 755 "$PERSISTENCE_DIR"
    log_success "Persistence directory created: $PERSISTENCE_DIR"
else
    log_error "User 'mosquitto' does not exist. Installation may be incomplete."
    exit 1
fi

# Step 5: Install systemd service file
log_info "Installing systemd service..."
cp "$SYSTEMD_SERVICE_SRC" "$SYSTEMD_SERVICE_DEST"
chmod 644 "$SYSTEMD_SERVICE_DEST"
log_success "Service file installed to: $SYSTEMD_SERVICE_DEST"

# Step 6: Reload systemd daemon
log_info "Reloading systemd daemon..."
systemctl daemon-reload
log_success "Systemd daemon reloaded"

# Step 7: Enable service to start on boot
log_info "Enabling orpheus-mqtt service..."
systemctl enable orpheus-mqtt.service
log_success "Service enabled (will start on boot)"

# Step 8: Start the service
log_info "Starting orpheus-mqtt service..."
systemctl start orpheus-mqtt.service
sleep 2  # Give service time to start

# Step 9: Check service status
if systemctl is-active --quiet orpheus-mqtt.service; then
    log_success "Orpheus MQTT broker is running!"
else
    log_error "Failed to start orpheus-mqtt service"
    log_info "Checking service status..."
    systemctl status orpheus-mqtt.service --no-pager
    exit 1
fi

# Step 9b: Run post-install test suite as invoking user when possible
TEST_DISPLAY_COMMAND="cd \"${MQTT_BROKER_DIR}\" && make test"
if command -v make >/dev/null 2>&1; then
    if [[ -n "$SUDO_USER" ]]; then
        if command -v sudo >/dev/null 2>&1; then
            log_info "Running post-install tests as ${SUDO_USER} (make -C \"${MQTT_BROKER_DIR}\" test)..."
            if sudo -H -u "$SUDO_USER" make -C "$MQTT_BROKER_DIR" test; then
                log_success "Post-install tests completed successfully"
                POST_INSTALL_TEST_STATUS="passed"
            else
                log_warning "Post-install tests reported failures; review output above"
                POST_INSTALL_TEST_STATUS="failed"
            fi
        else
            log_warning "Skipping automatic test run ('sudo' command not available). Run: ${TEST_DISPLAY_COMMAND}"
            POST_INSTALL_TEST_STATUS="skipped"
        fi
    else
        log_warning "Skipping automatic test run (no SUDO_USER detected). Run: ${TEST_DISPLAY_COMMAND}"
        POST_INSTALL_TEST_STATUS="skipped"
    fi
else
    log_warning "Skipping automatic test run: 'make' command not available"
    POST_INSTALL_TEST_STATUS="skipped"
fi

# Step 10: Display summary
echo ""
echo "================================================================================"
echo -e "${GREEN}Orpheus MQTT Broker Installation Complete!${NC}"
echo "================================================================================"
echo ""
echo "Service Information:"
echo "  • Service Name:    orpheus-mqtt.service"
echo "  • Status:          $(systemctl is-active orpheus-mqtt.service)"
echo "  • Mosquitto version: ${INSTALLED_VERSION}"
echo "  • Broker Address:  localhost:1883 (127.0.0.1:1883)"
echo ""
echo "Tests:"
case "$POST_INSTALL_TEST_STATUS" in
    passed)
        echo "  • make test:       passed"
        ;;
    failed)
        echo "  • make test:       failed (see logs above)"
        ;;
    skipped)
        echo "  • make test:       skipped (run manually: ${TEST_DISPLAY_COMMAND})"
        ;;
    *)
        echo "  • make test:       not run"
        ;;
esac
echo ""
echo "Directory Structure:"
echo "  • Root config:     $ORPHEUS_ROOT_CONFIG_DIR/ (shared)"
echo "  • MQTT config:     $MOSQUITTO_CONF"
echo "  • Root data:       $ORPHEUS_ROOT_DATA_DIR/ (shared)"
echo "  • MQTT data:       $PERSISTENCE_DIR"
echo ""
echo "Useful Commands:"
echo "  • Check status:    systemctl status orpheus-mqtt.service"
echo "  • View logs:       journalctl -u orpheus-mqtt.service -f"
echo "  • Restart broker:  systemctl restart orpheus-mqtt.service"
echo "  • Stop broker:     systemctl stop orpheus-mqtt.service"
echo ""
echo "Next Steps:"
if [[ "$POST_INSTALL_TEST_STATUS" == "failed" || "$POST_INSTALL_TEST_STATUS" == "skipped" ]]; then
    echo "  1. Test the broker: ${TEST_DISPLAY_COMMAND}"
    echo "  2. Configure agents to connect to: localhost:1883"
    echo "  3. Monitor logs: journalctl -u orpheus-mqtt.service -f"
else
    echo "  1. Configure agents to connect to: localhost:1883"
    echo "  2. Monitor logs: journalctl -u orpheus-mqtt.service -f"
fi
echo ""
echo "Security Notice:"
echo "  • Broker listens on localhost ONLY (not accessible from network)"
echo "  • Anonymous connections allowed (local agents only)"
echo "  • For production with remote access, enable TLS and authentication"
echo ""
echo "================================================================================"
