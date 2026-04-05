#!/bin/bash
################################################################################
# Jetson Orin NX Yahboom Baseline Setup Script
# 
# This script configures the base system for the Orpheus project on the
# NVIDIA Jetson Orin NX 16GB with Yahboom carrier board.
#
# Features:
# - Validates platform hardware
# - Installs required system packages
# - Configures user permissions for hardware access
# - Sets up systemd for service management
# - Idempotent (safe to run multiple times)
#
# Usage: sudo bash baseline-setup.sh
################################################################################

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   log_error "This script must be run as root (use sudo)"
   exit 1
fi

# Get the actual user (not root when using sudo)
ACTUAL_USER="${SUDO_USER:-$USER}"
if [[ "$ACTUAL_USER" == "root" ]]; then
    log_warning "Running as root directly. User permissions will be set for root."
fi

log_info "Starting baseline setup for Jetson Orin NX Yahboom..."
log_info "Running as user: $ACTUAL_USER"

################################################################################
# 1. VALIDATE SYSTEM
################################################################################

log_info "Step 1/7: Validating system information..."

# Check if this is a Jetson device
if [[ ! -f /proc/device-tree/model ]]; then
    log_error "Cannot find /proc/device-tree/model - is this a Jetson device?"
    exit 1
fi

DEVICE_MODEL=$(cat /proc/device-tree/model | tr -d '\0')
log_info "Detected device: $DEVICE_MODEL"

if [[ ! "$DEVICE_MODEL" =~ "Jetson" ]]; then
    log_error "This does not appear to be a Jetson device!"
    log_error "Detected: $DEVICE_MODEL"
    exit 1
fi

# Check for Orin NX specifically (informational only, don't fail)
if [[ "$DEVICE_MODEL" =~ "Orin NX" ]]; then
    log_success "Confirmed: Jetson Orin NX detected"
else
    log_warning "Expected Jetson Orin NX, but found: $DEVICE_MODEL"
    log_warning "Continuing anyway, but some features may not work as expected"
fi

# Check L4T version
if [[ -f /etc/nv_tegra_release ]]; then
    L4T_VERSION=$(cat /etc/nv_tegra_release)
    log_info "L4T Version: $L4T_VERSION"
else
    log_warning "Cannot determine L4T version (/etc/nv_tegra_release not found)"
fi

# Check Ubuntu version
if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    log_info "OS: $NAME $VERSION"
    
    if [[ "$VERSION_ID" != "24.04" ]] && [[ "$VERSION_ID" != "22.04" ]] && [[ "$VERSION_ID" != "20.04" ]]; then
        log_warning "Expected Ubuntu 24.04, 22.04, or 20.04, but found $VERSION_ID"
    fi
else
    log_warning "Cannot determine OS version"
fi

# Check architecture
ARCH=$(uname -m)
if [[ "$ARCH" != "aarch64" ]]; then
    log_error "Expected ARM64 (aarch64) architecture, but found: $ARCH"
    exit 1
fi
log_info "Architecture: $ARCH"

# Check CUDA availability (informational)
if command -v nvcc &> /dev/null; then
    CUDA_VERSION=$(nvcc --version | grep "release" | awk '{print $5}' | cut -d',' -f1)
    log_info "CUDA version: $CUDA_VERSION"
else
    log_warning "CUDA compiler (nvcc) not found - JetPack may not be fully installed"
fi

log_success "System validation complete"

################################################################################
# 2. UPDATE SYSTEM PACKAGES
################################################################################

log_info "Step 2/7: Updating system packages..."

# Create a lock file to prevent concurrent apt operations
LOCK_FILE="/tmp/orpheus-setup.lock"
if [[ -f "$LOCK_FILE" ]]; then
    log_warning "Lock file exists, another setup may be running"
    log_warning "If you're sure no other setup is running, remove: $LOCK_FILE"
    exit 1
fi
touch "$LOCK_FILE"

# Cleanup function to remove lock file
cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

# Update package lists
log_info "Updating package lists..."
apt-get update -y || {
    log_error "Failed to update package lists"
    exit 1
}

# Upgrade existing packages (with -y for non-interactive)
log_info "Upgrading existing packages (this may take a while)..."
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y || {
    log_warning "Some packages failed to upgrade, continuing anyway..."
}

log_success "System packages updated"

################################################################################
# 3. INSTALL COMMON DEPENDENCIES
################################################################################

log_info "Step 3/7: Installing common dependencies..."

PACKAGES=(
    # Build tools
    "build-essential"
    "cmake"
    "pkg-config"
    
    # Version control
    "git"
    "git-lfs"
    
    # Python development
    "python3"
    "python3-pip"
    "python3-venv"
    "python3-dev"
    
    # System utilities
    "curl"
    "wget"
    "htop"
    "iotop"
    "net-tools"
    "ethtool"
    "usbutils"
    "pciutils"
    
    # Audio libraries
    "libasound2-dev"
    "portaudio19-dev"
    "libportaudio2"
    "alsa-utils"
    "pulseaudio"
    "pulseaudio-utils"
    
    # Video/camera libraries
    "v4l-utils"
    "ffmpeg"
    "libavcodec-dev"
    "libavformat-dev"
    "libswscale-dev"
    
    # Network tools
    "mosquitto"
    "mosquitto-clients"
    "nmap"
    "iperf3"
    
    # Bluetooth
    "bluez"
    "bluez-tools"
    "bluetooth"
    
    # System libraries
    "libjpeg-dev"
    "libpng-dev"
    "libtiff-dev"
    "libssl-dev"
    "libffi-dev"
    
    # Misc utilities
    "jq"
    "tree"
    "tmux"
    "screen"
)

log_info "Installing ${#PACKAGES[@]} packages..."

for package in "${PACKAGES[@]}"; do
    if dpkg -l | grep -q "^ii  $package "; then
        log_info "  ✓ $package (already installed)"
    else
        log_info "  → Installing $package..."
        DEBIAN_FRONTEND=noninteractive apt-get install -y "$package" || {
            log_warning "Failed to install $package, continuing..."
        }
    fi
done

# Initialize git-lfs if not already done
if ! git lfs install --skip-repo &> /dev/null; then
    log_info "Initializing git-lfs..."
    git lfs install --skip-repo
fi

log_success "Common dependencies installed"

################################################################################
# 4. SET UP USER PERMISSIONS
################################################################################

log_info "Step 4/7: Configuring user permissions for hardware access..."

# Groups for hardware access
GROUPS=(
    "audio"      # Audio device access
    "video"      # Video device access
    "dialout"    # Serial port access
    "plugdev"    # USB device access
    "i2c"        # I2C bus access
    "gpio"       # GPIO access (Jetson-specific)
    "bluetooth"  # Bluetooth access
)

for group in "${GROUPS[@]}"; do
    # Create group if it doesn't exist
    if ! getent group "$group" &> /dev/null; then
        log_info "Creating group: $group"
        groupadd "$group" || log_warning "Failed to create group $group"
    fi
    
    # Add user to group if not already a member
    if id -nG "$ACTUAL_USER" | grep -qw "$group"; then
        log_info "  ✓ User $ACTUAL_USER already in group $group"
    else
        log_info "  → Adding $ACTUAL_USER to group $group"
        usermod -aG "$group" "$ACTUAL_USER" || {
            log_warning "Failed to add $ACTUAL_USER to group $group"
        }
    fi
done

# Set udev rules for common hardware
UDEV_RULES_FILE="/etc/udev/rules.d/99-orpheus-hardware.rules"
log_info "Creating udev rules: $UDEV_RULES_FILE"

cat > "$UDEV_RULES_FILE" << 'EOF'
# Orpheus Hardware Access Rules
# USB Audio interfaces
SUBSYSTEM=="sound", MODE="0660", GROUP="audio"
SUBSYSTEM=="usb", ATTR{idVendor}=="1397", MODE="0660", GROUP="audio"  # Behringer

# Video devices
SUBSYSTEM=="video4linux", MODE="0660", GROUP="video"

# I2C devices
SUBSYSTEM=="i2c-dev", MODE="0660", GROUP="i2c"

# GPIO devices (Jetson)
SUBSYSTEM=="gpio", MODE="0660", GROUP="gpio"

# Bluetooth devices
KERNEL=="rfkill", SUBSYSTEM=="misc", MODE="0660", GROUP="bluetooth"
EOF

# Reload udev rules
log_info "Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger

log_success "User permissions configured"
log_warning "Note: User $ACTUAL_USER may need to log out and back in for group changes to take effect"

################################################################################
# 5. CONFIGURE MOSQUITTO MQTT BROKER
################################################################################

log_info "Step 5/7: Configuring Mosquitto MQTT broker..."

MOSQUITTO_CONF="/etc/mosquitto/conf.d/orpheus.conf"

if [[ -f "$MOSQUITTO_CONF" ]]; then
    log_info "Mosquitto config already exists: $MOSQUITTO_CONF"
else
    log_info "Creating Mosquitto configuration..."
    cat > "$MOSQUITTO_CONF" << 'EOF'
# Orpheus MQTT Broker Configuration

# Listen on localhost for local services
listener 1883 127.0.0.1

# Allow anonymous access for local development
# WARNING: For production, configure authentication
allow_anonymous true

# Persistence
persistence true
persistence_location /var/lib/mosquitto/

# Logging
log_dest file /var/log/mosquitto/mosquitto.log
log_dest stdout
log_type error
log_type warning
log_type notice
log_type information

# Connection logging
connection_messages true

# Maximum queued messages
max_queued_messages 1000
EOF
fi

# Enable and start mosquitto
log_info "Enabling mosquitto service..."
systemctl enable mosquitto || log_warning "Failed to enable mosquitto"

if systemctl is-active --quiet mosquitto; then
    log_info "Restarting mosquitto service..."
    systemctl restart mosquitto || log_warning "Failed to restart mosquitto"
else
    log_info "Starting mosquitto service..."
    systemctl start mosquitto || log_warning "Failed to start mosquitto"
fi

# Verify mosquitto is running
if systemctl is-active --quiet mosquitto; then
    log_success "Mosquitto MQTT broker is running"
else
    log_warning "Mosquitto may not be running properly - check: systemctl status mosquitto"
fi

################################################################################
# 6. CONFIGURE SYSTEMD FOR SERVICE MANAGEMENT
################################################################################

log_info "Step 6/7: Configuring systemd for service management..."

# Create directory for custom service files
SERVICE_DIR="/etc/systemd/system/orpheus"
if [[ ! -d "$SERVICE_DIR" ]]; then
    log_info "Creating service directory: $SERVICE_DIR"
    mkdir -p "$SERVICE_DIR"
fi

# Set up systemd logging
log_info "Configuring journald for better logging..."
JOURNALD_CONF="/etc/systemd/journald.conf.d/orpheus.conf"
mkdir -p "$(dirname "$JOURNALD_CONF")"

if [[ ! -f "$JOURNALD_CONF" ]]; then
    cat > "$JOURNALD_CONF" << 'EOF'
[Journal]
# Increase journal size for better debugging
SystemMaxUse=500M
RuntimeMaxUse=100M
# Keep logs for 2 weeks
MaxRetentionSec=2week
# Forward to syslog
ForwardToSyslog=no
EOF
    systemctl restart systemd-journald || log_warning "Failed to restart journald"
fi

log_success "Systemd configuration complete"

################################################################################
# 7. PERFORMANCE AND OPTIMIZATION
################################################################################

log_info "Step 7/7: Applying performance optimizations..."

# Set Jetson to max performance mode if nvpmodel is available
if command -v nvpmodel &> /dev/null; then
    log_info "Setting power mode to MAXN (mode 0)..."
    nvpmodel -m 0 || log_warning "Failed to set nvpmodel"
    
    log_info "Enabling jetson_clocks..."
    if command -v jetson_clocks &> /dev/null; then
        jetson_clocks || log_warning "Failed to enable jetson_clocks"
    else
        log_warning "jetson_clocks command not found"
    fi
else
    log_warning "nvpmodel not found - cannot set performance mode"
fi

# Disable unnecessary services to save resources
DISABLE_SERVICES=(
    "bluetooth"  # We'll enable this manually when needed
    "cups"       # Printer service (usually not needed)
    "avahi-daemon"  # mDNS (usually not needed on embedded)
)

for service in "${DISABLE_SERVICES[@]}"; do
    if systemctl is-enabled --quiet "$service" 2>/dev/null; then
        log_info "Disabling unnecessary service: $service"
        systemctl disable "$service" || true
        systemctl stop "$service" || true
    fi
done

log_success "Performance optimizations applied"

################################################################################
# SUMMARY AND NEXT STEPS
################################################################################

echo ""
log_success "=========================================="
log_success "Baseline setup complete!"
log_success "=========================================="
echo ""
log_info "System Information:"
log_info "  Device: $DEVICE_MODEL"
log_info "  Architecture: $ARCH"
log_info "  User: $ACTUAL_USER"
echo ""
log_info "Services Status:"
if systemctl is-active --quiet mosquitto; then
    log_success "  ✓ Mosquitto MQTT broker is running"
else
    log_warning "  ✗ Mosquitto is not running"
fi
echo ""
log_info "Next Steps:"
log_info "  1. Log out and log back in for group permissions to take effect"
log_info "  2. Configure hardware components:"
log_info "     - Audio interface: see hardware/audio-interface/README.md"
log_info "     - Cameras: see hardware/cameras/README.md"
log_info "     - Networking: see hardware/networking/README.md"
log_info "     - Bluetooth audio: see hardware/bluetooth-audio/README.md"
log_info "  3. Set up services: see services/README.md"
log_info "  4. Deploy agents: see agents/README.md"
echo ""
log_info "Useful Commands:"
log_info "  - Monitor system: jtop (install with: sudo pip3 install jetson-stats)"
log_info "  - Check MQTT: mosquitto_sub -h localhost -t '#'"
log_info "  - View logs: journalctl -xe"
log_info "  - Check services: systemctl status"
echo ""

log_success "Setup complete! Happy hacking! 🚀"
