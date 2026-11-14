#!/bin/bash
# Remove orpheus-audio-output and undo the host changes its installer recorded.
# RESTORE_LEGACY=1 (make rollback) also brings back orpheus-bluetooth-autoconnect
# exactly as it was installed before. Settings files are never deleted.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lifecycle.sh
. "${SCRIPT_DIR}/lifecycle.sh"
RESTORE_LEGACY="${RESTORE_LEGACY:-0}"

if [[ ${EUID} -ne 0 ]]; then
    echo "Run as root: make uninstall-service (or make rollback)" >&2
    exit 1
fi

systemctl stop "${NEW_UNIT}" 2>/dev/null || true
systemctl disable "${NEW_UNIT}" 2>/dev/null || true
rm -f "${UNIT_DIR}/${NEW_UNIT}"
undo_changes "${RESTORE_LEGACY}"
systemctl daemon-reload
if [[ "${RESTORE_LEGACY}" == "1" && -e "${UNIT_DIR}/${LEGACY_UNIT}" ]]; then
    systemctl start "${LEGACY_UNIT}" || true
fi
rm -rf /opt/orpheus/services/orpheus-audio-output
say "uninstalled${RESTORE_LEGACY:+ (restore legacy: ${RESTORE_LEGACY})}"
