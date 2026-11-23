#!/bin/bash
# Remove orpheus-audio-output and undo the host changes its installer recorded.
# RESTORE_LEGACY=1 (make rollback) also brings back orpheus-bluetooth-autoconnect
# as it was installed before, enabled and running only if it was then. Every
# competing unit returns to the enabled/running state it had. Settings files
# are never deleted.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lifecycle.sh
. "${SCRIPT_DIR}/lifecycle.sh"
RESTORE_LEGACY="${RESTORE_LEGACY:-0}"

if [[ "${REQUIRE_ROOT:-1}" == "1" && ${EUID} -ne 0 ]]; then
    echo "Run as root: make uninstall-service (or make rollback)" >&2
    exit 1
fi

systemctl stop "${NEW_UNIT}" 2>/dev/null || true
systemctl disable "${NEW_UNIT}" 2>/dev/null || true
rm -f "${UNIT_DIR}/${NEW_UNIT}"
undo_changes "${CHANGES}" "${RESTORE_LEGACY}"
systemctl daemon-reload
rm -rf "${DEPLOY_ROOT}"
if [[ "${RESTORE_LEGACY}" == "1" ]]; then
    say "uninstalled; orpheus-bluetooth-autoconnect restored as it was before"
else
    say "uninstalled"
fi
