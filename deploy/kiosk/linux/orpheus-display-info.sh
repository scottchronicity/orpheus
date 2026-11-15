#!/bin/bash
# Report which displays this Linux host can see, read-only.
#
# For choosing where a kiosk screen should run: lists DRM connectors and
# whether a monitor is attached to each (with its preferred mode), USB
# display adapters, and whether a graphical session is running. Changes
# nothing, starts nothing, needs no root and no display server.
#
#   orpheus-display-info.sh
#
# SYSROOT (tests only) prefixes /sys and /proc paths.
set -uo pipefail

SYSROOT="${SYSROOT:-}"
DRM="${SYSROOT}/sys/class/drm"
found=0

echo "Display connectors (${DRM}):"
connectors=0
for dir in "${DRM}"/card*-*; do
    [[ -d "${dir}" ]] || continue
    name="$(basename "${dir}")"
    connectors=$((connectors + 1))
    status="$(cat "${dir}/status" 2>/dev/null || echo unknown)"
    modes="$(head -n 1 "${dir}/modes" 2>/dev/null || true)"
    if [[ "${status}" == "connected" ]]; then
        found=$((found + 1))
        echo "  ${name}: connected${modes:+, preferred mode ${modes}}"
    else
        echo "  ${name}: ${status}"
    fi
done
if [[ "${connectors}" -eq 0 ]]; then
    if grep -q '^nvidia_modeset ' "${SYSROOT}/proc/modules" 2>/dev/null \
        && ! grep -q '^nvidia_drm ' "${SYSROOT}/proc/modules" 2>/dev/null; then
        # NVIDIA Jetson (L4T): displays are driven by nvidia-modeset; without
        # nvidia-drm loaded the kernel exposes no connectors to inspect.
        echo "  none exposed: the NVIDIA display driver (nvidia_modeset) is loaded without nvidia_drm,"
        echo "  so attached monitors cannot be listed here; a display session (Xorg) would report them"
        unknown_hdmi=1
    else
        echo "  (no connectors)"
    fi
fi

echo "USB display adapters:"
usb=0
for dev in "${SYSROOT}"/sys/bus/usb/devices/*; do
    [[ -f "${dev}/idVendor" ]] || continue
    vendor="$(cat "${dev}/idVendor")"
    product="$(cat "${dev}/product" 2>/dev/null || true)"
    # DisplayLink (17e9) adapters, or anything describing itself as a display/HDMI.
    if [[ "${vendor}" == "17e9" ]] || grep -qiE 'display|hdmi|video' <<< "${product}"; then
        echo "  $(basename "${dev}"): ${vendor}:$(cat "${dev}/idProduct" 2>/dev/null) ${product}"
        usb=$((usb + 1))
    fi
done
[[ "${usb}" -gt 0 ]] || echo "  (none)"

echo "Graphical session:"
sessions=0
for comm in Xorg Xwayland gnome-shell cage weston sway labwc wayfire; do
    if pgrep -x "${comm}" >/dev/null 2>&1; then
        echo "  ${comm} is running"
        sessions=$((sessions + 1))
    fi
done
[[ "${sessions}" -gt 0 ]] || echo "  none (headless) — a kiosk browser on this host would need one"

echo
if [[ "${found}" -eq 0 && "${unknown_hdmi:-0}" == "1" ]]; then
    echo "Monitor attachment unknown on this host (see above)."
elif [[ "${found}" -gt 0 ]]; then
    echo "${found} monitor(s) attached. See docs/operator-manual/kiosk.md before running a display on this host."
else
    echo "No monitor reported attached. A monitor behind a USB hub may only appear once it is powered on;"
    echo "a USB/DisplayLink adapter shows above but needs its own driver to drive a screen."
fi
