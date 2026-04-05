#!/usr/bin/env bash
# Uninstall Orpheus Video Motion Detection Agent systemd service

set -euo pipefail

SERVICE_NAME="orpheus-agent-video-motion"
INSTALL_ROOT="/opt/orpheus/agents/${SERVICE_NAME}"
SYSTEMD_DIR="/etc/systemd/system"

log() { printf '[INFO] %s\n' "$1"; }
err() { printf '[ERROR] %s\n' "$1"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "This uninstaller must be run with sudo"
    echo "Usage: sudo ./systemd/uninstall-service.sh"
    exit 1
  fi
}

main() {
  require_root
  
  log "Uninstalling ${SERVICE_NAME} service..."

  # Stop and disable service
  systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
  systemctl disable "${SERVICE_NAME}" 2>/dev/null || true

  # Remove service file
  rm -f "${SYSTEMD_DIR}/${SERVICE_NAME}.service"

  # Reload systemd
  systemctl daemon-reload

  log "Service removed. To remove deployed files, run: sudo rm -rf ${INSTALL_ROOT}"
  log "✓ ${SERVICE_NAME} service uninstalled"
}

main "$@"
