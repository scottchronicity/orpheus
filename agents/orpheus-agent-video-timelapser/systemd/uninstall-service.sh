#!/usr/bin/env bash
# Uninstaller for the Orpheus Video Timelapser Agent systemd unit.

set -euo pipefail

SERVICE_NAME="orpheus-agent-video-timelapser"
AGENT_ID="orpheus-agent-video-timelapser"
INSTALL_ROOT="/opt/orpheus/agents/${AGENT_ID}"
SYSTEMD_DIR="/etc/systemd/system"

log() { printf '[INFO] %s\n' "$1"; }
err() { printf '[ERROR] %s\n' "$1"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "This script must be run with sudo"
    echo "Usage: sudo ./systemd/uninstall-service.sh"
    exit 1
  fi
}

main() {
  require_root

  log "Stopping service ${SERVICE_NAME}..."
  systemctl stop "${SERVICE_NAME}" 2>/dev/null || log "Service not running"

  log "Disabling service ${SERVICE_NAME}..."
  systemctl disable "${SERVICE_NAME}" 2>/dev/null || log "Service not enabled"

  log "Removing systemd unit file..."
  rm -f "${SYSTEMD_DIR}/${SERVICE_NAME}.service"

  log "Reloading systemd daemon..."
  systemctl daemon-reload

  log "Removing installation directory..."
  rm -rf "${INSTALL_ROOT}"

  log "Uninstallation complete"
}

main "$@"
