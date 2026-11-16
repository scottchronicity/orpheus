#!/bin/bash
# Install, check or remove the Orpheus kiosk on a Jetson's own monitor.
#
#   sudo deploy/kiosk/jetson/install.sh              install or update, enable at boot, (re)start
#   sudo deploy/kiosk/jetson/install.sh --no-start   install or update and enable; leave it stopped
#   sudo deploy/kiosk/jetson/install.sh --check      compare this host with the checkout; changes nothing
#   sudo deploy/kiosk/jetson/install.sh --uninstall  stop it and remove what the install added
#
# Safe to run again. Everything the kiosk needs is set up here, not by hand:
# the Chromium snap (GPU off), the unprivileged orpheus-kiosk user in the video
# group, a PulseAudio that can never start for that user (capture isolation),
# memory and CPU caps on that user's slice, the unit and the weekly update
# timer, and an attached keyboard that cannot reboot the station with
# Ctrl+Alt+Del. Touches no wildlife service. See docs/operator-manual/kiosk.md.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${HERE}/../../.." && pwd)"
KUSER="${ORPHEUS_KIOSK_USER:-orpheus-kiosk}"
LIB="${ORPHEUS_KIOSK_LIB:-/usr/local/lib/orpheus-kiosk}"
UNITDIR="${ORPHEUS_KIOSK_UNITDIR:-/etc/systemd/system}"
CONFD="${ORPHEUS_KIOSK_CONFD:-/etc/systemd/system.conf.d}"
# The snaps the kiosk uses: one list, owned by the weekly update job.
# shellcheck source=orpheus-kiosk-update.sh
source "${HERE}/orpheus-kiosk-update.sh"
SNAPS=("${snaps[@]}")
MEMORY_LIMIT=800M
CPU_SHARES=205

# source|destination|mode
FILES=(
    "${REPO}/deploy/kiosk/linux/orpheus-kiosk-browser.sh|${LIB}/orpheus-kiosk-browser.sh|0755"
    "${HERE}/orpheus-kiosk-session.sh|${LIB}/orpheus-kiosk-session.sh|0755"
    "${HERE}/orpheus-kiosk-update.sh|${LIB}/orpheus-kiosk-update.sh|0755"
    "${HERE}/orpheus-kiosk.service|${UNITDIR}/orpheus-kiosk.service|0644"
    "${HERE}/orpheus-kiosk-update.service|${UNITDIR}/orpheus-kiosk-update.service|0644"
    "${HERE}/orpheus-kiosk-update.timer|${UNITDIR}/orpheus-kiosk-update.timer|0644"
    "${HERE}/50-orpheus-no-ctrl-alt-del.conf|${CONFD}/50-orpheus-no-ctrl-alt-del.conf|0644"
)

log() { echo "[kiosk] $*"; }
die() { echo "[kiosk] ERROR: $*" >&2; exit 1; }

kiosk_home() { getent passwd "${KUSER}" | cut -d: -f6; }
kiosk_slice() { echo "user-$(id -u "${KUSER}").slice"; }

# Retries: the snap store has refused connections from this station for hours.
snap_retry() {
    local attempt
    for attempt in 1 2 3; do
        snap "$@" && return 0
        log "snap $* failed (attempt ${attempt}); retrying in 30 s"
        sleep 30
    done
    return 1
}

install_snaps() {
    local s
    for s in chromium gnome-core26; do
        if ! snap list "${s}" >/dev/null 2>&1; then
            log "installing the ${s} snap"
            snap_retry install "${s}" || die "could not install ${s} from the snap store"
        fi
    done
    # Chromium pulls in CUPS; the kiosk never prints, and cups-browsed listens on the network.
    if snap list cups >/dev/null 2>&1 && snap services cups 2>/dev/null | grep -q ' enabled '; then
        log "disabling the cups snap's services"
        snap stop --disable cups >/dev/null
    fi
    local present=()
    for s in "${SNAPS[@]}"; do snap list "${s}" >/dev/null 2>&1 && present+=("${s}"); done
    # Held from automatic refresh; orpheus-kiosk-update.timer applies updates weekly.
    snap refresh --hold=forever "${present[@]}" >/dev/null
}

install_user() {
    if ! id "${KUSER}" >/dev/null 2>&1; then
        log "creating the ${KUSER} user"
        useradd --create-home --shell /usr/sbin/nologin --user-group --groups video \
            --comment "Orpheus kiosk display" "${KUSER}" || die "useradd failed"
    fi
    # X opens the NVIDIA display through the logind session, which needs video (as gdm has).
    id -nG "${KUSER}" | tr ' ' '\n' | grep -qx video || usermod -aG video "${KUSER}"
    passwd -l "${KUSER}" >/dev/null
    local home; home="$(kiosk_home)"
    # Capture isolation: the user's login session must never start a PulseAudio.
    install -d -o "${KUSER}" -g "${KUSER}" -m 0755 "${home}/.config" "${home}/.config/systemd" \
        "${home}/.config/systemd/user" "${home}/.config/pulse"
    ln -sfn /dev/null "${home}/.config/systemd/user/pulseaudio.socket"
    ln -sfn /dev/null "${home}/.config/systemd/user/pulseaudio.service"
    chown -h "${KUSER}:${KUSER}" "${home}/.config/systemd/user/pulseaudio.socket" \
        "${home}/.config/systemd/user/pulseaudio.service"
    printf '# Orpheus kiosk: never start a PulseAudio for this user (capture isolation).\nautospawn = no\n' \
        > "${home}/.config/pulse/client.conf"
    chown "${KUSER}:${KUSER}" "${home}/.config/pulse/client.conf"
}

install_files() {
    local entry src dst mode reexec=0
    install -d -m 0755 "${LIB}" "${CONFD}"
    for entry in "${FILES[@]}"; do
        IFS='|' read -r src dst mode <<< "${entry}"
        [[ -f "${src}" ]] || die "missing ${src}"
        if ! cmp -s "${src}" "${dst}"; then
            [[ "${dst}" == "${CONFD}/"* ]] && reexec=1
            install -m "${mode}" -o root -g root "${src}" "${dst}"
            log "installed ${dst}"
        fi
    done
    systemctl mask ctrl-alt-del.target >/dev/null 2>&1
    # The manager reads system.conf.d only when it re-executes.
    (( reexec )) && { log "re-executing systemd for the Ctrl+Alt+Del setting"; systemctl daemon-reexec; }
    systemctl daemon-reload
}

install_limits() {
    # PAM moves X into the user's login session and the snap gives Chromium its own
    # scope, both under the user's slice: the caps go there, not on the service.
    systemctl set-property "$(kiosk_slice)" MemoryAccounting=yes \
        "MemoryLimit=${MEMORY_LIMIT}" "MemoryMax=${MEMORY_LIMIT}" "CPUShares=${CPU_SHARES}"
}

do_install() {
    local start="$1"
    [[ "$(id -u)" -eq 0 ]] || die "run as root (sudo)"
    install_snaps
    install_user
    install_files
    install_limits
    systemctl enable orpheus-kiosk.service >/dev/null 2>&1
    systemctl enable --now orpheus-kiosk-update.timer >/dev/null 2>&1
    if (( start )); then
        log "(re)starting orpheus-kiosk"
        systemctl restart orpheus-kiosk.service
    fi
    do_check
}

# One line per requirement; non-zero when anything differs from the checkout.
do_check() {
    local bad=0 entry src dst mode s home slice
    ok() { echo "  ✅ $*"; }
    no() { echo "  ❌ $*"; bad=1; }
    echo "Kiosk installation (checkout ${REPO}):"
    for entry in "${FILES[@]}"; do
        IFS='|' read -r src dst mode <<< "${entry}"
        if cmp -s "${src}" "${dst}"; then ok "${dst}"; else no "${dst} differs from ${src#"${REPO}/"}"; fi
    done
    for s in chromium gnome-core26; do
        snap list "${s}" >/dev/null 2>&1 && ok "snap ${s} installed" || no "snap ${s} not installed"
    done
    for s in "${SNAPS[@]}"; do
        snap list "${s}" 2>/dev/null | awk 'NR > 1' | grep -q 'held' && ok "snap ${s} held from automatic refresh" \
            || { snap list "${s}" >/dev/null 2>&1 && no "snap ${s} is not held"; }
    done
    snap services cups 2>/dev/null | grep -q ' enabled ' && no "cups snap services are enabled" || ok "cups snap services disabled"
    if id "${KUSER}" >/dev/null 2>&1; then
        ok "user ${KUSER} exists"
        id -nG "${KUSER}" | tr ' ' '\n' | grep -qx video && ok "${KUSER} is in video" || no "${KUSER} is not in video (X cannot open the display)"
        passwd -S "${KUSER}" 2>/dev/null | awk '{print $2}' | grep -qx L && ok "${KUSER} password locked" || no "${KUSER} password not locked"
        home="$(kiosk_home)"
        for s in socket service; do
            [[ "$(readlink "${home}/.config/systemd/user/pulseaudio.${s}" 2>/dev/null)" == /dev/null ]] \
                && ok "pulseaudio.${s} masked for ${KUSER}" || no "pulseaudio.${s} not masked for ${KUSER}"
        done
        grep -qx 'autospawn = no' "${home}/.config/pulse/client.conf" 2>/dev/null \
            && ok "PulseAudio autospawn off for ${KUSER}" || no "PulseAudio autospawn not off for ${KUSER}"
        pgrep -u "${KUSER}" -x pulseaudio >/dev/null && no "a PulseAudio is running as ${KUSER}" || ok "no PulseAudio running as ${KUSER}"
        slice="$(kiosk_slice)"
        [[ "$(systemctl show "${slice}" -p MemoryLimit --value)" == "$((800 * 1024 * 1024))" ]] \
            && ok "${slice} memory limit ${MEMORY_LIMIT}" || no "${slice} memory limit is not ${MEMORY_LIMIT}"
        [[ "$(systemctl show "${slice}" -p CPUShares --value)" == "${CPU_SHARES}" ]] \
            && ok "${slice} CPU shares ${CPU_SHARES}" || no "${slice} CPU shares are not ${CPU_SHARES}"
    else
        no "user ${KUSER} does not exist"
    fi
    [[ "$(systemctl is-enabled ctrl-alt-del.target 2>/dev/null)" == masked ]] \
        && ok "ctrl-alt-del.target masked" || no "ctrl-alt-del.target not masked"
    [[ "$(systemctl is-enabled orpheus-kiosk.service 2>/dev/null)" == enabled ]] \
        && ok "orpheus-kiosk enabled at boot" || no "orpheus-kiosk not enabled at boot"
    [[ "$(systemctl is-enabled orpheus-kiosk-update.timer 2>/dev/null)" == enabled ]] \
        && ok "orpheus-kiosk-update.timer enabled" || no "orpheus-kiosk-update.timer not enabled"
    echo "  ℹ️  orpheus-kiosk is $(systemctl is-active orpheus-kiosk.service 2>/dev/null)"
    return "${bad}"
}

do_uninstall() {
    [[ "$(id -u)" -eq 0 ]] || die "run as root (sudo)"
    local entry src dst mode
    systemctl disable --now orpheus-kiosk.service orpheus-kiosk-update.timer >/dev/null 2>&1
    for entry in "${FILES[@]}"; do
        IFS='|' read -r src dst mode <<< "${entry}"
        [[ "${dst}" == "${CONFD}/"* ]] && continue   # keyboard-reboot protection stays
        rm -f "${dst}"
    done
    id "${KUSER}" >/dev/null 2>&1 && systemctl revert "$(kiosk_slice)" >/dev/null 2>&1
    systemctl daemon-reload
    log "removed the kiosk. Kept: the ${KUSER} user, the snaps, and the Ctrl+Alt+Del protection"
    log "  (remove with: userdel -r ${KUSER}; snap remove chromium; systemctl unmask ctrl-alt-del.target)"
}

main() {
    case "${1:-}" in
        "") do_install 1 ;;
        --no-start) do_install 0 ;;
        --check) do_check ;;
        --uninstall) do_uninstall ;;
        -h | --help) sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
        *) die "unknown option '$1' (see --help)" ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
