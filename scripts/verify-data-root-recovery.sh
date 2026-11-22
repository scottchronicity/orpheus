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

source_spec=""
[[ -f "${fstab}" ]] && source_spec="$(findmnt --tab-file "${fstab}" -n -o SOURCE --mountpoint "${data_root}" 2>/dev/null || true)"
if [[ -z "${source_spec}" ]]; then
    echo "✅ ${data_root} is not a separate drive in /etc/fstab: nothing to recover"
    exit 0
fi
mount_unit="$(systemd-escape -p --suffix=mount "${data_root}")"

bad=0
ok() { echo "✅ $*"; }
no() { echo "❌ $*"; bad=1; }
show() { "${systemctl}" show "$1" -p "$2" --value 2>/dev/null; }

identifier="${source_spec#*=}"; identifier="${identifier##*/}"; identifier="${identifier//\"/}"
if [[ -f "${rule}" ]] && grep -q "SYSTEMD_WANTS}+=\"${mount_unit}\"" "${rule}" \
        && grep -qF "==\"${identifier}\"" "${rule}"; then
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
