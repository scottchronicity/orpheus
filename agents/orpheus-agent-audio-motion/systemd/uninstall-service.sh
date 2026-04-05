#!/usr/bin/env bash
# Uninstaller for the Orpheus Audio Motion Detector systemd unit.

set -euo pipefail

SERVICE_NAME="orpheus-agent-audio-motion"
INSTALL_ROOT="/opt/orpheus/agents/orpheus-agent-audio-motion"
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
  
  log "Stopping and disabling ${SERVICE_NAME} service"
  systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
  systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
  
  log "Removing systemd service file"
  rm -f "${SYSTEMD_DIR}/${SERVICE_NAME}.service"
  systemctl daemon-reload
  
  log "Removing installation directory"
  rm -rf "${INSTALL_ROOT}"
  
  log "Uninstallation complete"
}

main "$@"
