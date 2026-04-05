#!/bin/bash
#
# Orpheus Bluetooth Auto-Connect Installation Script
#
# This script installs and configures the Bluetooth auto-connect service
# for the Orpheus wildlife monitoring system. It ensures that a Bluetooth
# speaker automatically connects on system boot and reconnects if the
# connection drops.
#
# Usage: sudo BLUETOOTH_SPEAKER_MAC=XX:XX:XX:XX:XX:XX ./install.sh
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

log_info "Starting Orpheus Bluetooth Auto-Connect service installation..."

# Determine the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BLUETOOTH_SERVICE_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration
BLUETOOTH_MAC="${BLUETOOTH_SPEAKER_MAC:-FC:58:FA:02:AF:28}"
AUDIO_USER="${AUDIO_USER:-orpheus}"
ORPHEUS_ROOT_CONFIG_DIR="/etc/orpheus"
ORPHEUS_BLUETOOTH_CONFIG_DIR="${ORPHEUS_ROOT_CONFIG_DIR}/bluetooth-autoconnect"
CONFIG_FILE="${ORPHEUS_BLUETOOTH_CONFIG_DIR}/config.env"
SCRIPT_SRC="${BLUETOOTH_SERVICE_DIR}/scripts/orpheus-bluetooth-connect.sh"
SCRIPT_DEST="/usr/local/bin/orpheus-bluetooth-connect"
SYSTEMD_SERVICE_SRC="${BLUETOOTH_SERVICE_DIR}/systemd/orpheus-bluetooth-autoconnect.service"
SYSTEMD_SERVICE_DEST="/etc/systemd/system/orpheus-bluetooth-autoconnect.service"

# Check if script exists
if [[ ! -f "$SCRIPT_SRC" ]]; then
    log_error "Connection script not found at: $SCRIPT_SRC"
    exit 1
fi

# Check if systemd service file exists
if [[ ! -f "$SYSTEMD_SERVICE_SRC" ]]; then
    log_error "Systemd service file not found at: $SYSTEMD_SERVICE_SRC"
    exit 1
fi

# Step 1: Check Bluetooth dependencies
log_info "Checking Bluetooth dependencies..."
if ! command -v bluetoothctl >/dev/null 2>&1; then
    log_error "bluetoothctl not found. Installing bluez..."
    apt-get update -qq
    apt-get install -y bluez
fi
log_success "Bluetooth tools available"

# Step 2: Create Orpheus root configuration directory (shared by all services)
log_info "Creating Orpheus root configuration directory..."
if [ ! -d "$ORPHEUS_ROOT_CONFIG_DIR" ]; then
    mkdir -p "$ORPHEUS_ROOT_CONFIG_DIR"
    log_success "Created shared root directory: $ORPHEUS_ROOT_CONFIG_DIR"
else
    log_info "Shared root directory already exists: $ORPHEUS_ROOT_CONFIG_DIR"
fi

# Step 3: Create Bluetooth-specific configuration subdirectory
log_info "Creating Bluetooth Auto-Connect configuration subdirectory..."
mkdir -p "$ORPHEUS_BLUETOOTH_CONFIG_DIR"
log_success "Created Bluetooth config directory: $ORPHEUS_BLUETOOTH_CONFIG_DIR"

# Step 4: Write configuration file
log_info "Creating configuration file..."
cat > "$CONFIG_FILE" << EOF
# Orpheus Bluetooth Auto-Connect Configuration
# This file is sourced by the service to configure the Bluetooth device

# MAC address of the Bluetooth speaker to connect to
BLUETOOTH_SPEAKER_MAC=${BLUETOOTH_MAC}

# User account running PulseAudio (used for audio output switching)
AUDIO_USER=${AUDIO_USER:-orpheus}
EOF
chmod 644 "$CONFIG_FILE"
log_success "Configuration file created: $CONFIG_FILE"

# Step 5: Install the connection script
log_info "Installing connection script..."
cp "$SCRIPT_SRC" "$SCRIPT_DEST"
chmod 755 "$SCRIPT_DEST"

# Update the script to source the configuration file
sed -i 's|^BLUETOOTH_MAC=.*|# BLUETOOTH_MAC is loaded from config file|' "$SCRIPT_DEST"
sed -i "/^set -euo pipefail/a\\
\\
# Load configuration\\
CONFIG_FILE=\"${CONFIG_FILE}\"\\
if [[ -f \"\$CONFIG_FILE\" ]]; then\\
    source \"\$CONFIG_FILE\"\\
fi\\
\\
# Configuration (with fallback default)\\
BLUETOOTH_MAC=\"\${BLUETOOTH_SPEAKER_MAC:-FC:58:FA:02:AF:28}\"" "$SCRIPT_DEST"

log_success "Connection script installed to: $SCRIPT_DEST"

# Step 6: Install systemd service file
log_info "Installing systemd service..."
cp "$SYSTEMD_SERVICE_SRC" "$SYSTEMD_SERVICE_DEST"
chmod 644 "$SYSTEMD_SERVICE_DEST"
log_success "Service file installed to: $SYSTEMD_SERVICE_DEST"

# Step 7: Reload systemd daemon
log_info "Reloading systemd daemon..."
systemctl daemon-reload
log_success "Systemd daemon reloaded"

# Step 8: Enable service to start on boot
log_info "Enabling orpheus-bluetooth-autoconnect service..."
systemctl enable orpheus-bluetooth-autoconnect.service
log_success "Service enabled (will start on boot)"

# Step 9: Start the service
log_info "Starting orpheus-bluetooth-autoconnect service..."
systemctl start orpheus-bluetooth-autoconnect.service
sleep 3  # Give service time to start

# Step 10: Check service status
if systemctl is-active --quiet orpheus-bluetooth-autoconnect.service; then
    log_success "Orpheus Bluetooth Auto-Connect service is running!"
else
    log_error "Failed to start orpheus-bluetooth-autoconnect service"
    log_info "Checking service status..."
    systemctl status orpheus-bluetooth-autoconnect.service --no-pager
    exit 1
fi

# Step 11: Run post-install tests
TEST_DISPLAY_COMMAND="cd \"${BLUETOOTH_SERVICE_DIR}\" && make test"
if command -v make >/dev/null 2>&1; then
    if [[ -n "$SUDO_USER" ]]; then
        if command -v sudo >/dev/null 2>&1; then
            log_info "Running post-install tests as ${SUDO_USER}..."
            if sudo -H -u "$SUDO_USER" make -C "$BLUETOOTH_SERVICE_DIR" test; then
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

# Step 12: Display summary
echo ""
echo "================================================================================"
echo -e "${GREEN}Orpheus Bluetooth Auto-Connect Installation Complete!${NC}"
echo "================================================================================"
echo ""
echo "Service Information:"
echo "  • Service Name:    orpheus-bluetooth-autoconnect.service"
echo "  • Status:          $(systemctl is-active orpheus-bluetooth-autoconnect.service)"
echo "  • Target Device:   ${BLUETOOTH_MAC}"
echo "  • Audio User:      ${AUDIO_USER}"
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
echo "Configuration:"
echo "  • Root config:     $ORPHEUS_ROOT_CONFIG_DIR/ (shared)"
echo "  • Bluetooth config: $CONFIG_FILE"
echo "  • Connection script: $SCRIPT_DEST"
echo ""
echo "Useful Commands:"
echo "  • Check status:    systemctl status orpheus-bluetooth-autoconnect.service"
echo "  • View logs:       journalctl -u orpheus-bluetooth-autoconnect.service -f"
echo "  • Restart service: systemctl restart orpheus-bluetooth-autoconnect.service"
echo "  • Stop service:    systemctl stop orpheus-bluetooth-autoconnect.service"
echo "  • Test manually:   bluetoothctl connect ${BLUETOOTH_MAC}"
echo ""
echo "Next Steps:"
if [[ "$POST_INSTALL_TEST_STATUS" == "failed" || "$POST_INSTALL_TEST_STATUS" == "skipped" ]]; then
    echo "  1. Test the service: ${TEST_DISPLAY_COMMAND}"
    echo "  2. Monitor logs: journalctl -u orpheus-bluetooth-autoconnect.service -f"
    echo "  3. Verify Bluetooth connection: bluetoothctl info ${BLUETOOTH_MAC}"
else
    echo "  1. Monitor logs: journalctl -u orpheus-bluetooth-autoconnect.service -f"
    echo "  2. Verify Bluetooth connection: bluetoothctl info ${BLUETOOTH_MAC}"
fi
echo ""
echo "To change the Bluetooth device:"
echo "  1. Edit: $CONFIG_FILE"
echo "  2. Restart: sudo systemctl restart orpheus-bluetooth-autoconnect.service"
echo ""
echo "================================================================================"
