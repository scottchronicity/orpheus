#!/bin/bash
# Check that every installed service using the data root waits for its drive.
#
# Reads what systemd has LOADED (systemctl show), not the files on disk, so an
# installed unit that was never daemon-reloaded is caught too. A service that
# starts before /data/orpheus is mounted writes recordings and a fresh, empty
# database onto the root filesystem. Read-only; changes nothing.
#
#   verify-data-mount-dependency.sh [DATA_ROOT]   (default /data/orpheus)
#
# Exit 0 when every installed one carries the dependency, 1 when any lacks it.
# SYSTEMCTL overrides the systemctl binary (tests).
set -uo pipefail

data_root="${1:-/data/orpheus}"
systemctl="${SYSTEMCTL:-systemctl}"
# shellcheck source=data-root-units.sh
source "$(dirname "$0")/data-root-units.sh"

bad=0
for name in "${DATA_ROOT_UNITS[@]}"; do
    unit="${name}.service"
    load=$("${systemctl}" show "${unit}" -p LoadState --value 2>/dev/null)
    [[ "${load}" == "loaded" ]] || continue   # not installed on this host
    mounts=$("${systemctl}" show "${unit}" -p RequiresMountsFor --value 2>/dev/null)
    if [[ " ${mounts} " == *" ${data_root} "* ]]; then
        echo "✅ ${unit} waits for ${data_root}"
    else
        echo "❌ ${unit} does not require ${data_root} to be mounted (reinstall its unit, then daemon-reload)"
        bad=1
    fi
done
exit "${bad}"
