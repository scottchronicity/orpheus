#!/usr/bin/env bash
# Installer for the Orpheus Audio Playback Agent systemd unit.
#
# Deploys the agent into /opt/orpheus/agents/orpheus-agent-audio-playback with
# an isolated Python 3.9 virtual environment and installs the service file.

set -euo pipefail

SERVICE_NAME="orpheus-agent-audio-playback"
AGENT_ID="orpheus-agent-audio-playback"
INSTALL_ROOT="/opt/orpheus/agents/${AGENT_ID}"
SERVICE_FILE="${SERVICE_NAME}.service"
SYSTEMD_DIR="/etc/systemd/system"
PYTHON_BIN="${PYTHON_BIN:-python3.9}"
ORPHEUS_USER="orpheus"
ORPHEUS_GROUP="orpheus"

log() { printf '[INFO] %s\n' "$1"; }
warn() { printf '[WARN] %s\n' "$1"; }
err() { printf '[ERROR] %s\n' "$1"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "This installer must be run with sudo"
    echo "Usage: sudo ./systemd/install-service.sh"
    exit 1
  fi
}

ensure_python() {
  if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    err "Python interpreter '${PYTHON_BIN}' not found. Set PYTHON_BIN=/path/to/python3.9"
    exit 1
  fi
  local version
  version="$(${PYTHON_BIN} -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
  local major minor micro
  IFS='.' read -r major minor micro <<< "${version}"
  if [[ "${major}" -ne 3 || "${minor}" -lt 9 ]]; then
    err "Python 3.9+ required, found ${version}"
    exit 1
  fi
}

create_user() {
  if id -u "${ORPHEUS_USER}" >/dev/null 2>&1; then
    log "User ${ORPHEUS_USER} already present"
  else
    log "Creating system user ${ORPHEUS_USER}"
    useradd --system --no-create-home --shell /usr/sbin/nologin "${ORPHEUS_USER}"
  fi
  usermod -a -G audio "${ORPHEUS_USER}" 2>/dev/null || warn "Unable to add ${ORPHEUS_USER} to audio group"
  usermod -a -G plugdev "${ORPHEUS_USER}" 2>/dev/null || warn "Unable to add ${ORPHEUS_USER} to plugdev group"
}

sync_payload() {
  local source_root
  source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  log "Deploying agent files to ${INSTALL_ROOT}"
  mkdir -p "${INSTALL_ROOT}"
  rsync -a --delete \
    --exclude "venv" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    "${source_root}/src" "${INSTALL_ROOT}/"
  cp "${source_root}/pyproject.toml" "${INSTALL_ROOT}/"
  cp "${source_root}/requirements.txt" "${INSTALL_ROOT}/"
}

setup_venv() {
  log "Creating virtual environment at ${INSTALL_ROOT}/venv"
  rm -rf "${INSTALL_ROOT}/venv"
  "${PYTHON_BIN}" -m venv "${INSTALL_ROOT}/venv"
  "${INSTALL_ROOT}/venv/bin/pip" install --upgrade pip
  
  # Install orpheus-common from central installation
  local orpheus_common_path="/opt/orpheus/platform/orpheus-common"
  if [[ -d "${orpheus_common_path}" ]]; then
    log "Installing orpheus-common from ${orpheus_common_path}"
    "${INSTALL_ROOT}/venv/bin/pip" install "${orpheus_common_path}"
  else
    warn "orpheus-common not found at ${orpheus_common_path}"
    warn "Run: sudo /opt/orpheus/platform/orpheus-common/systemd/install.sh first"
    warn "Attempting to install from requirements.txt (may fail in production)"
  fi
  
  # Install other dependencies (excluding orpheus-common editable install)
  local source_root
  source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  local tmp_req="$(mktemp)"
  grep -vE '^-e[[:space:]]+\.\./\.\./platform/orpheus-common' "${source_root}/requirements.txt" > "${tmp_req}"
  "${INSTALL_ROOT}/venv/bin/pip" install -r "${tmp_req}"
  rm -f "${tmp_req}"
}

install_service() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  log "Installing systemd service file"
  cp "${script_dir}/${SERVICE_FILE}" "${SYSTEMD_DIR}/${SERVICE_FILE}"
  chmod 0644 "${SYSTEMD_DIR}/${SERVICE_FILE}"
  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
}

finalize_permissions() {
  chown -R "${ORPHEUS_USER}:${ORPHEUS_GROUP}" "${INSTALL_ROOT}"
}

main() {
  require_root
  ensure_python
  create_user
  sync_payload
  setup_venv
  finalize_permissions
  install_service
  log "Installation complete. Start the service with: sudo systemctl start ${SERVICE_NAME}"
}

main "$@"
