#!/bin/bash
# Check that Orpheus comes back by itself when the data drive drops out and
# returns: a udev rule starts the drive's mount when the drive appears, and the
# mount starts every enabled data-root service (their WantedBy=). Without both,
# a brief USB disconnect stops recording until someone restarts it by hand
# (jetson1, 2026-11-22). Reads what systemd has LOADED. Read-only.
#
#   verify-data-root-recovery.sh [DATA_ROOT]   (default /data/orpheus)
#
# Exit 0 when it holds (or the data root is not a separate drive), 1 otherwise.
# ORPHEUS_RECOVERY_ROOT prefixes /etc, FSTAB names the fstab, SYSTEMCTL
# overrides systemctl (tests).
set -uo pipefail

data_root="${1:-/data/orpheus}"
root="${ORPHEUS_RECOVERY_ROOT:-}"
fstab="${FSTAB:-${root}/etc/fstab}"
systemctl="${SYSTEMCTL:-systemctl}"
rule="${root}/etc/udev/rules.d/90-orpheus-data-root.rules"
# shellcheck source=data-root-units.sh
source "$(dirname "$0")/data-root-units.sh"
# shellcheck source=data-root-source.sh
source "$(dirname "$0")/data-root-source.sh"

source_spec="$(data_root_source "${data_root}" "${fstab}")"
if [[ -z "${source_spec}" && "${data_root}" == "${STATION_DATA_ROOT}" ]]; then
    read -r parent parent_source <<< "$(data_root_parent "${data_root}" "${fstab}")"
    if [[ -n "${parent:-}" ]]; then
        parent_match=0; udev_match "${parent_source}" || parent_match=$?
        if (( parent_match == 2 )); then
            echo "✅ ${data_root} is on '${parent_source}' (mounted at ${parent}), not a local drive: nothing to recover"
            exit 0
        fi
        echo "❌ /etc/fstab mounts ${parent} from '${parent_source}', with ${data_root} a directory on it: the services restart with ${data_root}'s own mount, which never exists. Fix: mount the drive at ${STATION_DATA_ROOT} itself"
        exit 1
    fi
fi
if [[ -z "${source_spec}" ]]; then
    echo "✅ ${data_root} is not a separate drive in /etc/fstab: nothing to recover"
    exit 0
fi
match=0; udev_match "${source_spec}" || match=$?
if (( match == 2 )); then
    echo "✅ ${data_root} is mounted from '${source_spec}', not a local drive: nothing to recover"
    exit 0
fi
mount_unit="$(systemd-escape -p --suffix=mount "${data_root}")"

bad=0
ok() { echo "✅ $*"; }
no() { echo "❌ $*"; bad=1; }
show() { "${systemctl}" show "$1" -p "$2" --value 2>/dev/null; }

if [[ "${data_root}" != "${STATION_DATA_ROOT}" ]]; then
    no "${data_root} is a separate drive, but the services require and restart with ${STATION_DATA_ROOT}: mount the drive there"
elif (( match == 1 )); then
    no "/etc/fstab names the data drive '${source_spec}', a kernel name that can change when it reconnects: use UUID= (lsblk -f)"
elif [[ -f "${rule}" ]] && grep -qF "ENV{${UDEV_KEY}}==\"${UDEV_VALUE}\", ENV{SYSTEMD_WANTS}+=\"${mount_unit}\"" "${rule}"; then
    ok "the drive (${source_spec}) starts ${mount_unit} when it reappears"
else
    no "nothing mounts ${data_root} again when the drive reappears (no rule for ${source_spec} in ${rule})"
fi

wants=" $(show "${mount_unit}" Wants) "
missing=()
checked=0
for name in "${DATA_ROOT_SERVICES[@]}"; do
    unit="${name}.service"
    [[ "$(show "${unit}" LoadState)" == "loaded" ]] || continue            # not installed here
    [[ "$("${systemctl}" is-enabled "${unit}" 2>/dev/null)" == "enabled" ]] || continue  # deliberately off
    checked=$((checked + 1))
    [[ "${wants}" == *" ${unit} "* ]] || missing+=("${unit}")
done
if (( ${#missing[@]} )); then
    no "${mount_unit} would not restart (re-run their install-service, or: sudo systemctl reenable <unit>): ${missing[*]}"
elif (( checked )); then
    ok "${mount_unit} restarts all ${checked} enabled data-root services"
fi

(( bad )) && echo "   Fix: make install-data-root-recovery, and reinstall the services' units"
exit "${bad}"
