#!/bin/bash
# Host lifecycle steps shared by install-service.sh and uninstall-service.sh.
#
# Every change is recorded in "$STATE_DIR/changes" so uninstall (and rollback)
# undoes exactly what install did and nothing else. Paths are rooted at
# $SYSROOT (empty on a real host) so the tests can run these steps in a sandbox.

SYSROOT="${SYSROOT:-}"
UNIT_DIR="${SYSROOT}/etc/systemd/system"
STATE_DIR="${SYSROOT}/var/lib/orpheus-audio-output"
BACKUP_DIR="${STATE_DIR}/legacy"
CHANGES="${STATE_DIR}/changes"
LEGACY_UNIT="orpheus-bluetooth-autoconnect.service"
LEGACY_SCRIPT="${SYSROOT}/usr/local/bin/orpheus-bluetooth-connect"
NEW_UNIT="orpheus-audio-output.service"

say() { echo "[audio-output] $*"; }

record() {
    mkdir -p "${STATE_DIR}"
    grep -qxF "$1" "${CHANGES}" 2>/dev/null || echo "$1" >> "${CHANGES}"
}

recorded() { grep -qxF "$1" "${CHANGES}" 2>/dev/null; }

user_home() { getent passwd "$1" | cut -d: -f6; }
user_uid() { id -u "$1"; }

# --- PulseAudio server prerequisites ----------------------------------------
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
        if [[ -e "${link}" ]]; then
            say "WARNING: ${link} exists and is not a mask; leaving it alone"
            continue
        fi
        ln -s /dev/null "${link}"
        record "mask:${link}"
        say "masked the stock ${unit} for ${user}"
    done
    chown -h "$(user_uid "${user}"):$(id -g "${user}")" "${home}/.config/systemd/user" \
        "${home}"/.config/systemd/user/pulseaudio.* 2>/dev/null || true
}

# --- retiring competing supervisors ------------------------------------------
retire_legacy_autoconnect() {
    if [[ ! -e "${UNIT_DIR}/${LEGACY_UNIT}" ]]; then
        return 0
    fi
    say "retiring ${LEGACY_UNIT} (its settings file stays as a migration source)"
    systemctl stop "${LEGACY_UNIT}" 2>/dev/null || true
    systemctl disable "${LEGACY_UNIT}" 2>/dev/null || true
    mkdir -p "${BACKUP_DIR}"
    mv "${UNIT_DIR}/${LEGACY_UNIT}" "${BACKUP_DIR}/${LEGACY_UNIT}"
    if [[ -e "${LEGACY_SCRIPT}" ]]; then
        mv "${LEGACY_SCRIPT}" "${BACKUP_DIR}/orpheus-bluetooth-connect"
    fi
    record "retired:${LEGACY_UNIT}"
}

# Hand-made units that also connect the same speaker (e.g. an early
# bluetooth-speaker-connect.service) would race the manager. Disable them.
disable_competing_units() {
    local address="$1" file name
    [[ -n "${address}" ]] || return 0
    for file in "${UNIT_DIR}"/*.service; do
        [[ -f "${file}" ]] || continue
        name="$(basename "${file}")"
        [[ "${name}" == "${NEW_UNIT}" || "${name}" == "${LEGACY_UNIT}" ]] && continue
        if grep -qiE "bluetoothctl[[:space:]]+connect[[:space:]]+${address}" "${file}"; then
            if systemctl is-enabled --quiet "${name}" 2>/dev/null; then
                say "disabling competing unit ${name} (it also connects ${address})"
                systemctl disable "${name}" 2>/dev/null || true
                record "disabled:${name}"
            fi
            systemctl stop "${name}" 2>/dev/null || true
        fi
    done
}

# --- undo ----------------------------------------------------------------------
undo_changes() {
    local restore_legacy="$1" line kept=""
    [[ -f "${CHANGES}" ]] || return 0
    while IFS= read -r line; do
        case "${line}" in
            linger:*)
                loginctl disable-linger "${line#linger:}" 2>/dev/null || true
                say "disabled lingering for ${line#linger:}"
                ;;
            mask:*)
                rm -f "${line#mask:}"
                say "removed mask ${line#mask:}"
                ;;
            disabled:*)
                systemctl enable "${line#disabled:}" 2>/dev/null || true
                say "re-enabled ${line#disabled:}"
                ;;
            retired:*)
                if [[ "${restore_legacy}" == "1" && -e "${BACKUP_DIR}/${LEGACY_UNIT}" ]]; then
                    mv "${BACKUP_DIR}/${LEGACY_UNIT}" "${UNIT_DIR}/${LEGACY_UNIT}"
                    if [[ -e "${BACKUP_DIR}/orpheus-bluetooth-connect" ]]; then
                        mv "${BACKUP_DIR}/orpheus-bluetooth-connect" "${LEGACY_SCRIPT}"
                    fi
                    systemctl daemon-reload 2>/dev/null || true
                    systemctl enable "${LEGACY_UNIT}" 2>/dev/null || true
                    say "restored ${LEGACY_UNIT}"
                else
                    # Not restored: keep the backup and the record for a later rollback.
                    kept="${kept}${line}"$'\n'
                fi
                ;;
        esac
    done < "${CHANGES}"
    if [[ -n "${kept}" ]]; then
        printf '%s' "${kept}" > "${CHANGES}"
    else
        rm -f "${CHANGES}"
    fi
}
