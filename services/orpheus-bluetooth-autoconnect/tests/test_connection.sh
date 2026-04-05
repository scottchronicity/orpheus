#!/bin/bash
#
# Simple bash test script for Orpheus Bluetooth Auto-Connect
# This tests the connection logic without requiring BATS or actual hardware
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Test helper functions
test_start() {
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -n "Test ${TESTS_RUN}: $1 ... "
}

test_pass() {
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo -e "${GREEN}PASS${NC}"
}

test_fail() {
    TESTS_FAILED=$((TESTS_FAILED + 1))
    echo -e "${RED}FAIL${NC}"
    if [ -n "${1:-}" ]; then
        echo "  Error: $1"
    fi
}

# Setup test environment
setup_test_env() {
    # Create temporary directory for mocks
    TEST_DIR="$(mktemp -d)"
    export PATH="${TEST_DIR}:${PATH}"
    export TEST_DIR
    
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
    
    # Create mock pactl (shouldn't be called directly)
    cat > "${TEST_DIR}/pactl" << 'EOF'
#!/bin/bash
echo "ERROR: pactl called directly" >&2
exit 1
EOF
    chmod +x "${TEST_DIR}/pactl"
}

# Cleanup test environment
cleanup_test_env() {
    if [ -n "${TEST_DIR:-}" ] && [ -d "${TEST_DIR}" ]; then
        rm -rf "${TEST_DIR}"
    fi
}

# Load script functions for testing
load_script_functions() {
    SCRIPT_PATH="${1}"
    
    # Source the logging and connection functions
    source <(sed -n '/^log_info()/,/^}/p' "${SCRIPT_PATH}")
    source <(sed -n '/^log_success()/,/^}/p' "${SCRIPT_PATH}")
    source <(sed -n '/^log_error()/,/^}/p' "${SCRIPT_PATH}")
    source <(sed -n '/^connect_device()/,/^}/p' "${SCRIPT_PATH}")
}

# Test 1: Successful connection
test_successful_connection() {
    test_start "connect_device successfully connects to Bluetooth device"
    
    export BLUETOOTH_MAC="FC:58:FA:02:AF:28"
    export AUDIO_USER="orpheus"
    
    # Run connect_device and capture output
    output=$(connect_device 2>&1)
    result=$?
    
    if [ $result -eq 0 ] && echo "$output" | grep -q "Connected to FC:58:FA:02:AF:28"; then
        test_pass
    else
        test_fail "Connection did not succeed (exit code: $result)"
    fi
}

# Test 2: Audio switching attempted
test_audio_switching() {
    test_start "connect_device attempts to switch audio output"
    
    export BLUETOOTH_MAC="FC:58:FA:02:AF:28"
    export AUDIO_USER="orpheus"
    
    output=$(connect_device 2>&1)
    
    if echo "$output" | grep -q "Switching audio output to Bluetooth device"; then
        test_pass
    else
        test_fail "Audio switching message not found in output"
    fi
}

# Test 3: MAC address format conversion
test_mac_address_conversion() {
    test_start "connect_device converts MAC address format correctly"
    
    export BLUETOOTH_MAC="FC:58:FA:02:AF:28"
    export AUDIO_USER="orpheus"
    rm -f "${TEST_DIR}/su.log"
    
    connect_device > /dev/null 2>&1
    
    if [ -f "${TEST_DIR}/su.log" ] && grep -q "bluez_sink.FC_58_FA_02_AF_28.a2dp_sink" "${TEST_DIR}/su.log"; then
        test_pass
    else
        test_fail "MAC address not converted correctly (expected FC_58_FA_02_AF_28)"
    fi
}

# Test 4: Correct user for pactl
test_correct_user() {
    test_start "connect_device runs pactl as correct user"
    
    export BLUETOOTH_MAC="FC:58:FA:02:AF:28"
    export AUDIO_USER="orpheus"
    rm -f "${TEST_DIR}/su.log"
    
    connect_device > /dev/null 2>&1
    
    if [ -f "${TEST_DIR}/su.log" ] && grep -q "MOCK_SU_USER=orpheus" "${TEST_DIR}/su.log"; then
        test_pass
    else
        test_fail "su not called with correct user"
    fi
}

# Test 5: Correct sink name construction
test_sink_name() {
    test_start "connect_device constructs correct sink name"
    
    export BLUETOOTH_MAC="FC:58:FA:02:AF:28"
    export AUDIO_USER="orpheus"
    
    output=$(connect_device 2>&1)
    
    if echo "$output" | grep -q "bluez_sink.FC_58_FA_02_AF_28.a2dp_sink"; then
        test_pass
    else
        test_fail "Sink name not found in output"
    fi
}

# Test 6: AUDIO_USER environment variable
test_audio_user_override() {
    test_start "connect_device respects AUDIO_USER environment variable"
    
    export BLUETOOTH_MAC="FC:58:FA:02:AF:28"
    export AUDIO_USER="testuser"
    rm -f "${TEST_DIR}/su.log"
    
    connect_device > /dev/null 2>&1
    
    if [ -f "${TEST_DIR}/su.log" ] && grep -q "MOCK_SU_USER=testuser" "${TEST_DIR}/su.log"; then
        test_pass
    else
        test_fail "Custom AUDIO_USER not respected"
    fi
}

# Test 7: Custom MAC address
test_custom_mac() {
    test_start "connect_device uses correct MAC address with custom value"
    
    export BLUETOOTH_MAC="AA:BB:CC:DD:EE:FF"
    export AUDIO_USER="orpheus"
    rm -f "${TEST_DIR}/su.log"
    
    connect_device > /dev/null 2>&1
    
    if [ -f "${TEST_DIR}/su.log" ] && grep -q "bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink" "${TEST_DIR}/su.log"; then
        test_pass
    else
        test_fail "Custom MAC address not converted correctly"
    fi
}

# Test 8: Invalid AUDIO_USER
test_invalid_audio_user() {
    test_start "connect_device rejects invalid AUDIO_USER characters"
    
    export BLUETOOTH_MAC="FC:58:FA:02:AF:28"
    export AUDIO_USER="user; rm -rf /"  # Security test: malicious user with shell injection attempt
    rm -f "${TEST_DIR}/su.log"
    
    output=$(connect_device 2>&1)
    result=$?
    
    # Should still succeed (connection) but skip audio switching
    if [ $result -eq 0 ] && echo "$output" | grep -q "Invalid AUDIO_USER"; then
        test_pass
    else
        test_fail "Invalid AUDIO_USER not rejected properly"
    fi
}

# Main test execution
main() {
    echo "======================================"
    echo "Orpheus Bluetooth Connection Tests"
    echo "======================================"
    echo ""
    
    # Get script path
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SCRIPT_PATH="${SCRIPT_DIR}/../scripts/orpheus-bluetooth-connect.sh"
    
    if [ ! -f "${SCRIPT_PATH}" ]; then
        echo -e "${RED}ERROR: Script not found at ${SCRIPT_PATH}${NC}"
        exit 1
    fi
    
    # Setup test environment
    setup_test_env
    trap cleanup_test_env EXIT
    
    # Load script functions
    load_script_functions "${SCRIPT_PATH}"
    
    # Run tests
    test_successful_connection
    test_audio_switching
    test_mac_address_conversion
    test_correct_user
    test_sink_name
    test_audio_user_override
    test_custom_mac
    test_invalid_audio_user
    
    # Print summary
    echo ""
    echo "======================================"
    echo "Test Summary"
    echo "======================================"
    echo "Tests run:    ${TESTS_RUN}"
    echo -e "Tests passed: ${GREEN}${TESTS_PASSED}${NC}"
    if [ ${TESTS_FAILED} -gt 0 ]; then
        echo -e "Tests failed: ${RED}${TESTS_FAILED}${NC}"
        exit 1
    else
        echo -e "Tests failed: ${TESTS_FAILED}"
        echo ""
        echo -e "${GREEN}All tests passed!${NC}"
        exit 0
    fi
}

# Run main function
main "$@"
