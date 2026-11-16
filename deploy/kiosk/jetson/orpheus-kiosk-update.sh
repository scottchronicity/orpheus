#!/bin/bash
# Weekly security updates for the kiosk browser and its runtime snaps.
#
# snapd's automatic refresh is held for these snaps so it never replaces the
# browser in the middle of the day or during a timelapse encode; this job
# applies the updates instead, once a week in a quiet window. An explicit
# `snap refresh <name>` is not blocked by the hold.
#
# The kiosk is stopped only when one of these snaps has a newer revision on its
# channel, and is put back the way it was found. When the store cannot be
# reached the job fails (see `systemctl status orpheus-kiosk-update`) and the
# kiosk keeps running.
set -uo pipefail
snaps=(chromium gnome-core26 mesa-2604 core26 cups)
attempts="${ORPHEUS_KIOSK_UPDATE_ATTEMPTS:-3}"
pause="${ORPHEUS_KIOSK_UPDATE_PAUSE:-60}"
snap_cmd="${SNAP_CMD:-snap}"

# Prints the snaps whose tracked channel has a different revision from the one
# installed. Reads `snap info`, so it works whether or not the snap is held.
# Fails when the store cannot be reached.
pending_snaps() {
    local s info tracking installed latest
    for s in "${snaps[@]}"; do
        info=$("${snap_cmd}" info "${s}" 2>&1) || return 1
        tracking=$(awk '/^tracking:/ { print $2 }' <<< "${info}")
        installed=$(awk '/^installed:/ { print $3 }' <<< "${info}" | tr -d '()')
        latest=$(awk -v ch="${tracking}:" '$1 == ch { print $4 }' <<< "${info}" | tr -d '()')
        [[ -n "${installed}" && -n "${latest}" ]] || return 1
        [[ "${installed}" == "${latest}" ]] || echo "${s}"
    done
}

main() {
    local attempt pending="" reached=0 was_active rc=1
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        if pending=$(pending_snaps); then reached=1; break; fi
        echo "orpheus-kiosk-update: snap store not reachable (attempt ${attempt})"
        (( attempt < attempts )) && sleep "${pause}"
    done
    if (( ! reached )); then
        echo "orpheus-kiosk-update: no update this week; the kiosk was left running"
        return 1
    fi
    if [[ -z "${pending}" ]]; then
        echo "orpheus-kiosk-update: kiosk snaps are up to date"
        return 0
    fi

    echo "orpheus-kiosk-update: updating" ${pending}
    was_active=$(systemctl is-active orpheus-kiosk 2>/dev/null || true)
    [[ "${was_active}" == active ]] && systemctl stop orpheus-kiosk
    for ((attempt = 1; attempt <= attempts; attempt++)); do
        # shellcheck disable=SC2086  # one argument per pending snap
        if "${snap_cmd}" refresh ${pending}; then rc=0; break; fi
        echo "orpheus-kiosk-update: snap refresh attempt ${attempt} failed"
        (( attempt < attempts )) && sleep "${pause}"
    done
    [[ "${was_active}" == active ]] && systemctl start orpheus-kiosk
    "${snap_cmd}" list "${snaps[@]}" 2>/dev/null
    return "${rc}"
}

# Sourceable: tests exercise pending_snaps without touching snapd.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main
fi
