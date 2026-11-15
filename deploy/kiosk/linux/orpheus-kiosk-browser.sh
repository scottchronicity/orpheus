#!/bin/bash
# Open the Orpheus kiosk display full screen in Chromium (or Chrome).
#
# Optional, for a machine that already has a graphical session: a Raspberry
# Pi or mini PC beside the screen, or a desktop. Nothing in Orpheus installs
# or starts this. It needs a display (DISPLAY or WAYLAND_DISPLAY) and refuses
# to run without one; it never installs a graphical stack.
#
#   orpheus-kiosk-browser.sh [URL]
#
# Environment:
#   ORPHEUS_KIOSK_URL      default URL (default http://localhost:8080/kiosk)
#   ORPHEUS_KIOSK_BROWSER  browser binary (default: first of chromium,
#                          chromium-browser, google-chrome found on PATH)
#   ORPHEUS_KIOSK_GPU      "0" to disable GPU rasterisation. Use it on a host
#                          whose GPU runs inference (the Jetson), so the
#                          browser does not take GPU memory.
#   ORPHEUS_KIOSK_PROFILE  profile directory (default ~/.cache/orpheus-kiosk),
#                          kept separate from any everyday browser profile
#   ORPHEUS_KIOSK_DRY_RUN  "1" to print the command instead of running it
set -euo pipefail

url="${1:-${ORPHEUS_KIOSK_URL:-http://localhost:8080/kiosk}}"
case "${url}" in
    http://*/kiosk* | https://*/kiosk*) ;;
    *)
        echo "orpheus-kiosk-browser: '${url}' is not an http(s) URL of an Orpheus /kiosk page" >&2
        exit 2
        ;;
esac

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo "orpheus-kiosk-browser: no graphical session (DISPLAY/WAYLAND_DISPLAY unset)." >&2
    echo "Open ${url} from a browser on any machine instead; see docs/operator-manual/kiosk.md." >&2
    exit 3
fi

browser="${ORPHEUS_KIOSK_BROWSER:-}"
if [[ -z "${browser}" ]]; then
    for candidate in chromium chromium-browser google-chrome google-chrome-stable; do
        if command -v "${candidate}" >/dev/null 2>&1; then
            browser="${candidate}"
            break
        fi
    done
fi
if [[ -z "${browser}" ]] || ! command -v "${browser}" >/dev/null 2>&1; then
    echo "orpheus-kiosk-browser: no Chromium or Chrome found (set ORPHEUS_KIOSK_BROWSER)" >&2
    exit 4
fi

profile="${ORPHEUS_KIOSK_PROFILE:-${HOME}/.cache/orpheus-kiosk}"
args=(
    --kiosk
    --app="${url}"
    --user-data-dir="${profile}"
    --no-first-run
    --noerrdialogs
    --disable-infobars
    --disable-session-crashed-bubble
    --disable-translate
    --disable-features=TranslateUI
    --check-for-update-interval=31536000
    --password-store=basic
)
if [[ "${ORPHEUS_KIOSK_GPU:-1}" == "0" ]]; then
    args+=(--disable-gpu --disable-gpu-compositing)
fi

if [[ "${ORPHEUS_KIOSK_DRY_RUN:-0}" == "1" ]]; then
    printf '%q ' "${browser}" "${args[@]}"
    echo
    exit 0
fi
mkdir -p "${profile}"
exec "${browser}" "${args[@]}"
