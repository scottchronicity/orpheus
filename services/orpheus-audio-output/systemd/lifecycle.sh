#!/bin/bash
# Host lifecycle steps shared by install-service.sh and uninstall-service.sh.
#
# Every host change is recorded, one line each, so it can be undone exactly:
#   linger:<user>                         lingering enabled by the installer
#   mask:<user>:<path>                    a /dev/null mask the installer created
#   unit:<name>:<was-enabled>:<was-active> a competing unit stopped/disabled
#   retired:<name>:<was-enabled>:<was-active> the legacy service, moved to backup
#   pulseaudio-stopped:<user>             a stock PulseAudio the installer stopped
# A run writes to $RUN_CHANGES; only a successful install merges it into
# $CHANGES, so a failed run undoes its own changes and nothing older.
#
# Paths are rooted at $SYSROOT (empty on a real host) so tests run in a sandbox.

SYSROOT="${SYSROOT:-}"
UNIT_DIR="${SYSROOT}/etc/systemd/system"
STATE_DIR="${SYSROOT}/var/lib/orpheus-audio-output"
BACKUP_DIR="${STATE_DIR}/legacy"
CHANGES="${STATE_DIR}/changes"
RUN_CHANGES="${RUN_CHANGES:-${CHANGES}}"
DEPLOY_ROOT="${SYSROOT}/opt/orpheus/services/orpheus-audio-output"
HEALTH_FILE="${SYSROOT}/run/orpheus-audio-output/health.json"
LEGACY_UNIT="orpheus-bluetooth-autoconnect.service"
LEGACY_SCRIPT="${SYSROOT}/usr/local/bin/orpheus-bluetooth-connect"
NEW_UNIT="orpheus-audio-output.service"

say() { echo "[audio-output] $*"; }

record() {
    mkdir -p "${STATE_DIR}"
    grep -qxF "$1" "${RUN_CHANGES}" 2>/dev/null || echo "$1" >> "${RUN_CHANGES}"
}

user_home() { getent passwd "$1" | cut -d: -f6; }
user_uid() { id -u "$1"; }

unit_enabled() { if systemctl is-enabled --quiet "$1" 2>/dev/null; then echo yes; else echo no; fi; }
unit_active() { if systemctl is-active --quiet "$1" 2>/dev/null; then echo yes; else echo no; fi; }

# --- the PulseAudio user's own systemd manager -----------------------------------
user_manager_running() {
    systemctl is-active --quiet "user@$(user_uid "$1").service" 2>/dev/null
}

user_systemctl() {
    local user="$1" uid
    shift
    uid="$(user_uid "${user}")"
    runuser -u "${user}" -- env \
        XDG_RUNTIME_DIR="/run/user/${uid}" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${uid}/bus" \
        systemctl --user "$@"
}

wait_for_user_manager() {
    local user="$1" i
    for i in $(seq 1 "${USER_MANAGER_WAIT_SECONDS:-10}"); do
        user_manager_running "${user}" && return 0
        sleep 1
    done
    return 1
}

# --- PulseAudio server prerequisites ------------------------------------------------
# Lingering keeps /run/user/<uid> (where the server's socket lives, and where
# the playback agent connects) from boot to shutdown, independent of logins.
ensure_linger() {
    local user="$1"
    if [[ "$(loginctl show-user "${user}" -p Linger --value 2>/dev/null)" == "yes" ]] \
        || [[ -e "${SYSROOT}/var/lib/systemd/linger/${user}" ]]; then
        say "lingering already enabled for ${user}"
        return 0
    fi
    loginctl enable-linger "${user}"
    record "linger:${user}"
    say "enabled lingering for ${user} (its runtime directory now exists from boot)"
}

# The user's stock PulseAudio units would load module-udev-detect and take the
# capture interface; the manager owns this user's server instead.
mask_stock_pulseaudio() {
    local user="$1" home unit link
    home="${SYSROOT}$(user_home "${user}")"
    mkdir -p "${home}/.config/systemd/user"
    for unit in pulseaudio.socket pulseaudio.service; do
        link="${home}/.config/systemd/user/${unit}"
        if [[ -L "${link}" && "$(readlink "${link}")" == "/dev/null" ]]; then
            continue
        fi
        if [[ -e "${link}" || -L "${link}" ]]; then
            say "ERROR: ${link} exists and is not a mask; refusing to replace it"
            return 1
        fi
        ln -s /dev/null "${link}"
        record "mask:${user}:${link}"
        say "masked the stock ${unit} for ${user}"
    done
    chown -h "$(user_uid "${user}"):$(id -g "${user}")" "${home}/.config/systemd/user" \
        "${home}"/.config/systemd/user/pulseaudio.* 2>/dev/null || true
}

# Masks only take effect once the user's manager reloads. Reload it, stop a
# socket it may still hold, and prove neither unit can start.
reload_and_verify_masks() {
    local user="$1" home unit state
    home="${SYSROOT}$(user_home "${user}")"
    for unit in pulseaudio.socket pulseaudio.service; do
        if [[ "$(readlink "${home}/.config/systemd/user/${unit}" 2>/dev/null)" != "/dev/null" ]]; then
            say "ERROR: ${unit} is not masked for ${user}"
            return 1
        fi
    done
    if ! user_manager_running "${user}"; then
        say "no systemd user manager running for ${user}; masks apply when it starts"
        return 0
    fi
    user_systemctl "${user}" daemon-reload || { say "ERROR: could not reload ${user}'s systemd manager"; return 1; }
    if [[ "$(user_systemctl "${user}" show -p ActiveState --value pulseaudio.socket 2>/dev/null)" != "inactive" ]]; then
        user_systemctl "${user}" stop pulseaudio.socket 2>/dev/null || true
    fi
    for unit in pulseaudio.socket pulseaudio.service; do
        state="$(user_systemctl "${user}" show -p LoadState --value "${unit}" 2>/dev/null)"
        if [[ "${state}" != "masked" ]]; then
            say "ERROR: ${user}'s systemd manager reports ${unit} LoadState=${state:-unknown}, not masked"
            return 1
        fi
    done
    state="$(user_systemctl "${user}" show -p ActiveState --value pulseaudio.socket 2>/dev/null)"
    if [[ "${state}" == "active" || "${state}" == "activating" ]]; then
        say "ERROR: ${user}'s pulseaudio.socket is still ${state}; it could socket-activate a stock PulseAudio"
        return 1
    fi
    say "verified: ${user}'s stock pulseaudio.socket/.service are masked and inactive"
}

# A stock PulseAudio already running for this user loads module-udev-detect
# (capture interface) and would be adopted; stop it so the managed,
# Bluetooth-only instance owns the socket. Not restarted on rollback: it was
# never started by Orpheus and would take the capture interface again.
stop_stock_pulseaudio() {
    local user="$1" uid
    uid="$(user_uid "${user}")"
    if pgrep -u "${uid}" -x pulseaudio >/dev/null 2>&1; then
        say "stopping the stock PulseAudio running for ${user}"
        pkill -u "${uid}" -x pulseaudio || true
        record "pulseaudio-stopped:${user}"
    fi
}

# --- retiring competing supervisors -----------------------------------------------
retire_legacy_autoconnect() {
    local enabled active
    if [[ ! -e "${UNIT_DIR}/${LEGACY_UNIT}" ]]; then
        return 0
    fi
    enabled="$(unit_enabled "${LEGACY_UNIT}")"
    active="$(unit_active "${LEGACY_UNIT}")"
    say "retiring ${LEGACY_UNIT} (was enabled=${enabled} active=${active}; its settings file stays)"
    systemctl stop "${LEGACY_UNIT}" 2>/dev/null || true
    systemctl disable "${LEGACY_UNIT}" 2>/dev/null || true
    mkdir -p "${BACKUP_DIR}"
    mv "${UNIT_DIR}/${LEGACY_UNIT}" "${BACKUP_DIR}/${LEGACY_UNIT}"
    if [[ -e "${LEGACY_SCRIPT}" ]]; then
        mv "${LEGACY_SCRIPT}" "${BACKUP_DIR}/orpheus-bluetooth-connect"
    fi
    record "retired:${LEGACY_UNIT}:${enabled}:${active}"
}

# Hand-made units that also connect the same speaker (e.g. an early
# bluetooth-speaker-connect.service) would race the manager.
disable_competing_units() {
    local address="$1" file name enabled active
    [[ -n "${address}" ]] || return 0
    for file in "${UNIT_DIR}"/*.service; do
        [[ -f "${file}" ]] || continue
        name="$(basename "${file}")"
        [[ "${name}" == "${NEW_UNIT}" || "${name}" == "${LEGACY_UNIT}" ]] && continue
        grep -qiE "bluetoothctl[[:space:]]+connect[[:space:]]+${address}" "${file}" || continue
        enabled="$(unit_enabled "${name}")"
        active="$(unit_active "${name}")"
        [[ "${enabled}" == "no" && "${active}" == "no" ]] && continue
        say "disabling competing unit ${name} (connects ${address}; was enabled=${enabled} active=${active})"
        systemctl stop "${name}" 2>/dev/null || true
        systemctl disable "${name}" 2>/dev/null || true
        record "unit:${name}:${enabled}:${active}"
    done
}

# --- undo ------------------------------------------------------------------------------
restore_unit_state() {
    local name="$1" enabled="$2" active="$3"
    if [[ "${enabled}" == "yes" ]]; then
        systemctl enable "${name}" 2>/dev/null || true
    fi
    if [[ "${active}" == "yes" ]]; then
        systemctl start "${name}" 2>/dev/null || true
    fi
    say "restored ${name} (enabled=${enabled} active=${active})"
}

# undo_changes <file> <restore_legacy 0|1>: newest change first.
undo_changes() {
    local file="$1" restore_legacy="$2" line kept="" rest name enabled active user path
    local -a lines
    [[ -f "${file}" ]] || return 0
    mapfile -t lines < "${file}"
    local i
    for ((i = ${#lines[@]} - 1; i >= 0; i--)); do
        line="${lines[i]}"
        case "${line}" in
            linger:*)
                loginctl disable-linger "${line#linger:}" 2>/dev/null || true
                say "disabled lingering for ${line#linger:}"
                ;;
            mask:*)
                rest="${line#mask:}"
                user="${rest%%:*}"
                path="${rest#*:}"
                rm -f "${path}"
                say "removed mask ${path}"
                if user_manager_running "${user}"; then
                    user_systemctl "${user}" daemon-reload 2>/dev/null || true
                fi
                ;;
            unit:*)
                IFS=: read -r _ name enabled active <<< "${line}"
                restore_unit_state "${name}" "${enabled}" "${active}"
                ;;
            retired:*)
                IFS=: read -r _ name enabled active <<< "${line}"
                if [[ "${restore_legacy}" == "1" && -e "${BACKUP_DIR}/${name}" ]]; then
                    mv "${BACKUP_DIR}/${name}" "${UNIT_DIR}/${name}"
                    if [[ -e "${BACKUP_DIR}/orpheus-bluetooth-connect" ]]; then
                        mv "${BACKUP_DIR}/orpheus-bluetooth-connect" "${LEGACY_SCRIPT}"
                    fi
                    systemctl daemon-reload 2>/dev/null || true
                    restore_unit_state "${name}" "${enabled}" "${active}"
                else
                    # Not restored: keep the backup and the record for a later rollback.
                    kept="${line}"$'\n'"${kept}"
                fi
                ;;
            pulseaudio-stopped:*)
                say "note: a stock PulseAudio for ${line#pulseaudio-stopped:} was stopped at install; it is not restarted (it takes the capture interface)"
                ;;
        esac
    done
    if [[ -n "${kept}" ]]; then
        printf '%s' "${kept}" > "${file}"
    else
        rm -f "${file}"
    fi
}

commit_run_changes() {
    [[ "${RUN_CHANGES}" != "${CHANGES}" && -f "${RUN_CHANGES}" ]] || return 0
    local line
    while IFS= read -r line; do
        grep -qxF "${line}" "${CHANGES}" 2>/dev/null || echo "${line}" >> "${CHANGES}"
    done < "${RUN_CHANGES}"
    rm -f "${RUN_CHANGES}"
}

# --- preflight -----------------------------------------------------------------------
# find_pulse_module <name>: the module file in any installed PulseAudio.
find_pulse_module() {
    local dir
    for dir in "${SYSROOT}"/usr/lib/pulse-*/modules "${SYSROOT}"/usr/lib/*/pulse-*/modules; do
        [[ -f "${dir}/$1.so" ]] && return 0
    done
    return 1
}
