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
#   1. this udev rule: when the drive (named as /etc/fstab names it) appears,
#      systemd starts its mount. fsck runs first, as at boot, and a failed
#      check leaves the drive unmounted and the services stopped;
#   2. each data-root unit's [Install] WantedBy=data-orpheus.mount, written by
#      its own install-service's `systemctl enable`: when the mount starts, it
#      starts the enabled services. A disabled service stays stopped.
#
# Effective at the next time the drive appears (a replug or the next boot).
# Nothing is mounted, started, restarted or re-triggered now.
#
#   sudo deploy/storage/install-data-root-recovery.sh [DATA_ROOT]   (default /data/orpheus)
#
# ORPHEUS_RECOVERY_ROOT prefixes /etc (tests); FSTAB names the fstab to read;
# SYSTEMCTL and UDEVADM override the binaries.
set -euo pipefail

data_root="${1:-${ORPHEUS_DATA_ROOT:-/data/orpheus}}"
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

source_spec=""
[[ -f "${fstab}" ]] && source_spec="$(findmnt --tab-file "${fstab}" -n -o SOURCE --mountpoint "${data_root}" 2>/dev/null || true)"
if [[ -z "${source_spec}" ]]; then
    echo "${data_root} is not its own entry in ${fstab}: no separate drive to recover, nothing installed"
    exit 0
fi

# The udev property that carries each fstab identifier (60-persistent-storage.rules).
case "${source_spec}" in
    UUID=*)      key=ID_FS_UUID;         value="${source_spec#UUID=}" ;;
    LABEL=*)     key=ID_FS_LABEL;        value="${source_spec#LABEL=}" ;;
    PARTUUID=*)  key=ID_PART_ENTRY_UUID; value="${source_spec#PARTUUID=}" ;;
    PARTLABEL=*) key=ID_PART_ENTRY_NAME; value="${source_spec#PARTLABEL=}" ;;
    /dev/disk/by-uuid/*)  key=ID_FS_UUID;  value="${source_spec#/dev/disk/by-uuid/}" ;;
    /dev/disk/by-label/*) key=ID_FS_LABEL; value="${source_spec#/dev/disk/by-label/}" ;;
    *)
        echo "ERROR: /etc/fstab mounts ${data_root} from '${source_spec}'. A kernel name like" >&2
        echo "       /dev/sda1 can change when the drive reconnects (it did on jetson1)." >&2
        echo "       Use UUID=... (see: lsblk -f), then run this again." >&2
        exit 1 ;;
esac
value="${value//\"/}"
mount_unit="$(systemd-escape -p --suffix=mount "${data_root}")"

install -d -m 0755 "${rules_dir}"
cat > "${rule}.tmp" <<EOF
# Installed by deploy/storage/install-data-root-recovery.sh from the Orpheus
# repository. When the Orpheus data drive (${source_spec} in /etc/fstab)
# appears, start its mount; the mount then starts the Orpheus services that
# stopped when the drive went away. Remove this file to undo.
ACTION!="remove", SUBSYSTEM=="block", ENV{${key}}=="${value}", ENV{SYSTEMD_WANTS}+="${mount_unit}"
EOF
chmod 0644 "${rule}.tmp"
mv -f "${rule}.tmp" "${rule}"
echo "Installed ${rule} (${key}=${value} -> ${mount_unit})"

"${udevadm}" control --reload
"${systemctl}" daemon-reload

echo
echo "Done. Effective the next time the drive appears; nothing was restarted."
echo "The services come back only if they are enabled with the current unit files"
echo "(WantedBy=... ${mount_unit}); their install-service does that."
echo "Undo: sudo rm ${rule} && sudo udevadm control --reload"
