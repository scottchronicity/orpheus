#!/usr/bin/env bash
# Install orpheus-common as a shared platform library
# This should be run FIRST before installing any services/agents

set -euo pipefail

INSTALL_ROOT="/opt/orpheus/platform/orpheus-common"
CONFIG_DIR="/opt/orpheus/config"
PYTHON_BIN="${PYTHON_BIN:-python3.9}"

log() { printf '[INFO] %s\n' "$1"; }
err() { printf '[ERROR] %s\n' "$1"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "This installer must be run with sudo"
    echo "Usage: sudo ./systemd/install.sh"
    exit 1
  fi
}

main() {
  require_root
  
  local source_root
  source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  
  log "Installing orpheus-common platform library to ${INSTALL_ROOT}"
  
  # Create directories
  mkdir -p "${INSTALL_ROOT}"
  mkdir -p "${CONFIG_DIR}"
  
  # Copy source files
  log "Copying source files..."
  rsync -a --delete \
    --exclude "venv" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude ".pytest_cache" \
    --exclude "*.egg-info" \
    "${source_root}/src" \
    "${source_root}/requirements.txt" \
    "${source_root}/setup.py" \
    "${source_root}/pyproject.toml" \
    "${INSTALL_ROOT}/"
  
  # Deploy configuration files — config lives at repo root: config/
  local repo_root="${source_root}/../.."
  local repo_config="${repo_root}/config"
  log "Deploying configuration files to ${CONFIG_DIR}..."

  if [[ -f "${repo_config}/orpheus.yaml" ]]; then
    if [[ ! -f "${CONFIG_DIR}/orpheus.yaml" ]]; then
      cp "${repo_config}/orpheus.yaml" "${CONFIG_DIR}/orpheus.yaml"
      log "Installed config at ${CONFIG_DIR}/orpheus.yaml"
    else
      log "Existing config found at ${CONFIG_DIR}/orpheus.yaml (left unchanged)"
    fi
  elif [[ -f "${CONFIG_DIR}/orpheus.yaml" ]]; then
    log "Existing config found at ${CONFIG_DIR}/orpheus.yaml (left unchanged)"
  else
    err "No orpheus.yaml found at ${repo_config}/orpheus.yaml"
    log "Copy your config into the repo and re-run:"
    log "  cp /your/orpheus.yaml ${repo_config}/orpheus.yaml"
    log "Then re-run: make deploy-all"
    exit 1
  fi
  
  # Copy sound files to shared location
  log "Installing sound files..."
  SOUNDS_DIR="/opt/orpheus/sounds"
  mkdir -p "${SOUNDS_DIR}"
  if [[ -d "${source_root}/src/orpheus_common/sounds" ]]; then
    rsync -a "${source_root}/src/orpheus_common/sounds/" "${SOUNDS_DIR}/"
    log "✓ Sound files installed to ${SOUNDS_DIR}"
  else
    log "⚠️  No sounds directory found (expected at src/orpheus_common/sounds)"
  fi
  
  log "✓ orpheus-common installed to ${INSTALL_ROOT}"
  log "✓ Configuration installed to ${CONFIG_DIR}"
  log ""
  log "Next steps:"
  log "  1. Edit ${CONFIG_DIR}/orpheus.yaml for your deployment"
  log "  2. Install services/agents (they will use this shared library)"
}

main "$@"
