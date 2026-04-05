#!/bin/bash
set -e

echo "Installing Orpheus GPS Service systemd service..."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMMON_RELATIVE="../../platform/orpheus-common"
COMMON_PATH="${PROJECT_ROOT}/${COMMON_RELATIVE}"
PYTHON_BIN="${PYTHON_BIN:-python3.9}"

if [ ! -d "${COMMON_PATH}" ]; then
    echo "ERROR: Could not locate orpheus-common at ${COMMON_PATH}" >&2
    exit 1
fi

COMMON_PATH="$(cd "${COMMON_PATH}" && pwd)"

TMP_REQUIREMENTS="$(mktemp)"
trap 'rm -f "${TMP_REQUIREMENTS}"' EXIT

# Strip editable install for deployment
grep -vE '^-e[[:space:]]+\.\./\.\./platform/orpheus-common([[:space:]]+.*)?$' "${PROJECT_ROOT}/requirements.txt" > "${TMP_REQUIREMENTS}"

# Create directories
mkdir -p /opt/orpheus/services/orpheus-gps

# Copy application files
cp -r "${PROJECT_ROOT}/src" "${PROJECT_ROOT}/systemd" /opt/orpheus/services/orpheus-gps/
cp "${PROJECT_ROOT}/requirements.txt" /opt/orpheus/services/orpheus-gps/
cp "${PROJECT_ROOT}/pyproject.toml" /opt/orpheus/services/orpheus-gps/

# Setup virtual environment
cd /opt/orpheus/services/orpheus-gps
# Remove existing venv to ensure correct Python version
if [ -d "venv" ]; then
    echo "Removing existing virtual environment..."
    rm -rf venv
fi
${PYTHON_BIN} -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install "${COMMON_PATH}"
venv/bin/pip install -r "${TMP_REQUIREMENTS}"

# Create orpheus user if it doesn't exist
if ! id -u orpheus >/dev/null 2>&1; then
    echo "Creating orpheus user..."
    useradd --system --no-create-home --shell /usr/sbin/nologin orpheus
fi

# Add orpheus user to dialout group for serial port access
usermod -a -G dialout orpheus 2>/dev/null || echo "Warning: Could not add orpheus to dialout group"

# Set ownership
chown -R orpheus:orpheus /opt/orpheus/services/orpheus-gps

# Install systemd service
cp systemd/orpheus-gps.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable orpheus-gps

echo "✓ Service installed"
echo "✓ GPS service will use centralized config at /opt/orpheus/config/orpheus.yaml"
echo ""
echo "Configuration:"
echo "  Set ORPHEUS_GPS_DEVICE in /etc/environment or .env (default: /dev/ttyACM0)"
echo "  Set ORPHEUS_STATIC_LAT and ORPHEUS_STATIC_LON for fallback coordinates"
echo ""
echo "Start the service with: sudo systemctl start orpheus-gps"
