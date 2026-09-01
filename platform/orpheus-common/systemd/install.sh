#!/usr/bin/env bash
# Install orpheus-common as a shared platform library
# This should be run FIRST before installing any services/agents

set -euo pipefail

INSTALL_ROOT="/opt/orpheus/platform/orpheus-common"
CONFIG_DIR="/opt/orpheus/config"
PYTHON_BIN="${PYTHON_BIN:-python3.9}"
# The interpreter orpheus-storage-sweep.service names in its ExecStart. The
# unit and this variable have to stay equal; a test asserts they do.
VENV_DIR="${INSTALL_ROOT}/venv"

log() { printf '[INFO] %s\n' "$1"; }
err() { printf '[ERROR] %s\n' "$1"; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "This installer must be run with sudo"
    echo "Usage: sudo ./systemd/install.sh"
    exit 1
  fi
}

# The file to seed ${CONFIG_DIR}/orpheus.yaml from, printed on stdout (empty
# when there is nothing to seed from).
#
# A fresh clone ships only orpheus.example.yaml, and this script is step 1 of
# the documented Jetson install — so requiring config/orpheus.yaml aborted the
# very first command, and step 2 then told the operator to edit a file that was
# never created. The example IS the shipped default config; seed from it and
# say so. A real config/orpheus.yaml still wins where one exists.
resolve_repo_config() {
  local repo_config="$1"
  if [[ -f "${repo_config}/orpheus.yaml" ]]; then
    printf '%s\n' "${repo_config}/orpheus.yaml"
  elif [[ -f "${repo_config}/orpheus.example.yaml" ]]; then
    printf '%s\n' "${repo_config}/orpheus.example.yaml"
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
    "${source_root}/VERSION" \
    "${source_root}/README.md" \
    "${INSTALL_ROOT}/"
  
  # Deploy configuration files — config lives at repo root: config/
  local repo_root="${source_root}/../.."
  local repo_config="${repo_root}/config"
  log "Deploying configuration files to ${CONFIG_DIR}..."

  local seed_config
  seed_config="$(resolve_repo_config "${repo_config}")"

  if [[ -f "${CONFIG_DIR}/orpheus.yaml" ]]; then
    log "Existing config found at ${CONFIG_DIR}/orpheus.yaml (left unchanged)"
  elif [[ -n "${seed_config}" ]]; then
    cp "${seed_config}" "${CONFIG_DIR}/orpheus.yaml"
    log "Installed config at ${CONFIG_DIR}/orpheus.yaml (from $(basename "${seed_config}"))"
    if [[ "${seed_config}" == *"orpheus.example.yaml" ]]; then
      log "That is the shipped example — edit ${CONFIG_DIR}/orpheus.yaml for this site"
    fi
  else
    err "No orpheus.yaml or orpheus.example.yaml found in ${repo_config}"
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
  
  # Both in condition position so a failure inside either is reported here
  # rather than aborting the script with no explanation.
  if ! build_venv || ! install_storage_sweep "${source_root}"; then
    err "The storage retention sweep was NOT installed, and nothing else on"
    err "this station deletes anything — the recording agents no longer trim"
    err "their own directories."
    err "Fix the problem above and re-run: sudo ./systemd/install.sh"
    exit 1
  fi

  log "✓ orpheus-common installed to ${INSTALL_ROOT}"
  log "✓ Configuration installed to ${CONFIG_DIR}"
  log ""
  log "Next steps:"
  log "  1. Edit ${CONFIG_DIR}/orpheus.yaml for your deployment"
  log "  2. Install services/agents (they will use this shared library)"
}

# Build the venv the storage sweep runs from.
#
# orpheus-common used to be the one component deployed to /opt without an
# interpreter. That was fine while nothing ran it directly — every agent built
# its own venv and installed the platform into that. The sweep changed it: it
# is a one-shot the platform itself owns, and its unit named a python no
# installer had ever created. Enabling the timer would have fired a job every
# 15 minutes that died on a missing interpreter, and since the recording agents
# no longer trim their own directories, nothing would have been deleting.
#
# It also gives 'make show-deployed' and 'make verify-deploy' the version
# metadata they have always tried to read from this path and never found.
#
# Explicit '|| return 1' on each step rather than relying on set -e: bash
# suppresses errexit inside a function called in an if-condition, which is
# exactly how main() calls this one.
build_venv() {
  if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
      err "Python interpreter '${PYTHON_BIN}' not found — cannot build ${VENV_DIR}"
      err "Set PYTHON_BIN=/path/to/python3.9 and re-run."
      return 1
    fi
    log "Creating the platform venv at ${VENV_DIR} (${PYTHON_BIN})..."
    "${PYTHON_BIN}" -m venv "${VENV_DIR}" || return 1
  fi

  # Reinstall on every run, not only when the venv is created: the rsync above
  # has just replaced the source, and a venv left alone keeps reporting the
  # version it was built with — the staleness verify-deploy looks for.
  #
  # The project rather than requirements.txt, because requirements.txt carries
  # the dev tools too and a station has no use for pytest and ruff.
  log "Installing orpheus-common into ${VENV_DIR}..."
  "${VENV_DIR}/bin/python" -m pip install --upgrade pip -q || return 1
  "${VENV_DIR}/bin/python" -m pip install --no-cache-dir "${INSTALL_ROOT}" -q || return 1

  # The unit runs as orpheus, not as root.
  chown -R orpheus:orpheus "${VENV_DIR}" 2>/dev/null || true

  log "✓ Platform venv ready at ${VENV_DIR}"
}

# Install the retention sweep's one-shot unit and its timer.
#
# It ships from orpheus-common rather than from an agent because it is not an
# agent: it owns every deletion under the data root, across every category,
# and belongs to none of them. Enabling the TIMER is what schedules it —
# enabling the service would run one sweep at boot and never again.
#
# The first sweep after this runs reports what it would delete and deletes
# nothing (storage.retention.first_run_grace_hours), so installing it does not
# remove a recording before anyone has seen the numbers.
install_storage_sweep() {
  local source_root="$1"
  local systemd_dir="/etc/systemd/system"

  if ! command -v systemctl >/dev/null 2>&1; then
    log "⚠️  systemctl not found — skipped the storage sweep timer (not a systemd host)"
    log "   Run it by hand instead: orpheus-storage-sweep"
    return 0
  fi

  # Run the unit's own ExecStart before enabling a timer that will run it
  # unattended every 15 minutes. An installer that enables a job it never tried
  # is how the missing interpreter got this far. Read the binary out of the unit
  # rather than naming it again here, so this cannot smoke-test one thing and
  # enable another.
  local exec_start
  exec_start=$(sed -n 's/^ExecStart=//p' "${source_root}/systemd/orpheus-storage-sweep.service" | head -n 1)
  if ! ${exec_start} --help >/dev/null 2>&1; then
    err "${exec_start} cannot run — not enabling the sweep's timer."
    return 1
  fi

  log "Installing the storage retention sweep..."
  cp "${source_root}/systemd/orpheus-storage-sweep.service" "${systemd_dir}/"
  cp "${source_root}/systemd/orpheus-storage-sweep.timer" "${systemd_dir}/"
  systemctl daemon-reload
  systemctl enable --now orpheus-storage-sweep.timer

  log "✓ orpheus-storage-sweep.timer enabled (every 15 minutes)"
  log "  Review what it would remove:  make storage-report"
  log "  Stop all deletion:            sudo systemctl disable --now orpheus-storage-sweep.timer"
}

# Sourceable: tests exercise resolve_repo_config without running the install.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
