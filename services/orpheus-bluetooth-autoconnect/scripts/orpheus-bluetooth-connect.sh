#!/bin/bash
#
# Orpheus Bluetooth Auto-Connect Script
#
# This script ensures a Bluetooth speaker automatically connects and
# reconnects if the connection drops. It's designed to run as a systemd
# service with automatic restart on failure.
#
# Configuration is via environment variable or hardcoded default:
#   BLUETOOTH_SPEAKER_MAC - MAC address of the Bluetooth device
#   AUDIO_USER            - User running PulseAudio (default: orpheus)
#
# Usage: BLUETOOTH_SPEAKER_MAC=XX:XX:XX:XX:XX:XX orpheus-bluetooth-connect
#

set -euo pipefail

# Configuration
# Default to JBL Flip 4, override with environment variable
BLUETOOTH_MAC="${BLUETOOTH_SPEAKER_MAC:-FC:58:FA:02:AF:28}"
AUDIO_USER="${AUDIO_USER:-orpheus}"  # User running PulseAudio
RECONNECT_DELAY=10  # Seconds to wait before reconnecting

# Logging functions
log_info() {
    echo "[INFO] $1"
}

log_success() {
    echo "[SUCCESS] $1"
}

log_error() {
    echo "[ERROR] $1" >&2
}

# Trust the device to prevent pairing prompts
trust_device() {
    log_info "Trusting Bluetooth device ${BLUETOOTH_MAC}..."
    if echo -e "trust ${BLUETOOTH_MAC}\nquit" | bluetoothctl; then
        log_success "Device ${BLUETOOTH_MAC} trusted"
        return 0
    else
        log_error "Failed to trust device ${BLUETOOTH_MAC}"
        return 1
    fi
}
# Connect to the Bluetooth device
connect_device() {
    log_info "Attempting to connect to ${BLUETOOTH_MAC}..."
    
    # --- Part 1: Connection Logic with Cache Refresh ---
    # Attempt 1: Standard connection
    if ! echo -e "connect ${BLUETOOTH_MAC}\nquit" | bluetoothctl | grep -q "Connection successful"; then
        log_info "Initial connection failed. Refreshing Bluetooth cache with scan..."
        # 10s scan to wake up the stack and re-populate the controller cache
        timeout 10 bluetoothctl scan on > /dev/null 2>&1 || true
        sleep 2
        
        # Attempt 2: Connection after cache refresh
        if ! echo -e "connect ${BLUETOOTH_MAC}\nquit" | bluetoothctl | grep -q "Connection successful"; then
             log_error "Failed to connect to ${BLUETOOTH_MAC} even after cache refresh"
             return 1
        fi
    fi

    log_success "Connected to ${BLUETOOTH_MAC}"
    
    # --- Part 2: Switch Audio Output (PulseAudio) ---
    log_info "Switching audio output to Bluetooth device..."
    
    # Validate AUDIO_USER (only allow alphanumeric, underscore, hyphen)
    if [[ ! "${AUDIO_USER}" =~ ^[a-zA-Z0-9_-]+$ ]]; then
        log_error "Invalid AUDIO_USER: ${AUDIO_USER} (only alphanumeric, underscore, and hyphen allowed)"
        return 0
    fi
    
    # Get the UID of the AUDIO_USER for XDG_RUNTIME_DIR
    TARGET_UID=$(id -u "${AUDIO_USER}" 2>/dev/null)
    if [[ -z "${TARGET_UID}" ]]; then
        log_error "Unable to get UID for user: ${AUDIO_USER}"
        return 0
    fi
    
    # Set up PulseAudio environment variable
    PULSE_ENV="export XDG_RUNTIME_DIR=/run/user/${TARGET_UID}"
    
    # Convert MAC address format from AA:BB:CC:DD:EE:FF to AA_BB_CC_DD_EE_FF
    MAC_WITH_UNDERSCORES="${BLUETOOTH_MAC//:/_}"
    
    # Construct the PulseAudio sink name
    SINK_NAME="bluez_sink.${MAC_WITH_UNDERSCORES}.a2dp_sink"
    
    # Poll for the Bluetooth sink to appear (max 10 retries, 1 second each)
    log_info "Waiting for Bluetooth sink to be available..."
    RETRY_COUNT=0
    MAX_RETRIES=10
    SINK_AVAILABLE=false
    
    while [ "${RETRY_COUNT}" -lt "${MAX_RETRIES}" ]; do
        if su - "${AUDIO_USER}" -c "${PULSE_ENV}; pactl list sinks short" 2>/dev/null | grep -q "${SINK_NAME}"; then
            SINK_AVAILABLE=true
            log_success "Bluetooth sink is available"
            break
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        sleep 1
    done
    
    if [ "${SINK_AVAILABLE}" != "true" ]; then
        log_error "Bluetooth sink ${SINK_NAME} did not become available after ${MAX_RETRIES} seconds"
        log_info "Available sinks:"
        su - "${AUDIO_USER}" -c "${PULSE_ENV}; pactl list sinks short" 2>&1 | sed 's/^/  /'
        return 0
    fi

    # Set the default sink
    log_info "Setting default sink to ${SINK_NAME}..."
    SET_SINK_OUTPUT=$(su - "${AUDIO_USER}" -c "${PULSE_ENV}; pactl set-default-sink \"${SINK_NAME}\"" 2>&1)
    SET_SINK_EXIT_CODE=$?
    
    if [ ${SET_SINK_EXIT_CODE} -eq 0 ]; then
        log_success "Audio output switched to ${SINK_NAME}"

        # Move any currently playing audio streams to the new sink
        log_info "Moving active audio streams to Bluetooth sink..."
        MOVE_OUTPUT=$(su - "${AUDIO_USER}" -c "${PULSE_ENV}; pactl list sink-inputs short | cut -f1 | xargs -r -I{} pactl move-sink-input {} \"${SINK_NAME}\"" 2>&1)
        MOVE_EXIT_CODE=$?
        
        if [ ${MOVE_EXIT_CODE} -eq 0 ]; then
            log_success "Active audio streams moved to Bluetooth sink"
        else
            log_info "No active audio streams to move (or move failed): ${MOVE_OUTPUT}"
        fi
    else
        log_error "Failed to switch audio output to ${SINK_NAME}"
        log_error "Error output: ${SET_SINK_OUTPUT}"
        log_error "Exit code: ${SET_SINK_EXIT_CODE}"
    fi
    
    return 0
}

# Check if device is connected
is_connected() {
    echo -e "info ${BLUETOOTH_MAC}\nquit" | bluetoothctl | grep -q "Connected: yes"
}

# Main loop
main() {
    log_info "Orpheus Bluetooth Auto-Connect service started"
    log_info "Target device: ${BLUETOOTH_MAC}"
    
    # Give bluetooth.service a moment to fully initialize
    sleep 3
    
    # Trust the device once at startup
    trust_device || log_error "Warning: Could not trust device, continuing anyway..."
    
    # Main connection loop
    while true; do
        if is_connected; then
            log_info "Device ${BLUETOOTH_MAC} is connected"
        else
            log_info "Device ${BLUETOOTH_MAC} is not connected, attempting connection..."
            if connect_device; then
                log_success "Successfully connected to ${BLUETOOTH_MAC}"
            else
                log_error "Connection attempt failed, will retry in ${RECONNECT_DELAY} seconds"
            fi
        fi
        
        # Wait before checking again
        sleep "${RECONNECT_DELAY}"
    done
}

# Run main loop
main
