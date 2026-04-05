#!/bin/bash
set -e

echo "Installing Orpheus Dashboard systemd service..."

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

DEFAULT_ORPHEUS_CONFIG="${COMMON_PATH}/config/orpheus.yaml"

# Create directories
mkdir -p /opt/orpheus/dashboard

# Copy application files (src contains orpheus_dashboard package with static files)
cp -r "${PROJECT_ROOT}/src" "${PROJECT_ROOT}/systemd" "${PROJECT_ROOT}/config" /opt/orpheus/dashboard/
cp "${PROJECT_ROOT}/requirements.txt" /opt/orpheus/dashboard/
cp "${PROJECT_ROOT}/pyproject.toml" /opt/orpheus/dashboard/
cp "${PROJECT_ROOT}/setup.py" /opt/orpheus/dashboard/

# Setup virtual environment
cd /opt/orpheus/dashboard
# Remove existing venv to ensure correct Python version
if [ -d "venv" ]; then
    echo "Removing existing virtual environment..."
    rm -rf venv
fi
${PYTHON_BIN} -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install "${COMMON_PATH}"
venv/bin/pip install -r "${TMP_REQUIREMENTS}"

# Install systemd service
cp systemd/orpheus-dashboard.service /etc/systemd/system/
systemctl daemon-reload

echo "✓ Service installed"
echo "✓ Dashboard will use centralized config at /opt/orpheus/config/orpheus.yaml"
