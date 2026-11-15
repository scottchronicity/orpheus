#!/usr/bin/env bash
# Installer for the Orpheus Bird Detection Agent systemd unit.
#
# Deploys the agent into /opt/orpheus/agents/orpheus-agent-bird-detection with
# a fresh Python 3.9 virtual environment and installs the service file.
#
#   PYTHON_BIN     interpreter for the venv (default python3.9; the package
#                  requires >=3.9,<3.10, and plain `python3` is 3.8 on JetPack 5)
#   ONNX_RUNTIME   cpu (default) or cuda: which requirements file to install,
#                  matching the Makefile's ONNX_RUNTIME
#
# `make install-service` runs this under sudo, which resets the environment,
# so pass either variable on the sudo command line instead:
#   sudo PYTHON_BIN=/usr/bin/python3.9 ONNX_RUNTIME=cpu bash systemd/install-service.sh
#
# Only the files the service needs are copied: never a working-tree venv,
# an old venv kept beside the source, caches or dotfiles. A copied dev venv
# is how a deployed venv once came to import code from a home-directory
# checkout. The venv is rebuilt on every install (as for the other agents)
# and the install fails if it references anything outside the deployment.
set -euo pipefail

SERVICE_NAME="orpheus-agent-bird-detection"
SERVICE_FILE="${SERVICE_NAME}.service"
# Overridable only so the installer can be tested in a sandbox.
INSTALL_DIR="${INSTALL_DIR:-/opt/orpheus/agents/${SERVICE_NAME}}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
PLATFORM_DIR="${PLATFORM_DIR:-/opt/orpheus/platform/orpheus-common}"
PYTHON_BIN="${PYTHON_BIN:-python3.9}"
ONNX_RUNTIME="${ONNX_RUNTIME:-cpu}"
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { printf '[INFO] %s\n' "$1"; }
err() { printf '[ERROR] %s\n' "$1" >&2; }

case "${ONNX_RUNTIME}" in
    cpu) REQUIREMENTS="requirements.txt" ;;
    cuda) REQUIREMENTS="requirements-cuda.txt" ;;
    *)
        err "ONNX_RUNTIME must be cpu or cuda; got '${ONNX_RUNTIME}'"
        exit 1
        ;;
esac

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    err "Python interpreter '${PYTHON_BIN}' not found. Set PYTHON_BIN=/path/to/python3.9"
    exit 1
fi
if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 9))'; then
    err "${SERVICE_NAME} requires Python 3.9 (pyproject: >=3.9,<3.10); ${PYTHON_BIN} is $("${PYTHON_BIN}" -c 'import platform; print(platform.python_version())')"
    exit 1
fi
if [[ ! -d "${PLATFORM_DIR}" ]]; then
    err "orpheus-common is not deployed at ${PLATFORM_DIR}; install the platform first"
    exit 1
fi

echo "Installing ${SERVICE_NAME} systemd service..."

log "Deploying agent files to ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
rsync -a --delete \
    --exclude "__pycache__" --exclude "*.pyc" --exclude "*.egg-info" \
    "${SOURCE_ROOT}/src/" "${INSTALL_DIR}/src/"
rsync -a --delete "${SOURCE_ROOT}/systemd/" "${INSTALL_DIR}/systemd/"
for f in pyproject.toml requirements.txt requirements-cuda.txt README.md VERSION; do
    if [[ -f "${SOURCE_ROOT}/${f}" ]]; then
        cp "${SOURCE_ROOT}/${f}" "${INSTALL_DIR}/${f}"
    fi
done

log "Creating a ${PYTHON_BIN} virtual environment (ONNX Runtime: ${ONNX_RUNTIME})"
rm -rf "${INSTALL_DIR}/venv"
"${PYTHON_BIN}" -m venv "${INSTALL_DIR}/venv"
# The requirements file names orpheus-common as ../../platform/orpheus-common,
# which resolves to the deployed platform from INSTALL_DIR.
(
    cd "${INSTALL_DIR}"
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r "${REQUIREMENTS}"
)

# Nothing in the deployed environment may point outside the deployment
# (e.g. an editable install of a home-directory checkout).
stray="$(grep -rlI -E '/home/|/Users/' \
    "${INSTALL_DIR}/venv/bin" \
    "${INSTALL_DIR}"/venv/lib/python3*/site-packages/*.pth \
    "${INSTALL_DIR}"/venv/lib/python3*/site-packages/*.egg-link \
    2>/dev/null || true)"
if [[ -n "${stray}" ]]; then
    err "the new venv references a home directory; refusing to install:"
    printf '  %s\n' ${stray} >&2
    exit 1
fi

echo "Installing systemd service..."
cp "${SOURCE_ROOT}/systemd/${SERVICE_FILE}" "${SYSTEMD_DIR}/"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo "✅ ${SERVICE_NAME} installed successfully"
echo ""
echo "Usage:"
echo "  sudo systemctl start ${SERVICE_NAME}"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  sudo journalctl -u ${SERVICE_NAME} -f"
