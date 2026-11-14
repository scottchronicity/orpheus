#!/bin/bash
# Install (or update) orpheus-audio-output. Run as root (make install-service).
#
#  1. Deploy the code and a venv to /opt/orpheus/services/orpheus-audio-output.
#  2. Validate the audio_output configuration (nothing else changes if invalid).
#  3. Prepare the audio server's lifecycle (PulseAudio: lingering for its user,
#     mask that user's stock PulseAudio units, stop a stock instance).
#  4. Retire orpheus-bluetooth-autoconnect and any unit that also connects the
#     same speaker, so exactly one supervisor runs.
#  5. Install, enable and (re)start the unit; report its first health snapshot.
#
# Every host change is recorded in /var/lib/orpheus-audio-output/changes;
# `make rollback` undoes them and restores the retired service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMMON_PATH="$(cd "${PROJECT_ROOT}/../../platform/orpheus-common" && pwd)"
DEPLOY_ROOT=/opt/orpheus/services/orpheus-audio-output
PYTHON_BIN="${PYTHON_BIN:-python3.9}"
HEALTH_FILE=/run/orpheus-audio-output/health.json

# shellcheck source=lifecycle.sh
. "${SCRIPT_DIR}/lifecycle.sh"

if [[ ${EUID} -ne 0 ]]; then
    echo "Run as root: make install-service" >&2
    exit 1
fi

# --- 1. deploy ------------------------------------------------------------------
say "deploying to ${DEPLOY_ROOT}"
mkdir -p "${DEPLOY_ROOT}"
rm -rf "${DEPLOY_ROOT}/src"
cp -r "${PROJECT_ROOT}/src" "${PROJECT_ROOT}/systemd" "${DEPLOY_ROOT}/"
cp "${PROJECT_ROOT}"/{pyproject.toml,requirements.txt,VERSION,README.md} "${DEPLOY_ROOT}/"
TMP_REQUIREMENTS="$(mktemp)"
trap 'rm -f "${TMP_REQUIREMENTS}"' EXIT
grep -vE '^-e[[:space:]]+\.\./\.\./platform/orpheus-common' "${PROJECT_ROOT}/requirements.txt" > "${TMP_REQUIREMENTS}"
cd "${DEPLOY_ROOT}"
rm -rf venv
"${PYTHON_BIN}" -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q "${COMMON_PATH}"
venv/bin/pip install -q -r "${TMP_REQUIREMENTS}"

# --- 2. validate ----------------------------------------------------------------
if ! CHECK_JSON="$(venv/bin/python -m orpheus_audio_output.main check)"; then
    echo "${CHECK_JSON}" >&2
    say "ERROR: invalid audio_output configuration; nothing else was changed"
    exit 1
fi
field() { echo "${CHECK_JSON}" | tail -n 1 | venv/bin/python -c "import json,sys; c=json.load(sys.stdin)['config']; print($1)"; }
ENABLED="$(field "c['enabled']")"
SOURCE="$(field "c['source']")"
SERVER_TYPE="$(field "c['server']['type']")"
OUTPUT_TYPE="$(field "c['output']['type']")"
PA_USER="$(field "(c['server'].get('pulseaudio') or {}).get('user','')")"
BT_ADDRESS="$(field "((c['output'].get('bluetooth') or {}).get('address',''))")"
say "configuration: enabled=${ENABLED} output=${OUTPUT_TYPE} ${BT_ADDRESS} server=${SERVER_TYPE} ${PA_USER} (from ${SOURCE})"

install -m 0644 "${PROJECT_ROOT}/systemd/${NEW_UNIT}" "${UNIT_DIR}/${NEW_UNIT}"
systemctl daemon-reload

if [[ "${ENABLED}" != "True" ]]; then
    systemctl disable --now "${NEW_UNIT}" 2>/dev/null || true
    say "audio_output is disabled: unit installed but not enabled; other services left as they are"
    exit 0
fi

# --- 3. audio server lifecycle --------------------------------------------------
if [[ "${SERVER_TYPE}" == "pulseaudio" ]]; then
    if ! id -u "${PA_USER}" >/dev/null 2>&1; then
        say "ERROR: audio_output.server.pulseaudio.user '${PA_USER}' does not exist"
        exit 1
    fi
    ensure_linger "${PA_USER}"
    mask_stock_pulseaudio "${PA_USER}"
    # A stock PulseAudio already running for this user loads module-udev-detect
    # (capture interface) and would be adopted; stop it so the managed,
    # Bluetooth-only instance owns the socket.
    PA_UID="$(id -u "${PA_USER}")"
    if pgrep -u "${PA_UID}" -x pulseaudio >/dev/null 2>&1; then
        say "stopping the stock PulseAudio running for ${PA_USER}"
        pkill -u "${PA_UID}" -x pulseaudio || true
    fi
fi

# --- 4. one supervisor ----------------------------------------------------------
retire_legacy_autoconnect
disable_competing_units "${BT_ADDRESS}"
systemctl daemon-reload

# --- 5. start -------------------------------------------------------------------
systemctl enable "${NEW_UNIT}"
systemctl restart "${NEW_UNIT}"
say "started ${NEW_UNIT}; waiting for its first health snapshot"
for _ in $(seq 1 60); do
    if [[ -s "${HEALTH_FILE}" ]] && venv/bin/python -c "import json,sys; h=json.load(open(sys.argv[1])); sys.exit(0 if h.get('server',{}).get('state') else 1)" "${HEALTH_FILE}" 2>/dev/null; then
        break
    fi
    sleep 1
done
if [[ -s "${HEALTH_FILE}" ]]; then
    venv/bin/python - "${HEALTH_FILE}" <<'EOF'
import json, sys
h = json.load(open(sys.argv[1]))
print(f"  status:   {h.get('status')}")
print(f"  server:   {h.get('server', {}).get('state')} {h.get('server', {}).get('detail') or ''}")
print(f"  output:   {h.get('output', {}).get('state')} {h.get('output', {}).get('detail') or ''}")
print(f"  routing:  {h.get('routing', {}).get('state')} {h.get('routing', {}).get('sink') or ''}")
print(f"  capture isolation ok: {h.get('capture_isolation', {}).get('ok')}")
EOF
else
    say "no health snapshot yet; check: journalctl -u ${NEW_UNIT} -n 50"
fi
say "installed. Status: make -C services/orpheus-audio-output health   Rollback: make -C services/orpheus-audio-output rollback"
