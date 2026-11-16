#!/bin/bash
# X session for the Orpheus kiosk on a Jetson's own monitor: no desktop, no
# window manager, one full-screen Chromium on the /kiosk page.
#
# Started by orpheus-kiosk.service through xinit. It starts the browser only
# while a monitor is attached, and closes it when the monitor goes away, so a
# headless station carries only an idle X server. The keyboard and touchpad
# work as in any X session; nothing here grabs or remaps them.
set -uo pipefail

launcher="${ORPHEUS_KIOSK_LAUNCHER:-/usr/local/lib/orpheus-kiosk/orpheus-kiosk-browser.sh}"
poll="${ORPHEUS_KIOSK_MONITOR_POLL:-15}"

# Prints "WxH" for the first connected output, nothing when none is connected.
connected_mode() {
    xrandr --query 2>/dev/null | awk '
        / connected/ { want = 1; next }
        want && /^[[:space:]]+[0-9]+x[0-9]+/ { print $1; exit }'
}

browser_pid=""
stop_browser() {
    if [[ -n "${browser_pid}" ]] && kill -0 "${browser_pid}" 2>/dev/null; then
        kill "${browser_pid}" 2>/dev/null
        wait "${browser_pid}" 2>/dev/null
    fi
    browser_pid=""
}
main() {
    xset s off -dpms s noblank 2>/dev/null || true
    trap 'stop_browser; exit 0' TERM INT
    while true; do
        mode="$(connected_mode)"
        if [[ -z "${mode}" ]]; then
            if [[ -n "${browser_pid}" ]]; then
                echo "orpheus-kiosk: monitor disconnected; closing the browser"
                stop_browser
            fi
        elif [[ -z "${browser_pid}" ]] || ! kill -0 "${browser_pid}" 2>/dev/null; then
            echo "orpheus-kiosk: monitor at ${mode}; starting the browser"
            xrandr --auto 2>/dev/null || true
            ORPHEUS_KIOSK_WINDOW="${mode/x/,}" "${launcher}" &
            browser_pid=$!
        fi
        sleep "${poll}" &
        wait $! 2>/dev/null
    done
}

# Sourceable: tests exercise connected_mode without starting a session.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main
fi
