"""BluetoothOutput: state probing and the field-proven connect sequence."""

from __future__ import annotations

import sys

from conftest import ADDRESS, BluetoothWorld, FakeRunner

from orpheus_audio_output.commands import CommandRunner
from orpheus_audio_output.outputs import (
    BLUETOOTH_A2DP,
    CONNECTED,
    DISCONNECTED,
    MISSING,
    NO_CONTROLLER,
    UNAVAILABLE,
    UNPAIRED,
    BluetoothOutput,
)


def make(world: BluetoothWorld):
    runner = FakeRunner(bluetoothctl=world)
    return BluetoothOutput(ADDRESS, runner, sleep=lambda _s: None), runner


def test_requires_a2dp_from_the_server():
    assert BluetoothOutput.requires == frozenset({BLUETOOTH_A2DP})


def test_probe_classifies_every_stack_state():
    cases = {
        ("up", "connected"): CONNECTED,
        ("up", "disconnected"): DISCONNECTED,
        ("up", "unpaired"): UNPAIRED,
        ("up", "unknown"): MISSING,
        ("absent", "disconnected"): NO_CONTROLLER,
        ("hang", "disconnected"): UNAVAILABLE,
    }
    for (controller, device), expected in cases.items():
        output, _ = make(BluetoothWorld(controller=controller, device=device))
        assert output.probe().state == expected, (controller, device)


def test_startup_trusts_the_device_once():
    output, runner = make(BluetoothWorld())
    output.startup()
    assert runner.argvs("bluetoothctl") == [["trust", ADDRESS]]
    assert output.trusted_at_startup is True


def test_establish_connects_directly_when_possible():
    output, runner = make(BluetoothWorld())
    assert output.establish().state == CONNECTED
    assert ["--timeout", "10", "scan", "on"] not in runner.argvs("bluetoothctl")


def test_establish_scans_and_retries_like_the_retired_service():
    world = BluetoothWorld(connect_mode="ok_after_scan")
    output, runner = make(world)
    assert output.establish().state == CONNECTED
    calls = [a[0] if a[0] != "--timeout" else "scan" for a in runner.argvs("bluetoothctl")]
    assert calls == ["connect", "info", "scan", "connect", "info"]


def test_failed_establish_reports_the_bluez_reason():
    output, _ = make(
        BluetoothWorld(connect_mode="fail:org.bluez.Error.Failed br-connection-page-timeout")
    )
    state = output.establish()
    assert state.state == DISCONNECTED
    assert "br-connection-page-timeout" in state.detail


def test_no_scan_when_the_stack_itself_is_down():
    output, runner = make(BluetoothWorld(controller="absent"))
    assert output.establish().state == NO_CONTROLLER
    assert not any("scan" in a for a in runner.argvs("bluetoothctl"))


def test_commands_never_read_stdin_and_are_bounded(tmp_path):
    """Interactive bluetoothctl grew an unbounded history file; the runner
    gives every command /dev/null as stdin and a hard timeout."""
    probe = tmp_path / "probe.py"
    probe.write_text("import sys; data = sys.stdin.read(); print(repr(data))")
    result = CommandRunner().run([sys.executable, str(probe)], timeout=5)
    assert result.ok and result.output.strip() == "''"

    slow = CommandRunner().run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert slow.timed_out and slow.returncode == 124

    missing = CommandRunner().run(["/nonexistent/bluetoothctl", "info"], timeout=1)
    assert missing.returncode == 127 and not missing.ok
