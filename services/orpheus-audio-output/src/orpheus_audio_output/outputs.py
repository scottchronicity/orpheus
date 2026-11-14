"""Output devices: what the speaker is and how to establish it.

An output implementation knows nothing about the audio server. It reports its
state, establishes itself, and describes itself as an ``Endpoint`` that a
server can map to one of its sinks. ``requires`` names the server capabilities
it depends on, so incompatible output/server choices fail at startup.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, FrozenSet, Optional

from .commands import CommandResult, CommandRunner
from .config import AudioOutputConfig, AudioOutputConfigError

# Output states, shared by all output implementations.
CONNECTED = "connected"
DISCONNECTED = "disconnected"
UNPAIRED = "unpaired"  # known to the stack but not paired
MISSING = "missing"  # not known to the stack at all
NO_CONTROLLER = "no_controller"  # no adapter
UNAVAILABLE = "unavailable"  # the stack did not answer

# Capability a Bluetooth A2DP output needs from the audio server.
BLUETOOTH_A2DP = "bluetooth-a2dp"


@dataclass(frozen=True)
class Endpoint:
    """What a server needs to find this output's sink."""

    kind: str
    address: str


@dataclass(frozen=True)
class OutputState:
    state: str
    detail: str = ""

    @property
    def connected(self) -> bool:
        return self.state == CONNECTED


class OutputDevice:
    """Implementation boundary for output devices (Bluetooth now; wired/network later)."""

    type: str = ""
    requires: FrozenSet[str] = frozenset()

    def startup(self) -> None:  # pragma: no cover - interface
        """One-time preparation when the manager starts."""

    def probe(self) -> OutputState:  # pragma: no cover - interface
        raise NotImplementedError

    def establish(self) -> OutputState:  # pragma: no cover - interface
        """Try to bring the output up; returns the state afterwards."""
        raise NotImplementedError

    def endpoint(self) -> Endpoint:  # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


class BluetoothOutput(OutputDevice):
    """A paired Bluetooth speaker, driven with ``bluetoothctl`` in argument mode.

    The connect sequence is the one the retired autoconnect service used on the
    field station: trust once at startup; connect; on failure scan briefly to
    refresh the controller cache and connect once more.
    """

    type = "bluetooth"
    requires = frozenset({BLUETOOTH_A2DP})

    def __init__(
        self,
        address: str,
        runner: Optional[CommandRunner] = None,
        *,
        bluetoothctl: str = "bluetoothctl",
        command_timeout: float = 15.0,
        connect_timeout: float = 45.0,
        scan_seconds: int = 10,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.address = address
        self._runner = runner or CommandRunner()
        self._bin = bluetoothctl
        self._command_timeout = command_timeout
        self._connect_timeout = connect_timeout
        self._scan_seconds = scan_seconds
        self._sleep = sleep
        self.trusted_at_startup: Optional[bool] = None

    def _bt(self, *args: str, timeout: Optional[float] = None) -> CommandResult:
        return self._runner.run([self._bin, *args], timeout=timeout or self._command_timeout)

    def startup(self) -> None:
        self.trusted_at_startup = self._bt("trust", self.address).ok

    def probe(self) -> OutputState:
        result = self._bt("info", self.address)
        return _classify_info(result, self._command_timeout)

    def establish(self) -> OutputState:
        first = self._bt("connect", self.address, timeout=self._connect_timeout)
        state = self.probe()
        if state.connected or state.state in (NO_CONTROLLER, UNAVAILABLE):
            return state
        self._bt(
            "--timeout",
            str(self._scan_seconds),
            "scan",
            "on",
            timeout=self._scan_seconds + 5,
        )
        self._sleep(2)
        second = self._bt("connect", self.address, timeout=self._connect_timeout)
        state = self.probe()
        if state.connected:
            return state
        reason = _connect_reason(second) or _connect_reason(first) or state.detail
        return OutputState(state.state, reason)

    def endpoint(self) -> Endpoint:
        return Endpoint(kind="bluetooth", address=self.address)

    def describe(self) -> dict:
        return {"type": self.type, "address": self.address}


def _classify_info(result: CommandResult, timeout: float) -> OutputState:
    text = result.output
    if result.timed_out:
        return OutputState(UNAVAILABLE, f"bluetoothctl timed out after {timeout:g}s")
    if "No default controller available" in text:
        return OutputState(NO_CONTROLLER, "no Bluetooth controller")
    if "Connected: yes" in text:
        return OutputState(CONNECTED)
    if "Paired: no" in text:
        return OutputState(UNPAIRED, "device is known but not paired")
    if "Connected: no" in text:
        return OutputState(DISCONNECTED)
    if "not available" in text:
        return OutputState(MISSING, "device is not known to BlueZ")
    return OutputState(
        UNAVAILABLE, f"bluetoothctl exited {result.returncode}: {text.strip()[:200]}"
    )


def _connect_reason(result: CommandResult) -> str:
    for line in result.output.splitlines():
        if "Failed to connect" in line or "Error" in line or "not available" in line:
            return line.strip()
    return ""


def build_output(config: AudioOutputConfig, runner: Optional[CommandRunner] = None) -> OutputDevice:
    if config.output.type == "bluetooth":
        assert config.output.bluetooth is not None
        return BluetoothOutput(config.output.bluetooth.address, runner)
    raise AudioOutputConfigError(f"unsupported output type {config.output.type!r}")
