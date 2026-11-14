"""Isolated fakes: no Bluetooth stack, no PulseAudio, no broker, no root."""

from __future__ import annotations

import os
import pwd
import stat
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pytest

from orpheus_audio_output.commands import CommandResult, RunAs

ADDRESS = "AA:BB:CC:DD:EE:FF"
SINK = "bluez_sink.AA_BB_CC_DD_EE_FF.a2dp_sink"


class FakeRunner:
    """Dispatches commands to per-binary handlers and records every call."""

    def __init__(self, **handlers: Callable[[list[str]], CommandResult]) -> None:
        self.handlers = handlers
        self.calls: list[tuple[list[str], Optional[RunAs], Optional[dict]]] = []

    def run(self, argv, *, timeout, run_as=None, env=None):  # noqa: ARG002
        argv = list(argv)
        self.calls.append((argv, run_as, dict(env) if env else None))
        return self.handlers[os.path.basename(argv[0])](argv[1:])

    def argvs(self, binary: str) -> list[list[str]]:
        return [a[1:] for a, _, _ in self.calls if os.path.basename(a[0]) == binary]


@dataclass
class BluetoothWorld:
    """A BlueZ stand-in: controller, one device, and how connects behave."""

    controller: str = "up"  # up | absent | hang
    device: str = "disconnected"  # connected | disconnected | unpaired | unknown
    connect_mode: str = "ok"  # ok | ok_after_scan | fail:<reason>
    scanned: bool = False
    log: list[str] = field(default_factory=list)

    def __call__(self, args: list[str]) -> CommandResult:
        self.log.append(" ".join(args))
        if self.controller == "hang":
            return CommandResult(124, "", timed_out=True)
        if self.controller == "absent":
            return CommandResult(1, "No default controller available\n")
        if args[:1] == ["--timeout"]:
            args = args[2:]
        cmd = args[0]
        if cmd == "info":
            if self.device == "unknown":
                return CommandResult(1, f"Device {args[1]} not available\n")
            paired = "no" if self.device == "unpaired" else "yes"
            connected = "yes" if self.device == "connected" else "no"
            return CommandResult(
                0,
                f"Device {args[1]}\n\tPaired: {paired}\n\tTrusted: yes\n\tConnected: {connected}\n",
            )
        if cmd == "connect":
            mode = self.connect_mode
            if mode == "ok_after_scan":
                mode = "ok" if self.scanned else "fail:org.bluez.Error.Failed"
            if mode == "ok":
                self.device = "connected"
                return CommandResult(0, "Attempting to connect\nConnection successful\n")
            return CommandResult(1, f"Attempting to connect\nFailed to connect: {mode[5:]}\n")
        if cmd == "scan":
            self.scanned = True
            return CommandResult(0, "Discovery started\n")
        if cmd == "trust":
            return CommandResult(0, "trust succeeded\n")
        return CommandResult(1, "Invalid command\n")


@dataclass
class PulseWorld:
    """A pactl stand-in for one server."""

    running: bool = True
    sinks: list[str] = field(default_factory=list)
    default: str = "auto_null"
    modules: list[str] = field(
        default_factory=lambda: [
            "module-native-protocol-unix",
            "module-bluetooth-policy",
            "module-bluetooth-discover",
        ]
    )
    inputs: list[int] = field(default_factory=list)
    fail_set_default: bool = False
    moved: list[tuple[str, str]] = field(default_factory=list)

    def __call__(self, args: list[str]) -> CommandResult:
        if not self.running:
            return CommandResult(1, "Connection failure: Connection refused\n")
        if args == ["info"]:
            return CommandResult(0, f"Server Name: pulseaudio\nDefault Sink: {self.default}\n")
        if args == ["list", "short", "sinks"]:
            rows = [
                f"{i}\t{s}\tmodule-bluez5-device.c\ts16le 2ch 44100Hz\tIDLE"
                for i, s in enumerate(self.sinks)
            ]
            return CommandResult(0, "\n".join(rows) + ("\n" if rows else ""))
        if args == ["list", "short", "modules"]:
            return CommandResult(0, "".join(f"{i}\t{m}\t\t\n" for i, m in enumerate(self.modules)))
        if args == ["list", "short", "sink-inputs"]:
            return CommandResult(0, "".join(f"{i}\t0\t-\tfloat32le\n" for i in self.inputs))
        if args[:1] == ["set-default-sink"]:
            if self.fail_set_default:
                return CommandResult(1, "Failure: No such entity\n")
            self.default = args[1]
            return CommandResult(0, "")
        if args[:1] == ["move-sink-input"]:
            self.moved.append((args[1], args[2]))
            return CommandResult(0, "")
        return CommandResult(1, f"unexpected pactl {args}\n")


@pytest.fixture
def me() -> RunAs:
    entry = pwd.getpwuid(os.geteuid())
    return RunAs(user=entry.pw_name, uid=entry.pw_uid, gid=entry.pw_gid, home=entry.pw_dir)


def _executable(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(body))
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def fake_pulse_bins(tmp_path: Path):
    """Real executables standing in for pulseaudio/pactl.

    ``pulseaudio`` binds the socket at $XDG_RUNTIME_DIR/pulse/native and serves
    until SIGTERM (mode file: ok | exit1 | silent). ``pactl info`` succeeds only
    if that socket accepts a connection. Records each start in ``starts``.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    mode = tmp_path / "pa-mode"
    mode.write_text("ok")
    starts = tmp_path / "starts"
    _executable(
        bindir / "pulseaudio",
        f"""
        import os, signal, socket, sys, time
        with open({str(starts)!r}, "a") as f:
            f.write(" ".join(sys.argv[1:]) + "\\n")
        mode = open({str(mode)!r}).read().strip()
        if mode == "exit1":
            sys.exit(1)
        if mode == "silent":
            signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
            while True:
                time.sleep(1)
        path = os.path.join(os.environ["XDG_RUNTIME_DIR"], "pulse", "native")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            os.unlink(path)
        s = socket.socket(socket.AF_UNIX)
        s.bind(path)
        s.listen(8)
        def bye(*_a):
            try:
                os.unlink(path)
            finally:
                sys.exit(0)
        signal.signal(signal.SIGTERM, bye)
        while True:
            c, _ = s.accept()
            c.close()
        """,
    )
    _executable(
        bindir / "pactl",
        """
        import os, socket, sys
        path = os.environ["PULSE_SERVER"].split("unix:", 1)[1]
        s = socket.socket(socket.AF_UNIX)
        try:
            s.connect(path)
        except OSError:
            print("Connection failure: Connection refused")
            sys.exit(1)
        if sys.argv[1:] == ["info"]:
            print("Server Name: fake\\nDefault Sink: auto_null")
        elif sys.argv[1:] == ["list", "short", "modules"]:
            print("0\\tmodule-native-protocol-unix\\t\\t")
        """,
    )
    return {"bin": bindir, "mode": mode, "starts": starts}
