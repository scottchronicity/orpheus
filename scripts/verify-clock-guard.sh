#!/bin/bash
# Check that Orpheus starts on a real clock after a cold boot.
#
# The Jetson has no battery-backed clock by default; it boots at 1970 or at
# timesyncd's last saved time. time-sync.target only means "NTP has set the
# clock" when systemd-time-wait-sync is enabled. Without that, an Orpheus
# service ordered after the target still starts on whatever the clock says.
# Reads what systemd has LOADED (systemctl show), so an installed change that
# was never daemon-reloaded is caught too. Read-only; changes nothing.
#
# Exit 0 when every check holds, 1 otherwise. SYSTEMCTL overrides systemctl.
# Fix with: make install-clock-guard  (deploy/clock/install-clock-guard.sh)
set -uo pipefail

systemctl="${SYSTEMCTL:-systemctl}"
# shellcheck source=data-root-units.sh
source "$(dirname "$0")/data-root-units.sh"

bad=0
ok() { echo "✅ $*"; }
no() { echo "❌ $*"; bad=1; }
show() { "${systemctl}" show "$1" -p "$2" --value 2>/dev/null; }

enabled=$("${systemctl}" is-enabled systemd-time-wait-sync.service 2>/dev/null)
if [[ "${enabled}" == "enabled" ]]; then
    ok "systemd-time-wait-sync is enabled: time-sync.target waits for NTP"
else
    no "systemd-time-wait-sync is ${enabled:-not installed}: time-sync.target does not wait for NTP"
fi

timeout=$(show systemd-time-wait-sync.service TimeoutStartUSec)
if [[ -n "${timeout}" && "${timeout}" != "infinity" ]]; then
    ok "the wait for NTP is bounded (${timeout}): an offline station still starts"
else
    no "the wait for NTP is unbounded (${timeout:-unknown}): an offline station would never start"
fi

if [[ "$(show nvrtc-sync-boot.service LoadState)" == "loaded" ]]; then
    if [[ " $(show nvrtc-sync-boot.service Before) " == *" systemd-timesyncd.service "* ]]; then
        ok "nvrtc-sync-boot runs before timesyncd: a batteryless RTC cannot set the clock back to 1970"
    else
        no "nvrtc-sync-boot can run after timesyncd and set the clock back to 1970"
    fi
fi

late=()
checked=0
for name in "${DATA_ROOT_UNITS[@]}"; do
    unit="${name}.service"
    [[ "$(show "${unit}" LoadState)" == "loaded" ]] || continue   # not installed here
    checked=$((checked + 1))
    [[ " $(show "${unit}" After) " == *" time-sync.target "* ]] || late+=("${unit}")
done
if (( ${#late[@]} )); then
    no "not ordered after time-sync.target (reinstall the unit, then daemon-reload): ${late[*]}"
elif (( checked )); then
    ok "all ${checked} installed data-root services start after time-sync.target"
fi

(( bad )) && echo "   Fix: make install-clock-guard (takes effect at the next boot)"
exit "${bad}"
