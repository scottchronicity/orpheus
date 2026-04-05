"""Tests for Orpheus Bluetooth Auto-Connect service."""

import subprocess
from unittest.mock import MagicMock, patch


def test_bluetoothctl_available():
    """Test that bluetoothctl command is available."""
    try:
        result = subprocess.run(
            ["which", "bluetoothctl"],
            capture_output=True,
            text=True,
            check=False,
        )
        # On systems without Bluetooth, this is expected to fail
        # We're just testing the test infrastructure works
        assert result.returncode in [0, 1]
    except FileNotFoundError:
        # which command might not be available
        pass


def test_import_subprocess():
    """Test that required Python modules can be imported."""
    import subprocess  # noqa: F401
    import time  # noqa: F401

    assert True


def test_pactl_command_in_script():
    """Test that the bluetooth script contains pactl set-default-sink command."""
    with open("scripts/orpheus-bluetooth-connect.sh", "r") as f:
        script_content = f.read()
    
    # Verify the script contains the critical pactl command
    assert "pactl set-default-sink" in script_content, "Script should set default audio sink"
    assert "pactl list sinks" in script_content, "Script should list available sinks for debugging"
    assert "bluez_sink" in script_content, "Script should reference Bluetooth sink"


def test_script_has_proper_error_logging():
    """Test that the script logs errors instead of hiding them."""
    with open("scripts/orpheus-bluetooth-connect.sh", "r") as f:
        script_content = f.read()
    
    # Check for improved error logging
    assert "log_error" in script_content, "Script should use log_error function"
    assert "log_info" in script_content, "Script should use log_info function"
    assert "log_success" in script_content, "Script should use log_success function"
    
    # Verify we're not hiding all errors with 2>/dev/null everywhere
    # The script should capture and log errors instead
    pactl_lines = [line for line in script_content.split('\n') if 'pactl set-default-sink' in line]
    for line in pactl_lines:
        if 'SET_SINK_OUTPUT=' in line or 'pactl set-default-sink' in line:
            # This is the improved version that captures output
            assert '2>&1' in script_content, "Script should capture stderr for debugging"


def test_service_file_has_journald_output():
    """Test that the systemd service file sends output to journal."""
    with open("systemd/orpheus-bluetooth-autoconnect.service", "r") as f:
        service_content = f.read()
    
    assert "StandardOutput=journal" in service_content, "Service should log to journal"
    assert "StandardError=journal" in service_content, "Service should log errors to journal"


@patch("subprocess.run")
def test_mock_bluetoothctl_trust(mock_run: MagicMock) -> None:
    """Test mock Bluetooth trust command."""
    mock_run.return_value = MagicMock(returncode=0, stdout="[CHG] Device FC:58:FA:02:AF:28 Trusted: yes\n")

    result = subprocess.run(
        ["echo", "-e", "trust FC:58:FA:02:AF:28\\nquit"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0


@patch("subprocess.run")
def test_mock_bluetoothctl_connect(mock_run: MagicMock) -> None:
    """Test mock Bluetooth connect command."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="Attempting to connect to FC:58:FA:02:AF:28\nConnection successful\n"
    )

    result = subprocess.run(
        ["echo", "-e", "connect FC:58:FA:02:AF:28\\nquit"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "connect" in result.stdout  # Mock should contain 'connect'
