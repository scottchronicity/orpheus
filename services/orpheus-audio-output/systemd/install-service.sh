#!/bin/bash
# Install (or update) orpheus-audio-output. Run as root (make install-service).
#
# Preflight (changes nothing on the host):
#   build the new code and venv in a staging directory beside the deployment
#   (its scripts rewritten for the final path, verified after the rename),
#   validate the audio_output configuration with it, and check the audio user,
#   tools and PulseAudio modules exist.
# Transaction (any failure restores the previous installation):
#   swap the staged deployment in, install the unit, prepare the PulseAudio
#   user (masks verified through its systemd manager, lingering, stop a stock
#   instance), retire orpheus-bluetooth-autoconnect and competing units
#   (recording whether each was enabled and running), point the playback
#   agent at the managed server (drop-in), start, and require a
#   ready server with capture isolation intact in the first health snapshot.
# On failure: the new unit is stopped, the previous deployment and unit file
# come back, this run's host changes are undone, and every service returns to
# the enabled/running state it had before.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMMON_PATH="${COMMON_PATH:-$(cd "${PROJECT_ROOT}/../../platform/orpheus-common" && pwd)}"
PYTHON_BIN="${PYTHON_BIN:-python3.9}"
HEALTH_WAIT_SECONDS="${HEALTH_WAIT_SECONDS:-60}"

# shellcheck source=lifecycle.sh
. "${SCRIPT_DIR}/lifecycle.sh"

if [[ "${REQUIRE_ROOT:-1}" == "1" && ${EUID} -ne 0 ]]; then
    echo "Run as root: make install-service" >&2
    exit 1
fi

STAGE=""
cleanup_stage() { [[ -n "${STAGE}" && -d "${STAGE}" ]] && rm -rf "${STAGE}"; return 0; }
trap cleanup_stage EXIT

fail_preflight() {
    say "ERROR: $*"
    say "preflight failed: nothing on this host was changed"
    exit 1
}

# --- preflight ----------------------------------------------------------------------
mkdir -p "$(dirname "${DEPLOY_ROOT}")"
STAGE="$(mktemp -d "${DEPLOY_ROOT}.stage.XXXXXX")"
say "building the new deployment in ${STAGE}"
cp -r "${PROJECT_ROOT}/src" "${PROJECT_ROOT}/systemd" "${STAGE}/"
cp "${PROJECT_ROOT}"/{pyproject.toml,requirements.txt,VERSION,README.md} "${STAGE}/"
"${PYTHON_BIN}" -m venv "${STAGE}/venv" || fail_preflight "could not create a ${PYTHON_BIN} venv"
"${STAGE}/venv/bin/pip" install -q --upgrade pip || fail_preflight "pip upgrade failed"
# Non-editable installs only: the venv is renamed into place after preflight.
"${STAGE}/venv/bin/pip" install -q "${COMMON_PATH}" || fail_preflight "installing orpheus-common failed"
"${STAGE}/venv/bin/pip" install -q "PyYAML>=6.0.2" "${STAGE}" || fail_preflight "installing orpheus-audio-output failed"
# Point generated scripts (pip, entry points, activate) at the final path;
# from here on only venv/bin/python (a symlink) runs until the swap.
relocate_venv "${STAGE}/venv" "${STAGE}" "${DEPLOY_ROOT}"
STAGE_PATH="${STAGE}"

if ! CHECK_JSON="$("${STAGE}/venv/bin/python" -m orpheus_audio_output.main check)"; then
    echo "${CHECK_JSON}" >&2
    fail_preflight "invalid audio_output configuration"
fi
field() { echo "${CHECK_JSON}" | tail -n 1 | "${STAGE}/venv/bin/python" -c "import json,sys; c=json.load(sys.stdin)['config']; print($1)"; }
ENABLED="$(field "c['enabled']")"
SOURCE="$(field "c['source']")"
SERVER_TYPE="$(field "c['server']['type']")"
OUTPUT_TYPE="$(field "c['output']['type']")"
PA_USER="$(field "(c['server'].get('pulseaudio') or {}).get('user','')")"
BT_ADDRESS="$(field "((c['output'].get('bluetooth') or {}).get('address',''))")"
say "configuration: enabled=${ENABLED} output=${OUTPUT_TYPE} ${BT_ADDRESS} server=${SERVER_TYPE} ${PA_USER} (from ${SOURCE})"

if [[ "${ENABLED}" == "True" ]]; then
    for tool in systemctl loginctl runuser pgrep; do
        command -v "${tool}" >/dev/null 2>&1 || fail_preflight "required tool '${tool}' not found"
    done
    if [[ "${OUTPUT_TYPE}" == "bluetooth" ]]; then
        command -v bluetoothctl >/dev/null 2>&1 || fail_preflight "bluetoothctl not found (install bluez)"
    fi
    if [[ "${SERVER_TYPE}" == "pulseaudio" ]]; then
        id -u "${PA_USER}" >/dev/null 2>&1 || fail_preflight "audio_output.server.pulseaudio.user '${PA_USER}' does not exist"
        for tool in pulseaudio pactl; do
            command -v "${tool}" >/dev/null 2>&1 || fail_preflight "'${tool}' not found (install pulseaudio pulseaudio-utils)"
        done
        modules=(module-native-protocol-unix)
        [[ "${OUTPUT_TYPE}" == "bluetooth" ]] && modules+=(module-bluetooth-policy module-bluetooth-discover)
        for module in "${modules[@]}"; do
            find_pulse_module "${module}" || fail_preflight "PulseAudio module ${module} not found (install pulseaudio-module-bluetooth)"
        done
        if PLAYBACK_USER="$(playback_unit_user)" && [[ "${PLAYBACK_USER}" != "${PA_USER}" ]]; then
            fail_preflight "the playback agent runs as '${PLAYBACK_USER:-root}' but audio_output.server.pulseaudio.user is '${PA_USER}'; its sounds could not reach that server"
        fi
        link_dir="${SYSROOT}$(user_home "${PA_USER}")/.config/systemd/user"
        for unit in pulseaudio.socket pulseaudio.service; do
            if [[ -e "${link_dir}/${unit}" && "$(readlink "${link_dir}/${unit}")" != "/dev/null" ]]; then
                fail_preflight "${link_dir}/${unit} is a real unit file; remove it or mask it yourself"
            fi
        done
    fi
fi
say "preflight passed"

# --- transaction ----------------------------------------------------------------------
PREV_ENABLED="$(unit_enabled "${NEW_UNIT}")"
PREV_ACTIVE="$(unit_active "${NEW_UNIT}")"
PREV_DEPLOY="${DEPLOY_ROOT}.previous"
PREV_UNIT_FILE="${STATE_DIR}/previous-${NEW_UNIT}"
mkdir -p "${STATE_DIR}"
RUN_CHANGES="${STATE_DIR}/changes.run"
rm -f "${RUN_CHANGES}" "${PREV_UNIT_FILE}"
rm -rf "${PREV_DEPLOY}"

restore_previous() {
    trap - ERR
    set +e
    say "install failed: restoring the previous installation"
    systemctl stop "${NEW_UNIT}" 2>/dev/null
    if [[ -f "${PREV_UNIT_FILE}" ]]; then
        mv "${PREV_UNIT_FILE}" "${UNIT_DIR}/${NEW_UNIT}"
    else
        rm -f "${UNIT_DIR}/${NEW_UNIT}"
    fi
    if [[ -d "${PREV_DEPLOY}" ]]; then
        rm -rf "${DEPLOY_ROOT}"
        mv "${PREV_DEPLOY}" "${DEPLOY_ROOT}"
    elif [[ "${SWAPPED:-0}" == "1" ]]; then
        rm -rf "${DEPLOY_ROOT}"
    fi
    systemctl daemon-reload 2>/dev/null
    undo_changes "${RUN_CHANGES}" 1
    if [[ "${PREV_ENABLED}" == "yes" ]]; then
        systemctl enable "${NEW_UNIT}" 2>/dev/null
    else
        systemctl disable "${NEW_UNIT}" 2>/dev/null
    fi
    [[ "${PREV_ACTIVE}" == "yes" ]] && systemctl start "${NEW_UNIT}" 2>/dev/null
    say "previous installation restored (${NEW_UNIT} enabled=${PREV_ENABLED} active=${PREV_ACTIVE})"
    exit 1
}
trap 'restore_previous' ERR

fail() { say "ERROR: $*"; restore_previous; }

SWAPPED=0
if [[ -d "${DEPLOY_ROOT}" ]]; then
    mv "${DEPLOY_ROOT}" "${PREV_DEPLOY}"
fi
mv "${STAGE}" "${DEPLOY_ROOT}"
STAGE=""
SWAPPED=1
verify_venv "${DEPLOY_ROOT}/venv" "${STAGE_PATH}" || fail "the deployed venv has broken scripts"
"${DEPLOY_ROOT}/venv/bin/pip" --version >/dev/null 2>&1 || fail "pip does not run from ${DEPLOY_ROOT}/venv"
if [[ -f "${UNIT_DIR}/${NEW_UNIT}" ]]; then
    cp -p "${UNIT_DIR}/${NEW_UNIT}" "${PREV_UNIT_FILE}"
fi
install -m 0644 "${PROJECT_ROOT}/systemd/${NEW_UNIT}" "${UNIT_DIR}/${NEW_UNIT}"
systemctl daemon-reload

if [[ "${ENABLED}" != "True" ]]; then
    systemctl disable --now "${NEW_UNIT}" 2>/dev/null || true
    commit_run_changes
    rm -rf "${PREV_DEPLOY}" "${PREV_UNIT_FILE}"
    trap - ERR
    say "audio_output is disabled: unit installed but not enabled; other services left as they are"
    exit 0
fi

if [[ "${SERVER_TYPE}" == "pulseaudio" ]]; then
    mask_stock_pulseaudio "${PA_USER}" || fail "could not mask ${PA_USER}'s stock PulseAudio units"
    ensure_linger "${PA_USER}"
    wait_for_user_manager "${PA_USER}" || fail "the systemd user manager for ${PA_USER} did not start after enabling lingering; the masks cannot be verified"
    reload_and_verify_masks "${PA_USER}" || fail "stock PulseAudio could still be socket-activated for ${PA_USER}"
    stop_stock_pulseaudio "${PA_USER}"
fi

retire_legacy_autoconnect
disable_competing_units "${BT_ADDRESS}"
systemctl daemon-reload
if [[ "${SERVER_TYPE}" == "pulseaudio" ]]; then
    route_playback_to_server "${PA_USER}"
fi

systemctl enable "${NEW_UNIT}"
rm -f "${HEALTH_FILE}"
systemctl restart "${NEW_UNIT}"
say "started ${NEW_UNIT}; waiting up to ${HEALTH_WAIT_SECONDS}s for a ready server"

health_verdict() {
    "${DEPLOY_ROOT}/venv/bin/python" - "${HEALTH_FILE}" <<'EOF'
import json, sys
try:
    h = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    print("pending"); sys.exit()
server = h.get("server", {}).get("state")
iso = h.get("capture_isolation", {}).get("ok")
if iso is False:
    print("fail:capture isolation not ok: %s" % h["capture_isolation"]); sys.exit()
if server == "ready":
    print("ok"); sys.exit()
if server in ("failed", "isolation_violation") and h.get("server", {}).get("consecutive_failures", 0) >= 2:
    print("fail:server %s: %s" % (server, h["server"].get("detail"))); sys.exit()
print("pending")
EOF
}

verdict=pending
for _ in $(seq 1 "${HEALTH_WAIT_SECONDS}"); do
    if [[ "$(unit_active "${NEW_UNIT}")" != "yes" ]]; then
        verdict="fail:${NEW_UNIT} is not running"
        sleep 1
        [[ "$(unit_active "${NEW_UNIT}")" != "yes" ]] && break
    fi
    verdict="$(health_verdict)"
    [[ "${verdict}" != pending ]] && break
    sleep 1
done
case "${verdict}" in
    ok) ;;
    pending) fail "no ready audio server within ${HEALTH_WAIT_SECONDS}s (journalctl -u ${NEW_UNIT})" ;;
    *) fail "${verdict#fail:}" ;;
esac

trap - ERR
commit_run_changes
rm -rf "${PREV_DEPLOY}" "${PREV_UNIT_FILE}"
"${DEPLOY_ROOT}/venv/bin/python" - "${HEALTH_FILE}" <<'EOF'
import json, sys
h = json.load(open(sys.argv[1]))
print(f"  status:   {h.get('status')}")
print(f"  server:   {h.get('server', {}).get('state')} {h.get('server', {}).get('detail') or ''}")
print(f"  output:   {h.get('output', {}).get('state')} {h.get('output', {}).get('detail') or ''}")
print(f"  routing:  {h.get('routing', {}).get('state')} {h.get('routing', {}).get('sink') or ''}")
print(f"  capture isolation ok: {h.get('capture_isolation', {}).get('ok')}")
EOF
say "installed. Status: make -C services/orpheus-audio-output health   Rollback: make -C services/orpheus-audio-output rollback"
