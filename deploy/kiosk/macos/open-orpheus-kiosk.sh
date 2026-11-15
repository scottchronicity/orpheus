#!/bin/bash
# Open the Orpheus kiosk display on a Mac. Optional; any browser tab works.
#
#   open-orpheus-kiosk.sh [URL]          # default http://jetson1:8080/kiosk
#
# With Google Chrome installed, opens it full screen in kiosk mode (Cmd-Q to
# leave) with its own profile. Otherwise opens the URL in the default browser;
# use View > Enter Full Screen (Ctrl-Cmd-F) there.
set -euo pipefail

url="${1:-${ORPHEUS_KIOSK_URL:-http://jetson1:8080/kiosk}}"
case "${url}" in
    http://*/kiosk* | https://*/kiosk*) ;;
    *)
        echo "open-orpheus-kiosk: '${url}' is not an http(s) URL of an Orpheus /kiosk page" >&2
        exit 2
        ;;
esac

chrome="/Applications/Google Chrome.app"
if [[ -d "${chrome}" && "${ORPHEUS_KIOSK_DRY_RUN:-0}" != "1" ]]; then
    exec open -na "${chrome}" --args --kiosk --app="${url}" \
        --user-data-dir="${HOME}/Library/Caches/orpheus-kiosk" --no-first-run
fi
if [[ "${ORPHEUS_KIOSK_DRY_RUN:-0}" == "1" ]]; then
    echo "open ${url}"
    exit 0
fi
exec open "${url}"
