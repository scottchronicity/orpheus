#!/usr/bin/env bats
#
# BATS tests for Orpheus Bluetooth Auto-Connect script
#
# These tests verify the connection logic and audio switching functionality
# without requiring actual Bluetooth hardware.
#

# Setup function runs before each test
setup() {
    # Create a temporary directory for mocks
    TEST_DIR="$(mktemp -d)"
    export PATH="${TEST_DIR}:${PATH}"
    
    # Create mock bluetoothctl that simulates successful connection
    cat > "${TEST_DIR}/bluetoothctl" << 'EOF'
#!/bin/bash
# Mock bluetoothctl that always succeeds
while IFS= read -r line; do
    if [[ "$line" == connect* ]]; then
        echo "Attempting to connect to ${line#connect }"
        echo "Connection successful"
    elif [[ "$line" == trust* ]]; then
        echo "[CHG] Device ${line#trust } Trusted: yes"
    elif [[ "$line" == info* ]]; then
        echo "Device ${line#info }"
        echo "        Connected: yes"
    fi
done
EOF
    chmod +x "${TEST_DIR}/bluetoothctl"
    
    # Create mock su command that captures the command being run
    # We need to export TEST_DIR so the mock script can see it
    export TEST_DIR
    cat > "${TEST_DIR}/su" << 'EOF'
#!/bin/bash
# Mock su that logs the command and user
# Format: su - <user> -c "<command>"
if [[ "$1" == "-" ]] && [[ "$3" == "-c" ]]; then
    USER="$2"
    COMMAND="$4"
    echo "MOCK_SU_USER=${USER}" >> "${TEST_DIR}/su.log"
    echo "MOCK_SU_COMMAND=${COMMAND}" >> "${TEST_DIR}/su.log"
    
    # Simulate pactl list sinks short for polling test
    # Always return success with a generic bluez sink pattern
    if [[ "$COMMAND" == *"pactl list sinks short"* ]]; then
        # Return multiple sinks including any bluez_sink that matches the MAC
        echo "0	alsa_output.pci.stereo-fallback	module-alsa-card.c	s16le 2ch 44100Hz	IDLE"
        # Return a bluez sink that will match any MAC pattern being tested
        echo "1	bluez_sink.FC_58_FA_02_AF_28.a2dp_sink	module-bluez5-device.c	s16le 2ch 44100Hz	RUNNING"
        echo "2	bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink	module-bluez5-device.c	s16le 2ch 44100Hz	SUSPENDED"
        exit 0
    fi
    
    # Simulate pactl list sink-inputs short for moving streams
    if [[ "$COMMAND" == *"pactl list sink-inputs short"* ]]; then
        # Return some fake sink inputs
        echo "42	0	module-stream-restore.c	float32le 2ch 44100Hz"
        exit 0
    fi
    
    # Simulate success for all other commands
    exit 0
fi
exit 1
EOF
    chmod +x "${TEST_DIR}/su"
    
    # Create mock id command
    cat > "${TEST_DIR}/id" << 'EOF'
#!/bin/bash
# Mock id that returns a fake UID
if [[ "$1" == "-u" ]]; then
    echo "1000"
    exit 0
fi
exit 1
EOF
    chmod +x "${TEST_DIR}/id"
    
    # Create mock pactl (shouldn't be called directly, only via su)
    cat > "${TEST_DIR}/pactl" << 'EOF'
#!/bin/bash
# Mock pactl - shouldn't be called in our tests
echo "ERROR: pactl called directly (should be via su)" >&2
exit 1
EOF
    chmod +x "${TEST_DIR}/pactl"
    
    # Source the script functions
    export BLUETOOTH_MAC="FC:58:FA:02:AF:28"
    export AUDIO_USER="orpheus"
    export RECONNECT_DELAY=1
    
    # Load the script's functions
    SCRIPT_PATH="${BATS_TEST_DIRNAME}/../scripts/orpheus-bluetooth-connect.sh"
    
    # Extract just the functions for testing
    source <(sed -n '/^log_info()/,/^}/p' "${SCRIPT_PATH}")
    source <(sed -n '/^log_success()/,/^}/p' "${SCRIPT_PATH}")
    source <(sed -n '/^log_error()/,/^}/p' "${SCRIPT_PATH}")
    source <(sed -n '/^connect_device()/,/^}/p' "${SCRIPT_PATH}")
}

# Teardown function runs after each test
teardown() {
    # Clean up temporary directory
    if [ -n "${TEST_DIR}" ] && [ -d "${TEST_DIR}" ]; then
        rm -rf "${TEST_DIR}"
    fi
}

@test "connect_device successfully connects to Bluetooth device" {
    # Run the connect_device function
    run connect_device
    
    # Should succeed
    [ "$status" -eq 0 ]
    
    # Should log connection success
    [[ "$output" =~ "Connected to FC:58:FA:02:AF:28" ]]
}

@test "connect_device switches audio output after connection" {
    # Run the connect_device function
    run connect_device
    
    # Should succeed
    [ "$status" -eq 0 ]
    
    # Should attempt to switch audio
    [[ "$output" =~ "Switching audio output to Bluetooth device" ]]
}

@test "connect_device converts MAC address format correctly" {
    # Run the connect_device function
    run connect_device
    
    # Check that su.log was created
    [ -f "${TEST_DIR}/su.log" ]
    
    # Verify the MAC address was converted from FC:58:FA:02:AF:28 to FC_58_FA_02_AF_28
    grep "MOCK_SU_COMMAND=pactl set-default-sink bluez_sink.FC_58_FA_02_AF_28.a2dp_sink" "${TEST_DIR}/su.log"
}

@test "connect_device runs pactl as correct user" {
    # Run the connect_device function
    run connect_device
    
    # Check that su.log was created
    [ -f "${TEST_DIR}/su.log" ]
    
    # Verify su was called with the correct user
    grep "MOCK_SU_USER=orpheus" "${TEST_DIR}/su.log"
}

@test "connect_device constructs correct sink name" {
    # Run the connect_device function
    run connect_device
    
    # Check the output mentions the correct sink name
    [[ "$output" =~ "bluez_sink.FC_58_FA_02_AF_28.a2dp_sink" ]]
}

@test "connect_device respects AUDIO_USER environment variable" {
    # Override the AUDIO_USER
    export AUDIO_USER="testuser"
    
    # Re-source the connect_device function with new environment
    source <(sed -n '/^connect_device()/,/^}/p' "${BATS_TEST_DIRNAME}/../scripts/orpheus-bluetooth-connect.sh")
    
    # Run the connect_device function
    run connect_device
    
    # Check that su.log was created
    [ -f "${TEST_DIR}/su.log" ]
    
    # Verify su was called with the overridden user
    grep "MOCK_SU_USER=testuser" "${TEST_DIR}/su.log"
}

@test "connect_device uses correct MAC address with custom value" {
    # Override the MAC address
    export BLUETOOTH_MAC="AA:BB:CC:DD:EE:FF"
    
    # Re-source the connect_device function with new environment
    source <(sed -n '/^connect_device()/,/^}/p' "${BATS_TEST_DIRNAME}/../scripts/orpheus-bluetooth-connect.sh")
    
    # Run the connect_device function
    run connect_device
    
    # Check that su.log was created
    [ -f "${TEST_DIR}/su.log" ]
    
    # Verify the custom MAC address was converted correctly
    grep "MOCK_SU_COMMAND=pactl set-default-sink bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink" "${TEST_DIR}/su.log"
}
