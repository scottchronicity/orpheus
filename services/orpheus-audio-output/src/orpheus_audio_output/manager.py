"""Output readiness lifecycle: server up, output established, playback routed.

The manager does not choose or play sounds (the playback agent does). It keeps
the configured output ready: the audio server running, the output device
established, and the server's default sink pointing at the output, recovering
each independently under the reconnect policy.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .config import AudioOutputConfig
from .outputs import OutputDevice, OutputState
from .policy import Backoff, LogThrottle
from .servers import FAILED, ISOLATION_VIOLATION, STOPPED, AudioServer, ServerState

# A connected output whose sink has not appeared on the server after this many
# polls is reported, with the likely cause (another audio server owns it).
SINK_GRACE_POLLS = 3


class OutputManager:
    def __init__(
        self,
        config: AudioOutputConfig,
        output: OutputDevice,
        server: AudioServer,
        log: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.output = output
        self.server = server
        self.log = log
        self.clock = clock
        self.server_backoff = Backoff(config.reconnect)
        self.output_backoff = Backoff(config.reconnect)
        self.server_state = ServerState(STOPPED)
        self.output_state = OutputState("unknown")
        self.route_state = "not_ready"
        self.route_detail = ""
        self.routed_sink: Optional[str] = None
        self.isolation_problems: list[str] = []
        self.other_servers: list[dict] = []
        self.counters = {"output_reconnects": 0, "server_recoveries": 0, "routes": 0}
        self._ever_connected = False
        self._server_starts = 0
        self._sink_missing_polls = 0
        self._throttle = LogThrottle()

    # -- logging ----------------------------------------------------------
    def _transition(self, what: str, old: str, new: str, detail: str = "") -> None:
        if old != new:
            self.log.info(f"{what} state changed", old=old, new=new, detail=detail or None)
            self._throttle.clear(what)

    def _failure(self, what: str, message: str, retry_in: Optional[float]) -> None:
        now = self.clock()
        emit, suppressed = self._throttle.should_log(what, message, now)
        if emit:
            self.log.warning(
                f"{what} not ready",
                reason=message,
                retry_in_seconds=retry_in,
                repeats_suppressed=suppressed or None,
            )

    # -- lifecycle --------------------------------------------------------
    def start(self) -> None:
        self.log.info(
            "Audio output manager starting",
            output=self.output.describe(),
            server=self.server.describe(),
            reconnect=vars(self.config.reconnect),
            config_source=self.config.source,
        )
        self.output.startup()
        trusted = getattr(self.output, "trusted_at_startup", None)
        if trusted is False:
            self.log.warning("Could not trust the output device at startup; continuing")

    def stop(self) -> None:
        self.server.stop()

    def tick(self) -> float:
        """One supervision pass. Returns seconds until the next pass."""
        self._tick_server()
        self._tick_isolation()
        self._tick_output()
        self._tick_routing()
        return self.config.reconnect.initial_delay_seconds

    def _tick_server(self) -> None:
        now = self.clock()
        if not (self.server_state.ready or self.server_backoff.due(now)):
            return
        before = self.server_state
        state = self.server.ensure()
        self.server_state = state
        self._transition("server", before.state, state.state, state.detail)
        # A dead server is usually restarted inside one ensure() call, so count
        # recoveries from the server's own start counter, not state changes.
        starts = getattr(self.server, "starts", 0) or 0
        if self._server_starts and starts > self._server_starts:
            self.counters["server_recoveries"] += starts - self._server_starts
        self._server_starts = max(self._server_starts, starts)
        if state.ready:
            self.server_backoff.success(now)
        else:
            wait = self.server_backoff.failure(now)
            self._failure("server", state.detail, wait if self.config.reconnect.enabled else None)
        notes = getattr(self.server, "notes", None)
        while notes:
            self.log.info("server note", detail=notes.pop(0))

    def _tick_isolation(self) -> None:
        problems = self.server.isolation_violations() if self.server_state.ready else []
        other = getattr(self.server, "other_servers", lambda: [])()
        if problems and self.server_state.managed:
            # Never let the managed server keep an ALSA device: stop it and
            # retry under backoff with the same Bluetooth-only configuration.
            self.log.error("Capture isolation violated; stopping managed server", problems=problems)
            self.server.restart("capture isolation violated")
            self.server_state = ServerState(ISOLATION_VIOLATION, "; ".join(problems))
            self.server_backoff.failure(self.clock())
        elif problems and problems != self.isolation_problems:
            self.log.error(
                "An audio server this manager does not own may hold the capture interface",
                problems=problems,
            )
        foreign_alsa = [o for o in other if o.get("alsa_devices")]
        if foreign_alsa and foreign_alsa != [
            o for o in self.other_servers if o.get("alsa_devices")
        ]:
            self.log.error(
                "Another PulseAudio process has ALSA devices open (possible capture conflict)",
                servers=foreign_alsa,
            )
        self.isolation_problems = problems
        self.other_servers = other

    def _tick_output(self) -> None:
        now = self.clock()
        before = self.output_state
        state = self.output.probe()
        if not state.connected and self.output_backoff.due(now):
            # Not gated on our server: another user's audio server may provide
            # the A2DP endpoint, and the attempt itself is cheap and bounded.
            state = self.output.establish()
            if state.connected:
                self.output_backoff.success(now)
                if self._ever_connected:
                    self.counters["output_reconnects"] += 1
            else:
                wait = self.output_backoff.failure(now)
                hint = ""
                if not self.server_state.ready:
                    hint = " (no audio server is ready here; a speaker needs one to accept A2DP)"
                self._failure(
                    "output",
                    f"{state.state}: {state.detail}{hint}",
                    wait if self.config.reconnect.enabled else None,
                )
        elif state.connected:
            self.output_backoff.success(now)
        if state.connected:
            self._ever_connected = True
        self.output_state = state
        self._transition("output", before.state, state.state, state.detail)

    def _tick_routing(self) -> None:
        before = self.route_state
        if not (self.output_state.connected and self.server_state.ready):
            self.route_state, self.route_detail = "not_ready", ""
            self.routed_sink = None
            self._sink_missing_polls = 0
            self._transition("routing", before, self.route_state)
            return
        sink = self.server.find_sink(self.output.endpoint())
        if sink is None:
            self._sink_missing_polls += 1
            self.route_state = "waiting_for_sink"
            self.route_detail = "output connected; its sink has not appeared on the server yet"
            if self._sink_missing_polls >= SINK_GRACE_POLLS:
                self.route_detail = (
                    "output connected but the server has no sink for it; another audio "
                    "server may hold the A2DP endpoint"
                )
                self._failure("routing", self.route_detail, None)
            self._transition("routing", before, self.route_state, self.route_detail)
            return
        self._sink_missing_polls = 0
        if self.routed_sink != sink or self.server.default_sink() != sink:
            ok, detail = self.server.route_to(sink)
            if not ok:
                self.route_state, self.route_detail = "route_failed", detail
                self.routed_sink = None
                self._failure("routing", detail, self.config.reconnect.initial_delay_seconds)
                self._transition("routing", before, self.route_state, detail)
                return
            self.counters["routes"] += 1
            self.routed_sink = sink
            self.route_detail = detail
        self.route_state = "routed"
        self._transition("routing", before, self.route_state, self.route_detail)

    # -- health -----------------------------------------------------------
    @property
    def ready(self) -> bool:
        return self.route_state == "routed"

    def health(self) -> dict:
        if self.isolation_problems or self.server_state.state in (FAILED, ISOLATION_VIOLATION):
            status = "unhealthy"
        elif self.ready:
            status = "healthy"
        else:
            status = "degraded"
        now = self.clock()

        def retry_in(b: Backoff) -> Optional[float]:
            if b.failures == 0 or not self.config.reconnect.enabled:
                return None
            return max(0.0, round(b.next_attempt - now, 1))

        return {
            "status": status,
            "ready": self.ready,
            "output": {
                **self.output.describe(),
                "state": self.output_state.state,
                "detail": self.output_state.detail or None,
                "consecutive_failures": self.output_backoff.failures,
                "retry_in_seconds": retry_in(self.output_backoff),
            },
            "server": {
                **self.server.describe(),
                "state": self.server_state.state,
                "detail": self.server_state.detail or None,
                "managed": self.server_state.managed,
                "consecutive_failures": self.server_backoff.failures,
                "retry_in_seconds": retry_in(self.server_backoff),
            },
            "routing": {
                "state": self.route_state,
                "sink": self.routed_sink,
                "detail": self.route_detail or None,
            },
            "capture_isolation": {
                "ok": not self.isolation_problems
                and not any(o.get("alsa_devices") for o in self.other_servers),
                "problems": self.isolation_problems,
                "other_audio_servers": self.other_servers,
            },
            "counters": dict(self.counters),
            "reconnect": vars(self.config.reconnect),
            "config_source": self.config.source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
