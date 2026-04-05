#!/usr/bin/env bash
set -e

SERVICE_NAME="orpheus-agent-event-correlator"
SERVICE_FILE="${SERVICE_NAME}.service"
INSTALL_DIR="/opt/orpheus/agents/${SERVICE_NAME}"
SYSTEMD_DIR="/etc/systemd/system"
PYTHON_BIN="${PYTHON_BIN:-python3.9}"

echo "Installing ${SERVICE_NAME} systemd service..."

# Check Python version
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "ERROR: Python interpreter '${PYTHON_BIN}' not found."
    echo "Set PYTHON_BIN=/path/to/python3.9 if needed."
    exit 1
fi

# Copy service files to /opt/orpheus
sudo mkdir -p "${INSTALL_DIR}"
sudo cp -r . "${INSTALL_DIR}/"
sudo cp pyproject.toml "${INSTALL_DIR}/"

# Install dependencies if venv doesn't exist
if [ ! -d "${INSTALL_DIR}/venv" ]; then
    echo "Creating virtual environment with ${PYTHON_BIN}..."
    cd "${INSTALL_DIR}"
    ${PYTHON_BIN} -m venv venv
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
