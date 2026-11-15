#!/usr/bin/env bash
set -e

SERVICE_NAME="orpheus-agent-event-correlator"
SERVICE_FILE="${SERVICE_NAME}.service"
INSTALL_DIR="/opt/orpheus/agents/${SERVICE_NAME}"
SYSTEMD_DIR="/etc/systemd/system"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"

echo "Installing ${SERVICE_NAME} systemd service..."

# Check Python version
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "ERROR: Python interpreter '${PYTHON_BIN}' not found."
    echo "Set PYTHON_BIN to a Python 3.12 or 3.13 interpreter if needed."
    exit 1
fi

if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(not ((3, 12) <= sys.version_info[:2] < (3, 14)))'; then
    echo "ERROR: ${SERVICE_NAME} requires Python 3.12 or 3.13." >&2
    exit 1
fi

# Copy service files to /opt/orpheus
sudo mkdir -p "${INSTALL_DIR}"
sudo cp -r . "${INSTALL_DIR}/"
sudo cp pyproject.toml "${INSTALL_DIR}/"

# Rebuild a pre-existing Python 3.9 environment once; keeping it would leave
# this service running under the runtime its package metadata no longer allows.
if [ -x "${INSTALL_DIR}/venv/bin/python" ] && ! "${INSTALL_DIR}/venv/bin/python" -c 'import sys; raise SystemExit((3, 12) <= sys.version_info[:2] < (3, 14))'; then
    echo "Replacing the existing incompatible Python environment..."
    sudo rm -rf "${INSTALL_DIR}/venv"
fi

# Install dependencies if the compatible venv doesn't exist
if [ ! -x "${INSTALL_DIR}/venv/bin/python" ]; then
    echo "Creating virtual environment with ${PYTHON_BIN}..."
    cd "${INSTALL_DIR}"
    "${PYTHON_BIN}" -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
fi

# Install systemd service
echo "Installing systemd service..."
sudo cp "systemd/${SERVICE_FILE}" "${SYSTEMD_DIR}/"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"

echo "✅ ${SERVICE_NAME} installed successfully"
echo ""
echo "Usage:"
echo "  sudo systemctl start ${SERVICE_NAME}"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
