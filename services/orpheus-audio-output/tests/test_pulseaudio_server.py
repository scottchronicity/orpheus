"""PulseAudioServer: capture isolation, lifecycle with a real child process, routing."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from conftest import ADDRESS, SINK, FakeRunner, PulseWorld

from orpheus_audio_output.commands import CommandRunner
from orpheus_audio_output.outputs import BLUETOOTH_A2DP, Endpoint
from orpheus_audio_output.servers import (
    FAILED,
    READY,
    PulseAudioServer,
    pulseaudio_script,
)

ALSA = (
    "module-alsa-card",
    "module-alsa-sink",
    "module-alsa-source",
    "module-udev-detect",
    "module-detect",
)


# -- capture isolation --------------------------------------------------------
def test_managed_script_loads_no_alsa_or_udev_module():
    script = pulseaudio_script(frozenset({BLUETOOTH_A2DP}))
    loaded = [line.split()[1] for line in script.splitlines() if line.startswith("load-module")]
    assert loaded == [
        "module-native-protocol-unix",
        "module-bluetooth-policy",
        "module-bluetooth-discover",
    ]
    assert not any(m.startswith(ALSA) for m in loaded)
    assert ".fail" in script  # a broken module aborts startup instead of half-starting


def test_bluetooth_modules_only_when_an_output_needs_them():
    loaded = [
        ln.split()[1]
        for ln in pulseaudio_script(frozenset()).splitlines()
        if ln.startswith("load-module")
    ]
    assert loaded == ["module-native-protocol-unix"]


def _fake_proc(root: Path, pid: int, uid: int, fds: list[str]) -> None:
    d = root / str(pid)
    (d / "fd").mkdir(parents=True)
    (d / "comm").write_text("pulseaudio\n")
    (d / "status").write_text(f"Name:\tpulseaudio\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
    for i, target in enumerate(fds):
        os.symlink(target, d / "fd" / str(i))


def test_isolation_flags_alsa_modules_on_the_server(me, tmp_path):
    world = PulseWorld(
        modules=["module-native-protocol-unix", "module-udev-detect", "module-alsa-card"]
    )
    runtime = tmp_path / "run"
    (runtime / str(me.uid) / "pulse").mkdir(parents=True)
    (runtime / str(me.uid) / "pulse" / "native").touch()
    server = PulseAudioServer(
        me.user,
        frozenset({BLUETOOTH_A2DP}),
        FakeRunner(pactl=world),
        runtime_root=runtime,
        proc_root=tmp_path / "proc",
        resolve_user=lambda _u: me,
    )
    assert server.isolation_violations() == [
        "PulseAudio loaded module-udev-detect",
        "PulseAudio loaded module-alsa-card",
    ]


def test_other_pulseaudio_processes_holding_sound_devices_are_reported(me, tmp_path):
    proc = tmp_path / "proc"
    _fake_proc(proc, 4242, 1000, ["/dev/snd/pcmC1D0c", "/dev/snd/controlC1", "/dev/null"])
    _fake_proc(proc, 4343, 1001, ["/dev/null"])
    server = PulseAudioServer(
        me.user, frozenset(), FakeRunner(), proc_root=proc, resolve_user=lambda _u: me
    )
    others = sorted(server.other_servers(), key=lambda o: o["pid"])
    assert others[0] == {
        "pid": 4242,
        "uid": 1000,
        "alsa_devices": ["/dev/snd/controlC1", "/dev/snd/pcmC1D0c"],
    }
    assert others[1] == {"pid": 4343, "uid": 1001}


# -- lifecycle with a real child ----------------------------------------------
@pytest.fixture
def real_server(me, tmp_path, fake_pulse_bins):
    servers = []

    def make(**kw):
        server = PulseAudioServer(
            me.user,
            frozenset({BLUETOOTH_A2DP}),
            CommandRunner(),
            pulseaudio_bin=str(fake_pulse_bins["bin"] / "pulseaudio"),
            pactl_bin=str(fake_pulse_bins["bin"] / "pactl"),
            runtime_root=tmp_path / "run",
            script_dir=tmp_path / "script",
            proc_root=tmp_path / "noproc",
            startup_timeout=kw.pop("startup_timeout", 5.0),
            resolve_user=lambda _u: me,
            **kw,
        )
        servers.append(server)
        return server

    yield make
    for s in servers:
        s.stop()


def test_starts_a_managed_server_with_the_generated_script(real_server, fake_pulse_bins, tmp_path):
    server = real_server()
    state = server.ensure()
    assert state.state == READY and state.managed is True and state.pid
    args = fake_pulse_bins["starts"].read_text()
    assert "--daemonize=no" in args and "-n -F" in args and "--disallow-exit=yes" in args
    assert "module-udev-detect" not in (tmp_path / "script" / "pulseaudio.pa").read_text()
    # Healthy checks do not restart it.
    assert server.ensure().pid == state.pid
    assert server.starts == 1


def test_recovers_after_the_server_is_killed(real_server):
    server = real_server()
    first = server.ensure()
    os.kill(first.pid, signal.SIGKILL)
    for _ in range(50):
        if server.managed_pid is None:
            break
        time.sleep(0.05)
    again = server.ensure()
    assert again.state == READY and again.managed is True
    assert again.pid != first.pid
    assert server.starts == 2


def test_adopts_a_server_already_running_for_the_user(real_server, fake_pulse_bins, me, tmp_path):
    env = dict(os.environ, XDG_RUNTIME_DIR=str(tmp_path / "run" / str(me.uid)))
    (tmp_path / "run" / str(me.uid)).mkdir(parents=True)
    other = subprocess.Popen([str(fake_pulse_bins["bin"] / "pulseaudio")], env=env)
    try:
        sock = tmp_path / "run" / str(me.uid) / "pulse" / "native"
        for _ in range(100):
            if sock.exists():
                break
            time.sleep(0.05)
        server = real_server()
        state = server.ensure()
        assert state.state == READY and state.managed is False
        assert server.starts == 0
        server.stop()  # never stops a server it does not own
        assert other.poll() is None
    finally:
        other.terminate()
        other.wait(5)


def test_startup_failure_is_reported_not_raised(real_server, fake_pulse_bins):
    fake_pulse_bins["mode"].write_text("exit1")
    state = real_server().ensure()
    assert state.state == FAILED and "exited during startup with code 1" in state.detail


def test_a_server_that_never_answers_is_stopped(real_server, fake_pulse_bins):
    fake_pulse_bins["mode"].write_text("silent")
    server = real_server(startup_timeout=1.0)
    state = server.ensure()
    assert state.state == FAILED and "did not answer" in state.detail
    assert server.managed_pid is None


def test_missing_runtime_directory_is_created(real_server, me, tmp_path):
    server = real_server()
    assert not (tmp_path / "run" / str(me.uid)).exists()
    assert server.ensure().ready
    assert any("created missing runtime directory" in n for n in server.notes)


def test_unknown_user_fails_clearly(tmp_path):
    def nobody(_u):
        raise KeyError(_u)

    server = PulseAudioServer("ghost", frozenset(), FakeRunner(), resolve_user=nobody)
    assert server.ensure().detail == "user 'ghost' does not exist"


# -- routing ------------------------------------------------------------------
@pytest.fixture
def routed(me, tmp_path):
    world = PulseWorld(sinks=["auto_null", SINK, "bluez_sink.11_22_33_44_55_66.a2dp_sink"])
    runner = FakeRunner(pactl=world)
    server = PulseAudioServer(
        me.user,
        frozenset({BLUETOOTH_A2DP}),
        runner,
        runtime_root=tmp_path,
        resolve_user=lambda _u: me,
    )
    return server, world, runner


def test_finds_the_sink_for_this_speaker_only(routed):
    server, _, _ = routed
    assert server.find_sink(Endpoint("bluetooth", ADDRESS)) == SINK
    assert server.find_sink(Endpoint("bluetooth", "00:00:00:00:00:01")) is None


def test_routes_default_sink_and_moves_playing_streams(routed):
    server, world, runner = routed
    world.inputs = [7, 9]
    ok, detail = server.route_to(SINK)
    assert ok and world.default == SINK and server.default_sink() == SINK
    assert world.moved == [("7", SINK), ("9", SINK)]
    assert "moved 2 stream(s)" in detail
    # pactl always targets this user's socket explicitly (never autospawns).
    env = runner.calls[0][2]
    assert env["PULSE_SERVER"].endswith("/pulse/native") and env["XDG_RUNTIME_DIR"]


def test_route_failure_is_reported(routed):
    server, world, _ = routed
    world.fail_set_default = True
    ok, detail = server.route_to(SINK)
    assert not ok and "No such entity" in detail
