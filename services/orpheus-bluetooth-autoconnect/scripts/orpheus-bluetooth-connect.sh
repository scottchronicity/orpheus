#!/bin/bash
#
# Orpheus Bluetooth Auto-Connect
#
# Keeps one paired Bluetooth speaker connected and routes PulseAudio output to
# it. Runs as a long-lived systemd service (orpheus-bluetooth-autoconnect):
# each poll reads the device state, reconnects when it has dropped, and backs
# off (up to MAX_RECONNECT_DELAY) while the speaker or BlueZ is unavailable.
# Connecting needs a running audio server (PulseAudio with its Bluetooth
# module) to have registered the A2DP endpoint; this script does not start or
# configure one.
#
# Configuration (environment, or the config file below; the file wins):
#   BLUETOOTH_SPEAKER_MAC  MAC address of the paired speaker
#   AUDIO_USER             user whose PulseAudio receives the speaker (default orpheus)
#   RECONNECT_DELAY        seconds between polls while healthy (default 10)
#   MAX_RECONNECT_DELAY    backoff ceiling in seconds (default 60)
#
# Why bluetoothctl is only ever called with arguments, never fed on stdin:
# in interactive mode (`echo "connect X" | bluetoothctl`) every invocation
# loads, appends to and rewrites readline history in ~/.cache/.bluetoothctl_history.
# Run as root every few seconds, that file grew without bound (31 MB / 2.1 M
# lines on the field station), and each call then spent ~48 s and ~64 MB
# re-reading it inside this unit's 64M / 10% CPU limits. Argument mode keeps
# no history.
#
# Usage: BLUETOOTH_SPEAKER_MAC=XX:XX:XX:XX:XX:XX orpheus-bluetooth-connect
#
# Deliberately not `set -e`: this is a supervisor loop, and every failure is
# handled (and logged) explicitly. Under -e a failing command substitution,
# e.g. `pactl set-default-sink` while PulseAudio restarts, killed the loop.
set -uo pipefail

CONFIG_FILE="${ORPHEUS_BLUETOOTH_CONFIG:-/etc/orpheus/bluetooth-autoconnect/config.env}"
if [[ -f "${CONFIG_FILE}" ]]; then
    # shellcheck source=/dev/null
    . "${CONFIG_FILE}"
fi

# Default is this project's field-station speaker; installs write their own.
BLUETOOTH_MAC="${BLUETOOTH_SPEAKER_MAC:-FC:58:FA:02:AF:28}"
AUDIO_USER="${AUDIO_USER:-orpheus}"
RECONNECT_DELAY="${RECONNECT_DELAY:-10}"
MAX_RECONNECT_DELAY="${MAX_RECONNECT_DELAY:-60}"
BT_COMMAND_TIMEOUT="${BT_COMMAND_TIMEOUT:-15}"   # info/show/trust/power
BT_CONNECT_TIMEOUT="${BT_CONNECT_TIMEOUT:-45}"   # connect (page timeout + profile setup)
SCAN_SECONDS="${SCAN_SECONDS:-10}"
SINK_WAIT_SECONDS="${SINK_WAIT_SECONDS:-10}"
STARTUP_DELAY="${STARTUP_DELAY:-3}"
PULSE_RUNTIME_ROOT="${PULSE_RUNTIME_ROOT:-/run/user}"

EX_CONFIG=78   # sysexits.h EX_CONFIG; the unit does not restart on it

# Loop state, carried between polls.
DEVICE_STATE=""
DEVICE_INFO=""
LAST_STATE=""
FAILURES=0
AUDIO_ROUTED=false
NEXT_DELAY="${RECONNECT_DELAY}"
TARGET_UID=""
SLEEP_PID=""

# Logging functions
log_info() {
    echo "[INFO] $1"
}

log_success() {
    echo "[SUCCESS] $1"
}

log_warn() {
    echo "[WARN] $1"
}

log_error() {
    echo "[ERROR] $1" >&2
}

# bluetoothctl in non-interactive (argument) mode, bounded by a timeout so a
# missing or wedged bluetoothd (bluetoothctl waits for it forever) cannot
# stall the loop. Usage: bt <timeout-seconds> <bluetoothctl args...>
bt() {
    local limit="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout -k 5 "${limit}" bluetoothctl "$@"
    else
        bluetoothctl "$@"
    fi
}

validate_config() {
    local ok=0 n
    if [[ ! "${BLUETOOTH_MAC}" =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]; then
        log_error "Invalid BLUETOOTH_SPEAKER_MAC '${BLUETOOTH_MAC}' (expected XX:XX:XX:XX:XX:XX); set it in ${CONFIG_FILE}"
        ok=1
    fi
    for n in RECONNECT_DELAY MAX_RECONNECT_DELAY BT_COMMAND_TIMEOUT BT_CONNECT_TIMEOUT SCAN_SECONDS SINK_WAIT_SECONDS STARTUP_DELAY; do
        if [[ ! "${!n}" =~ ^[0-9]+$ ]]; then
            log_error "Invalid ${n} '${!n}' (expected a whole number of seconds)"
            ok=1
        fi
    done
    if [[ "${RECONNECT_DELAY}" == "0" ]]; then
        log_error "RECONNECT_DELAY must be at least 1 second"
        ok=1
    fi
    return "${ok}"
}

# Resolve AUDIO_USER to a UID once. Returns 1 (and logs) when audio routing
# is impossible; the Bluetooth connection itself is still maintained.
resolve_audio_user() {
    if [[ -n "${TARGET_UID}" ]]; then
        return 0
    fi
    # Validate AUDIO_USER (only allow alphanumeric, underscore, hyphen)
    if [[ ! "${AUDIO_USER}" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        log_error "Invalid AUDIO_USER: ${AUDIO_USER} (only alphanumeric, underscore, and hyphen allowed)"
        return 1
    fi
    local uid
    if ! uid=$(id -u "${AUDIO_USER}" 2>/dev/null) || [[ -z "${uid}" ]]; then
        log_error "Unable to get UID for user: ${AUDIO_USER}"
        return 1
    fi
    TARGET_UID="${uid}"
    return 0
}

# Run a command line as AUDIO_USER against that user's PulseAudio.
as_audio_user() {
    su - "${AUDIO_USER}" -c "export XDG_RUNTIME_DIR=${PULSE_RUNTIME_ROOT}/${TARGET_UID}; $1"
}

# Diagnostic only, never a gate: the A2DP endpoint may be registered by an
# audio server running as another user (e.g. a desktop session). Checks the
# socket file rather than running `pactl info`, because a client connect may
# autospawn PulseAudio, which grabs the capture interface on stations that
# keep it stopped (see the audio-motion agent's README).
audio_server_hint() {
    if resolve_audio_user 2>/dev/null && [[ -S "${PULSE_RUNTIME_ROOT}/${TARGET_UID}/pulse/native" ]]; then
        return 0
    fi
    log_info "Hint: no PulseAudio socket for ${AUDIO_USER} (${PULSE_RUNTIME_ROOT}/${TARGET_UID:-?}/pulse/native). If 'journalctl -u bluetooth' shows 'a2dp-sink profile connect failed ... Protocol not available', no audio server has registered A2DP with BlueZ."
}

# Read the device and controller state into DEVICE_STATE / DEVICE_INFO:
#   connected | disconnected | unpaired | missing | no_controller | unavailable
refresh_device_state() {
    local rc
    DEVICE_INFO=$(bt "${BT_COMMAND_TIMEOUT}" info "${BLUETOOTH_MAC}" 2>&1)
    rc=$?
    case "${DEVICE_INFO}" in
        *"No default controller available"*) DEVICE_STATE=no_controller ;;
        *"Connected: yes"*) DEVICE_STATE=connected ;;
        *"Paired: no"*) DEVICE_STATE=unpaired ;;
        *"Connected: no"*) DEVICE_STATE=disconnected ;;
        *"not available"*) DEVICE_STATE=missing ;;
        *)
            DEVICE_STATE=unavailable
            if [[ "${rc}" -eq 124 || "${rc}" -eq 137 ]]; then
                DEVICE_INFO="bluetoothctl timed out after ${BT_COMMAND_TIMEOUT}s"
            else
                DEVICE_INFO="bluetoothctl exited ${rc}: ${DEVICE_INFO}"
            fi
            ;;
    esac
}

# Check if device is connected
is_connected() {
    refresh_device_state
    [[ "${DEVICE_STATE}" == "connected" ]]
}

# Trust the device so reconnects never wait on an authorization prompt.
trust_device() {
    log_info "Trusting Bluetooth device ${BLUETOOTH_MAC}..."
    if bt "${BT_COMMAND_TIMEOUT}" trust "${BLUETOOTH_MAC}" >/dev/null 2>&1; then
        log_success "Device ${BLUETOOTH_MAC} trusted"
        return 0
    fi
    log_error "Failed to trust device ${BLUETOOTH_MAC}"
    return 1
}

# Pull the reason out of bluetoothctl's connect output, e.g.
# "Failed to connect: org.bluez.Error.Failed".
connect_failure_reason() {
    local reason
    reason=$(printf '%s\n' "$1" | grep -m1 -E 'Failed to connect|not available|Error' || true)
    if [[ -z "${reason}" ]]; then
        reason=$(printf '%s\n' "$1" | tail -n 1)
    fi
    printf '%s' "${reason:-no output}"
}

# Connect to the Bluetooth device, then route audio to it. Returns 0 once
# BlueZ reports the device connected; an audio-routing failure leaves
# AUDIO_ROUTED=false for the main loop to retry and does not undo the link.
connect_device() {
    log_info "Attempting to connect to ${BLUETOOTH_MAC}..."

    local out
    out=$(bt "${BT_CONNECT_TIMEOUT}" connect "${BLUETOOTH_MAC}" 2>&1)
    if ! is_connected; then
        # As before: a discovery scan to wake the stack and re-populate the
        # controller cache, then one more attempt.
        log_info "Initial connection failed ($(connect_failure_reason "${out}")). Refreshing Bluetooth cache with scan..."
        bt "$((SCAN_SECONDS + 5))" --timeout "${SCAN_SECONDS}" scan on >/dev/null 2>&1 || true
        sleep 2
        out=$(bt "${BT_CONNECT_TIMEOUT}" connect "${BLUETOOTH_MAC}" 2>&1)
        if ! is_connected; then
            log_error "Failed to connect to ${BLUETOOTH_MAC} even after cache refresh: $(connect_failure_reason "${out}")"
            audio_server_hint
            return 1
        fi
    fi

    log_success "Connected to ${BLUETOOTH_MAC}"
    if switch_audio_output; then
        AUDIO_ROUTED=true
    else
        AUDIO_ROUTED=false
    fi
    return 0
}

# Make the speaker PulseAudio's default sink and move playing streams to it.
# Returns 1 when the sink could not be selected, so the caller retries.
switch_audio_output() {
    log_info "Switching audio output to Bluetooth device..."
    resolve_audio_user || return 1

    # Convert MAC address format from AA:BB:CC:DD:EE:FF to AA_BB_CC_DD_EE_FF
    local sink_name="bluez_sink.${BLUETOOTH_MAC//:/_}.a2dp_sink"

    # Poll for the Bluetooth sink to appear (1 second each)
    log_info "Waiting for Bluetooth sink to be available..."
    local sinks="" tries=0
    while :; do
        sinks=$(as_audio_user "pactl list sinks short" 2>&1) || true
        if [[ "${sinks}" == *"${sink_name}"* ]]; then
            log_success "Bluetooth sink is available"
            break
        fi
        tries=$((tries + 1))
        if [[ "${tries}" -ge "${SINK_WAIT_SECONDS}" ]]; then
            log_error "Bluetooth sink ${sink_name} did not become available after ${SINK_WAIT_SECONDS} seconds"
            log_info "Available sinks:"
            printf '%s\n' "${sinks}" | sed 's/^/  /'
            return 1
        fi
        sleep 1
    done

    # Set the default sink
    log_info "Setting default sink to ${sink_name}..."
    local set_out
    if ! set_out=$(as_audio_user "pactl set-default-sink ${sink_name}" 2>&1); then
        log_error "Failed to switch audio output to ${sink_name}: ${set_out}"
        return 1
    fi
    log_success "Audio output switched to ${sink_name}"

    # Move any currently playing audio streams to the new sink
    log_info "Moving active audio streams to Bluetooth sink..."
    local move_out
    if move_out=$(as_audio_user "pactl list sink-inputs short | cut -f1 | xargs -r -I{} pactl move-sink-input {} ${sink_name}" 2>&1); then
        log_success "Active audio streams moved to Bluetooth sink"
    else
        log_info "No active audio streams to move (or move failed): ${move_out}"
    fi
    return 0
}

# Try to bring a non-connected device back. Returns 0 when connected.
attempt_connection() {
    case "${DEVICE_STATE}" in
        no_controller)
            log_error "No Bluetooth controller available (adapter missing, blocked by rfkill, or bluetoothd still starting)"
            return 1
            ;;
        unavailable)
            log_error "BlueZ did not answer (${DEVICE_INFO}); is bluetooth.service running?"
            return 1
            ;;
        missing)
            log_error "Device ${BLUETOOTH_MAC} is not known to BlueZ. Pair it once, with the speaker in pairing mode: bluetoothctl pair ${BLUETOOTH_MAC} && bluetoothctl trust ${BLUETOOTH_MAC}"
            ;;
        unpaired)
            log_error "Device ${BLUETOOTH_MAC} is known but not paired. Pair it once, with the speaker in pairing mode: bluetoothctl pair ${BLUETOOTH_MAC}"
            ;;
    esac

    connect_device
}

# Capped exponential backoff: RECONNECT_DELAY while healthy, doubling per
# consecutive failure up to MAX_RECONNECT_DELAY.
compute_next_delay() {
    local delay="${RECONNECT_DELAY}" i=1
    while [[ "${i}" -lt "${FAILURES}" && "${delay}" -lt "${MAX_RECONNECT_DELAY}" ]]; do
        delay=$((delay * 2))
        i=$((i + 1))
    done
    if [[ "${delay}" -gt "${MAX_RECONNECT_DELAY}" ]]; then
        delay="${MAX_RECONNECT_DELAY}"
    fi
    NEXT_DELAY="${delay}"
}

# One supervision step; sets NEXT_DELAY. Logs state changes and failures only,
# so a healthy connection stays quiet in the journal.
poll_once() {
    refresh_device_state
    if [[ "${DEVICE_STATE}" != "${LAST_STATE}" ]]; then
        log_info "Device ${BLUETOOTH_MAC} state: ${LAST_STATE:-startup} -> ${DEVICE_STATE}"
        LAST_STATE="${DEVICE_STATE}"
    fi

    if [[ "${DEVICE_STATE}" == "connected" ]]; then
        if [[ "${AUDIO_ROUTED}" == "true" ]]; then
            FAILURES=0
        elif switch_audio_output; then
            AUDIO_ROUTED=true
            FAILURES=0
        else
            FAILURES=$((FAILURES + 1))
        fi
    else
        AUDIO_ROUTED=false
        log_info "Device ${BLUETOOTH_MAC} is not connected, attempting connection..."
        if attempt_connection; then
            log_success "Successfully connected to ${BLUETOOTH_MAC}"
            LAST_STATE=connected
            if [[ "${AUDIO_ROUTED}" == "true" ]]; then
                FAILURES=0
            else
                FAILURES=$((FAILURES + 1))
            fi
        else
            FAILURES=$((FAILURES + 1))
        fi
    fi

    compute_next_delay
    if [[ "${FAILURES}" -gt 0 ]]; then
        log_error "Speaker not ready (${FAILURES} consecutive failures), will retry in ${NEXT_DELAY} seconds"
    fi
}

# Sleep in the background so SIGTERM is handled at once, not after a backoff
# sleep of up to MAX_RECONNECT_DELAY.
sleep_interruptible() {
    sleep "$1" &
    SLEEP_PID=$!
    wait "${SLEEP_PID}" 2>/dev/null || true
    SLEEP_PID=""
}

on_stop() {
    log_info "Orpheus Bluetooth Auto-Connect stopping"
    if [[ -n "${SLEEP_PID}" ]]; then
        kill "${SLEEP_PID}" 2>/dev/null || true
    fi
    exit 0
}

# Startup, as before: wait for bluetooth.service, trust the device once.
startup() {
    log_info "Orpheus Bluetooth Auto-Connect service started"
    log_info "Target device: ${BLUETOOTH_MAC}; audio user: ${AUDIO_USER}; poll ${RECONNECT_DELAY}s, backoff up to ${MAX_RECONNECT_DELAY}s"

    # Give bluetooth.service a moment to fully initialize
    if [[ "${STARTUP_DELAY}" -gt 0 ]]; then
        sleep_interruptible "${STARTUP_DELAY}"
    fi

    # Trust the device once at startup
    trust_device || log_error "Warning: Could not trust device, continuing anyway..."
}

# Main loop
main() {
    if ! validate_config; then
        exit "${EX_CONFIG}"
    fi
    trap on_stop TERM INT

    startup

    while true; do
        poll_once
        sleep_interruptible "${NEXT_DELAY}"
    done
}

# Run the loop only when executed; tests source this file for its functions.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
