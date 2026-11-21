#!/usr/bin/env bash
# Make Orpheus start on a real clock after a cold boot.
#
# Installs two systemd drop-ins from this directory and enables
# systemd-time-wait-sync. Everything takes effect at the next boot: nothing is
# started, stopped or restarted now. The why is in the drop-ins' comments.
#
#   sudo deploy/clock/install-clock-guard.sh
#
# ORPHEUS_CLOCK_ROOT prefixes /etc (tests); SYSTEMCTL overrides systemctl.
set -euo pipefail

root="${ORPHEUS_CLOCK_ROOT:-}"
systemctl="${SYSTEMCTL:-systemctl}"
here="$(cd "$(dirname "$0")" && pwd)"
units="${root}/etc/systemd/system"

if [[ -z "${root}" && "$(id -u)" -ne 0 ]]; then
    echo "ERROR: run with sudo — this writes ${units}" >&2
    exit 1
fi

installed=()
install_dropin() {  # <unit> <source file in this directory>
    install -d -m 0755 "${units}/$1.d"
    install -m 0644 "${here}/$2" "${units}/$1.d/10-orpheus.conf"
    installed+=("${units}/$1.d/10-orpheus.conf")
    echo "Installed ${units}/$1.d/10-orpheus.conf"
}

install_dropin systemd-time-wait-sync.service time-wait-sync.conf
if [[ "$("${systemctl}" show nvrtc-sync-boot.service -p LoadState --value 2>/dev/null)" == "loaded" ]]; then
    install_dropin nvrtc-sync-boot.service nvrtc-sync-boot.conf
else
    echo "nvrtc-sync-boot.service is not installed (not a Jetson): no RTC ordering needed"
fi

"${systemctl}" daemon-reload
"${systemctl}" enable systemd-time-wait-sync.service

echo
echo "Done. Effective from the next boot; nothing was restarted."
echo "Undo: sudo systemctl disable systemd-time-wait-sync.service"
echo "      sudo rm ${installed[*]}"
echo "      sudo systemctl daemon-reload"
