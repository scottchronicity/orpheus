#!/usr/bin/env bash
set -e

SERVICE_NAME="orpheus-agent-event-correlator"
SERVICE_FILE="${SERVICE_NAME}.service"
# Overridable only so the installer can be tested in a sandbox.
INSTALL_DIR="${INSTALL_DIR:-/opt/orpheus/agents/${SERVICE_NAME}}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
# The station's 3.12 is provisioned by scripts/provision-python.sh; prefer it so
# `make install-service` (which runs this under sudo, dropping PYTHON_BIN) works.
ORPHEUS_PYTHON312="${ORPHEUS_PYTHON312:-/opt/orpheus/python/bin/python3.12}"
if [ -z "${PYTHON_BIN:-}" ]; then
    if [ -x "${ORPHEUS_PYTHON312}" ]; then PYTHON_BIN="${ORPHEUS_PYTHON312}"; else PYTHON_BIN=python3.12; fi
fi

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

# Copy only what the service needs. Never `cp -r .`: that also copied any
# working-tree venv (e.g. venv-py312, or a dev `venv` straight over the
# deployed one, before the version check below could see it).
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
sudo mkdir -p "${INSTALL_DIR}"
sudo rsync -a --delete \
    --exclude "__pycache__" --exclude "*.pyc" --exclude "*.egg-info" \
    "${SOURCE_ROOT}/src/" "${INSTALL_DIR}/src/"
sudo rsync -a --delete "${SOURCE_ROOT}/systemd/" "${INSTALL_DIR}/systemd/"
for f in pyproject.toml requirements.txt README.md VERSION; do
    if [ -f "${SOURCE_ROOT}/${f}" ]; then
        sudo cp "${SOURCE_ROOT}/${f}" "${INSTALL_DIR}/${f}"
    fi
done
cd "${INSTALL_DIR}"

# Rebuild a pre-existing Python 3.9 environment once; keeping it would leave
# this service running under the runtime its package metadata no longer allows.
# Also rebuild one that references a home directory (a copied dev venv or an
# editable install of a checkout), which the deployment must never depend on.
if [ -x "${INSTALL_DIR}/venv/bin/python" ] && ! "${INSTALL_DIR}/venv/bin/python" -c 'import sys; raise SystemExit(not ((3, 12) <= sys.version_info[:2] < (3, 14)))'; then
    echo "Replacing the existing incompatible Python environment..."
    sudo rm -rf "${INSTALL_DIR}/venv"
elif [ -d "${INSTALL_DIR}/venv" ] && grep -rlqI -E '/home/|/Users/' \
        "${INSTALL_DIR}/venv/bin" "${INSTALL_DIR}"/venv/lib/python3*/site-packages/*.pth 2>/dev/null; then
    echo "Replacing an environment that references a home directory..."
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
