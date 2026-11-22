#!/usr/bin/env bash
# Bring Orpheus back by itself when the data drive drops out and returns.
#
# Every service that uses the data root requires its mount, so when the drive
# disconnects systemd stops them all: correctly, since they would otherwise
# write onto the root filesystem. But nothing mounts the drive again when it
# reappears, and nothing restarts the services. On jetson1 (2026-11-22) a USB
# drop 110 s after boot left the station not recording, with the kiosk showing
# "Station unreachable", until someone noticed.
#
# Two pieces close that loop:
#   1. this udev rule: when the drive (identified as /etc/fstab names it, so
#      any disk and any UUID) appears, systemd starts its mount. fsck runs
#      first, as at boot, and a failed check leaves the drive unmounted and the
#      services stopped;
#   2. each data-root unit's [Install] WantedBy=data-orpheus.mount, written by
#      its own install-service's `systemctl enable`: when the mount starts, it
#      starts the enabled services. A disabled service stays stopped.
#
# Effective at the next time the drive appears (a replug or the next boot).
# Nothing is mounted, started, restarted or re-triggered now. Hosts this does
# not apply to (no separate data drive, a network share, a drive fstab names by
# kernel name) get a message and exit 0, so `make install-host` carries on;
# `make verify-deploy` reports the last one as a failure to fix in /etc/fstab.
#
#   sudo deploy/storage/install-data-root-recovery.sh [DATA_ROOT]   (default /data/orpheus)
#
# ORPHEUS_RECOVERY_ROOT prefixes /etc (tests); FSTAB names the fstab to read;
# SYSTEMCTL and UDEVADM override the binaries.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../../scripts/data-root-source.sh
source "${here}/../../scripts/data-root-source.sh"

data_root="${1:-${ORPHEUS_DATA_ROOT:-${STATION_DATA_ROOT}}}"
root="${ORPHEUS_RECOVERY_ROOT:-}"
fstab="${FSTAB:-${root}/etc/fstab}"
systemctl="${SYSTEMCTL:-systemctl}"
udevadm="${UDEVADM:-udevadm}"
rules_dir="${root}/etc/udev/rules.d"
rule="${rules_dir}/90-orpheus-data-root.rules"

if [[ -z "${root}" && "$(id -u)" -ne 0 ]]; then
    echo "ERROR: run with sudo — this writes ${rule}" >&2
    exit 1
fi

source_spec="$(data_root_source "${data_root}" "${fstab}")"
if [[ -z "${source_spec}" ]]; then
    echo "${data_root} is not its own entry in ${fstab}: no separate drive to recover, nothing installed"
    exit 0
fi
if [[ "${data_root}" != "${STATION_DATA_ROOT}" ]]; then
    echo "ERROR: ${data_root} is a separate drive, but Orpheus's services require and restart" >&2
    echo "       with ${STATION_DATA_ROOT} (RequiresMountsFor, WantedBy=data-orpheus.mount)." >&2
    echo "       Mount the data drive at ${STATION_DATA_ROOT} instead. Nothing installed." >&2
    exit 1
fi
match=0; udev_match "${source_spec}" || match=$?
if (( match == 1 )); then
    echo "WARNING: /etc/fstab mounts ${data_root} from '${source_spec}', a kernel name that can"
    echo "         change when the drive reconnects (it did on jetson1). Name it by UUID=..."
    echo "         (see: lsblk -f), then run this again. Nothing installed."
    exit 0
elif (( match == 2 )); then
    echo "${data_root} is mounted from '${source_spec}', not a local drive: nothing installed"
    exit 0
fi
mount_unit="$(systemd-escape -p --suffix=mount "${data_root}")"

install -d -m 0755 "${rules_dir}"
cat > "${rule}.tmp" <<EOF
# Installed by deploy/storage/install-data-root-recovery.sh from the Orpheus
# repository. When the Orpheus data drive (${source_spec} in /etc/fstab)
# appears, start its mount; the mount then starts the Orpheus services that
# stopped when the drive went away. Remove this file to undo.
ACTION!="remove", SUBSYSTEM=="block", ENV{${UDEV_KEY}}=="${UDEV_VALUE}", ENV{SYSTEMD_WANTS}+="${mount_unit}"
EOF
chmod 0644 "${rule}.tmp"
mv -f "${rule}.tmp" "${rule}"
echo "Installed ${rule} (${UDEV_KEY}=${UDEV_VALUE} -> ${mount_unit})"

"${udevadm}" control --reload
"${systemctl}" daemon-reload

echo
echo "Done. Effective the next time the drive appears; nothing was restarted."
echo "The services come back only if they are enabled with the current unit files"
echo "(WantedBy=... ${mount_unit}); their install-service does that."
echo "Undo: sudo rm ${rule} && sudo udevadm control --reload"
