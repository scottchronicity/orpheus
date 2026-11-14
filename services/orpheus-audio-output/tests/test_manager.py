"""OutputManager lifecycle: establish, route, recover, back off, stay quiet."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest
from conftest import ADDRESS, SINK

from orpheus_audio_output.config import parse_audio_output
from orpheus_audio_output.manager import SINK_GRACE_POLLS, OutputManager
from orpheus_audio_output.outputs import (
    CONNECTED,
    DISCONNECTED,
    UNAVAILABLE,
    Endpoint,
    OutputDevice,
    OutputState,
)
from orpheus_audio_output.servers import (
    FAILED,
    ISOLATION_VIOLATION,
    READY,
    AudioServer,
    ServerState,
)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@dataclass
class FakeOutput(OutputDevice):
    state: str = DISCONNECTED
    connects_ok: bool = True
    attempts: int = 0
    started: bool = False
    type: str = "bluetooth"
    requires: frozenset = frozenset({"bluetooth-a2dp"})

    def startup(self):
        self.started = True

    def probe(self):
        if self.state == UNAVAILABLE:
            return OutputState(UNAVAILABLE, "bluetoothctl timed out after 15s")
        return OutputState(self.state)

    def establish(self):
        self.attempts += 1
        if self.state == UNAVAILABLE:
            return OutputState(UNAVAILABLE, "bluetoothctl timed out after 15s")
        if self.connects_ok:
            self.state = CONNECTED
            return OutputState(CONNECTED)
        return OutputState(DISCONNECTED, "Failed to connect: org.bluez.Error.Failed")

    resets: int = 0

    def reset(self):
        self.resets += 1
        self.state = DISCONNECTED

    def endpoint(self):
        return Endpoint("bluetooth", ADDRESS)

    def describe(self):
        return {"type": "bluetooth", "address": ADDRESS}


@dataclass
class FakeServer(AudioServer):
    up: bool = True
    managed: bool = True
    start_ok: bool = True
    sink_present: bool = True
    default: Optional[str] = None
    violations: list = field(default_factory=list)
    others: list = field(default_factory=list)
    ensures: int = 0
    starts: int = 0
    restarts: list = field(default_factory=list)
    routes: list = field(default_factory=list)
    stopped: bool = False
    notes: list = field(default_factory=list)
    type: str = "pulseaudio"
    capabilities: frozenset = frozenset({"bluetooth-a2dp"})

    def ensure(self):
        self.ensures += 1
        if not self.up:
            if not self.start_ok:
                return ServerState(FAILED, "PulseAudio exited during startup with code 1")
            self.up = True
            self.starts += 1
        return ServerState(READY, managed=self.managed, pid=4242 if self.managed else None)

    def find_sink(self, endpoint):
        return SINK if self.sink_present else None

    def default_sink(self):
        return self.default

    def route_to(self, sink):
        self.routes.append(sink)
        self.default = sink
        return True, f"default sink {sink}"

    def isolation_violations(self):
        return list(self.violations)

    def other_servers(self):
        return list(self.others)

    def restart(self, reason):
        self.restarts.append(reason)
        self.up = False

    def stop(self):
        self.stopped = True

    def describe(self):
        return {"type": "pulseaudio", "user": "orpheus"}

    def crash(self):
        self.up = False
        self.default = None  # a fresh server forgets the default sink


class Log:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str, dict]] = []

    def _add(self, level, msg, **kw):
        self.lines.append((level, msg, kw))

    def info(self, msg, **kw):
        self._add("info", msg, **kw)

    def warning(self, msg, **kw):
        self._add("warning", msg, **kw)

    def error(self, msg, **kw):
        self._add("error", msg, **kw)


def cfg(**reconnect):
    return parse_audio_output(
        {
            "output": {"bluetooth": {"address": ADDRESS}},
            "reconnect": {"initial_delay_seconds": 10, "max_delay_seconds": 60, **reconnect},
        }
    )


@pytest.fixture
def setup():
    def make(output=None, server=None, **reconnect):
        clock = Clock()
        output = output or FakeOutput()
        server = server or FakeServer(up=False)
        log = Log()
        manager = OutputManager(cfg(**reconnect), output, server, log, clock=clock)
        manager.start()
        return manager, output, server, clock, log

    return make


def run(manager, clock, ticks):
    for _ in range(ticks):
        wait = manager.tick()
        clock.advance(wait)


def test_cold_start_brings_up_server_output_and_routing(setup):
    manager, output, server, clock, _ = setup()
    assert output.started
    run(manager, clock, 1)
    assert server.starts == 1 and output.state == CONNECTED
    assert server.routes == [SINK] and manager.ready
    health = manager.health()
    assert health["status"] == "healthy"
    assert health["routing"] == {"state": "routed", "sink": SINK, "detail": f"default sink {SINK}"}


def test_steady_state_does_not_reconnect_reroute_or_log(setup):
    manager, output, server, clock, log = setup()
    run(manager, clock, 1)
    before = len(log.lines)
    run(manager, clock, 100)
    assert output.attempts == 1 and server.routes == [SINK]
    assert len(log.lines) == before


def test_speaker_drop_reconnects_and_reroutes(setup):
    manager, output, server, clock, _ = setup()
    run(manager, clock, 1)
    output.state = DISCONNECTED
    server.default = "auto_null"
    run(manager, clock, 1)
    assert output.state == CONNECTED and server.routes == [SINK, SINK]
    assert manager.counters["output_reconnects"] == 1 and manager.ready


def test_unavailable_speaker_backs_off_to_the_ceiling_then_recovers(setup):
    output = FakeOutput(connects_ok=False)
    manager, output, server, clock, _ = setup(output=output)
    attempt_times = []
    for _ in range(60):  # 10 minutes of 10 s polls
        before = output.attempts
        manager.tick()
        if output.attempts > before:
            attempt_times.append(clock.t)
        clock.advance(10)
    gaps = [b - a for a, b in zip(attempt_times, attempt_times[1:])]
    assert gaps[:4] == [10, 20, 40, 60]
    assert set(gaps[4:]) == {60}
    assert manager.health()["status"] == "degraded"
    assert manager.health()["output"]["consecutive_failures"] == len(attempt_times)
    output.connects_ok = True
    clock.advance(60)
    manager.tick()
    assert manager.ready and manager.output_backoff.failures == 0


def test_bluetooth_stack_unavailable_then_restarted(setup):
    output = FakeOutput(state=UNAVAILABLE)
    manager, output, server, clock, _ = setup(output=output)
    run(manager, clock, 3)
    assert not manager.ready
    assert "timed out" in manager.health()["output"]["detail"]
    output.state = DISCONNECTED  # bluetooth.service is back
    run(manager, clock, 8)
    assert manager.ready


def test_server_termination_restarts_it_and_reroutes(setup):
    manager, output, server, clock, _ = setup()
    run(manager, clock, 1)
    server.crash()
    run(manager, clock, 1)
    assert server.starts == 2 and server.default == SINK
    assert server.routes == [SINK, SINK]
    assert manager.counters["server_recoveries"] == 1


def test_server_start_failures_back_off_and_do_not_block_the_output(setup):
    server = FakeServer(up=False, start_ok=False)
    manager, output, server, clock, _ = setup(server=server)
    run(manager, clock, 12)  # polls at 0..110 s
    assert server.ensures == 4  # attempts at 0, 10, 30 and 70 s (next due at 130 s)
    # The connection is still attempted: another user's server may provide A2DP.
    assert output.state == CONNECTED
    assert manager.health()["status"] == "unhealthy"
    assert manager.health()["routing"]["state"] == "not_ready"


def test_reboot_is_a_cold_start(setup):
    first, *_ = setup()
    # A new manager process sees whatever state the host comes up in.
    manager, output, server, clock, _ = setup(
        output=FakeOutput(state=DISCONNECTED), server=FakeServer(up=False)
    )
    run(manager, clock, 1)
    assert manager.ready and server.starts == 1


def test_connected_but_sink_missing_is_reported_after_grace(setup):
    server = FakeServer(up=True, sink_present=False)
    manager, _, server, clock, log = setup(server=server)
    run(manager, clock, SINK_GRACE_POLLS)
    health = manager.health()
    assert health["routing"]["state"] == "waiting_for_sink"
    assert "another audio server may hold the A2DP endpoint" in health["routing"]["detail"]
    assert any(line[1] == "routing not ready" for line in log.lines)


def test_lost_sink_after_a_server_restart_reconnects_the_output(setup):
    manager, output, server, clock, _ = setup()
    run(manager, clock, 1)
    assert manager.ready
    # The server restarts; the link stays up but the new server has no sink.
    server.crash()
    server.sink_present = False
    run(manager, clock, SINK_GRACE_POLLS)
    assert output.resets == 1 and manager.counters["output_resets"] == 1
    # Reconnecting renegotiates A2DP with the new server: the sink appears.
    server.sink_present = True
    run(manager, clock, 3)
    assert manager.ready and server.default == SINK


def test_recovering_without_a_reroute_clears_the_stale_detail(setup):
    manager, _, server, clock, _ = setup()
    run(manager, clock, 1)
    server.sink_present = False
    run(manager, clock, SINK_GRACE_POLLS)
    assert "another audio server" in manager.health()["routing"]["detail"]
    server.sink_present = True  # same sink, still the default: no re-route
    run(manager, clock, 1)
    assert manager.health()["routing"] == {
        "state": "routed",
        "sink": SINK,
        "detail": f"default sink {SINK}",
    }


def test_a_sink_missing_without_a_server_restart_is_reported_not_fought(setup):
    # e.g. another user's audio server holds the A2DP endpoint
    server = FakeServer(up=True, sink_present=False)
    manager, output, server, clock, _ = setup(server=server)
    run(manager, clock, 60)
    assert output.resets == 0
    assert "another audio server may hold" in manager.health()["routing"]["detail"]


def test_one_reset_per_server_restart(setup):
    manager, output, server, clock, _ = setup()
    run(manager, clock, 1)
    server.crash()
    server.sink_present = False  # and it never comes back
    run(manager, clock, 60)
    assert output.resets == 1


def test_capture_isolation_violation_stops_the_managed_server(setup):
    server = FakeServer(up=True, violations=["PulseAudio loaded module-udev-detect"])
    manager, _, server, clock, log = setup(server=server)
    manager.tick()
    assert server.restarts == ["capture isolation violated"]
    assert manager.server_state.state == ISOLATION_VIOLATION
    assert manager.health()["status"] == "unhealthy"
    assert any(line[0] == "error" for line in log.lines)


def test_an_adopted_server_with_alsa_modules_is_flagged_not_killed(setup):
    server = FakeServer(up=True, managed=False, violations=["PulseAudio loaded module-udev-detect"])
    manager, _, server, clock, _ = setup(server=server)
    manager.tick()
    assert server.restarts == []
    health = manager.health()
    assert health["status"] == "unhealthy" and not health["capture_isolation"]["ok"]


def test_foreign_server_holding_sound_devices_is_visible(setup):
    others = [{"pid": 77, "uid": 1000, "alsa_devices": ["/dev/snd/pcmC1D0c"]}]
    manager, _, _, clock, log = setup(server=FakeServer(up=True, others=others))
    manager.tick()
    assert manager.health()["capture_isolation"]["other_audio_servers"] == others
    assert manager.health()["capture_isolation"]["ok"] is False
    assert any("Another PulseAudio" in line[1] for line in log.lines)


def test_reconnect_disabled_makes_one_attempt_only(setup):
    output = FakeOutput(connects_ok=False)
    manager, output, _, clock, _ = setup(output=output, enabled=False)
    run(manager, clock, 30)
    assert output.attempts == 1
    assert manager.health()["output"]["retry_in_seconds"] is None


def test_a_long_outage_stays_quiet_in_the_log(setup):
    output = FakeOutput(connects_ok=False)
    manager, _, _, clock, log = setup(output=output)
    run(manager, clock, 6 * 60 * 24)  # one day of 10 s polls
    warnings = [line for line in log.lines if line[0] == "warning"]
    # One line when it starts failing, then one every 10 minutes at most.
    assert len(warnings) <= 24 * 6 + 1
    assert warnings[-1][2]["repeats_suppressed"] >= 1


def test_stop_stops_the_server(setup):
    manager, _, server, clock, _ = setup()
    run(manager, clock, 1)
    manager.stop()
    assert server.stopped
