# Sourced, not run. How /etc/fstab names the station's data drive, shared by
# deploy/storage/install-data-root-recovery.sh and scripts/verify-data-root-recovery.sh
# so the installer and the check always agree.
#
# A station's data root is /data/orpheus: every shipped unit declares
# RequiresMountsFor=/data/orpheus and WantedBy=data-orpheus.mount. Any local
# drive, filesystem or disk UUID works mounted there. ORPHEUS_DATA_ROOT
# elsewhere is for development hosts, which do not run the units.
# shellcheck disable=SC2034  # used by the sourcing script
STATION_DATA_ROOT=/data/orpheus

# data_root_source <data_root> <fstab>: the fstab SOURCE that mounts data_root,
# or nothing when data_root is not its own entry.
data_root_source() {
    [[ -f "$2" ]] || return 0
    findmnt --tab-file "$2" -n -o SOURCE --mountpoint "$1" 2>/dev/null || true
}

# data_root_parent <data_root> <fstab>: "MOUNTPOINT SOURCE" of the deepest fstab
# entry that mounts a directory above data_root (other than /), or nothing. A
# station drive mounted at /data, with /data/orpheus a directory on it, never
# gets a data-orpheus.mount, so the services would never restart with it.
data_root_parent() {
    [[ -f "$2" ]] || return 0
    local target source best="" best_source=""
    while read -r target source; do
        [[ "${target}" != "/" && "$1" == "${target%/}/"* && ${#target} -gt ${#best} ]] || continue
        best="${target}" best_source="${source}"
    done < <(findmnt --tab-file "$2" -n -r -o TARGET,SOURCE 2>/dev/null)
    [[ -n "${best}" ]] && echo "${best} ${best_source}"
    return 0
}

# udev_match <fstab source>: sets UDEV_KEY/UDEV_VALUE, the udev property that
# identifies that drive whatever port or kernel name it comes back on.
# Returns 1 for a kernel name (/dev/sda1 ...), which can change on reconnect,
# and 2 for anything that is not a local drive (a network share, ...).
udev_match() {
    UDEV_KEY="" UDEV_VALUE=""
    case "$1" in
        UUID=*)                   UDEV_KEY=ID_FS_UUID;         UDEV_VALUE="${1#UUID=}" ;;
        LABEL=*)                  UDEV_KEY=ID_FS_LABEL;        UDEV_VALUE="${1#LABEL=}" ;;
        PARTUUID=*)               UDEV_KEY=ID_PART_ENTRY_UUID; UDEV_VALUE="${1#PARTUUID=}" ;;
        PARTLABEL=*)              UDEV_KEY=ID_PART_ENTRY_NAME; UDEV_VALUE="${1#PARTLABEL=}" ;;
        /dev/disk/by-uuid/*)      UDEV_KEY=ID_FS_UUID;         UDEV_VALUE="${1#/dev/disk/by-uuid/}" ;;
        /dev/disk/by-label/*)     UDEV_KEY=ID_FS_LABEL;        UDEV_VALUE="${1#/dev/disk/by-label/}" ;;
        /dev/disk/by-partuuid/*)  UDEV_KEY=ID_PART_ENTRY_UUID; UDEV_VALUE="${1#/dev/disk/by-partuuid/}" ;;
        /dev/disk/by-partlabel/*) UDEV_KEY=ID_PART_ENTRY_NAME; UDEV_VALUE="${1#/dev/disk/by-partlabel/}" ;;
        /dev/*) return 1 ;;
        *)      return 2 ;;
    esac
    UDEV_VALUE="${UDEV_VALUE//\"/}"
}
