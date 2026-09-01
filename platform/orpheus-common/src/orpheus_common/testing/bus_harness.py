"""Behavior-focused e2e harness for testing agents over a REAL EventBus.

These helpers let a test stand up a real agent against a real broker (a local
``nats-server`` or the Simulacrum backplane) and assert on its OBSERVABLE bus
behavior — which subjects it subscribes to, what it publishes in response to a
stimulus, its health/heartbeat/shutdown messages. They deliberately assert the
*contract*, not the implementation, so the same tests stay green across a
refactor (e.g. extracting lifecycle boilerplate into an ``Actor`` base).

Import only from test code. Nothing here is used at runtime.

Design notes:
- Observation reuses the established ``test_event_bus_nats`` pattern: a callback
  that records ``(topic, payload)`` and a condition variable so a test can wait
  for the off-loop dispatch thread to deliver.
- ``AgentRunner`` runs an asyncio agent's ``start()``/``shutdown()`` in-process on
  a background thread+loop. Agents install signal handlers via
  ``loop.add_signal_handler``, which only works on the main thread — so the runner
  no-ops it and triggers graceful shutdown by setting the agent's ``stop_event``
  directly, which drives the SAME shutdown code path a real SIGTERM would.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable, List, Optional, Tuple

from orpheus_common.config import OrpheusConfig
from orpheus_common.event_bus import EventBus, create_event_bus

DEFAULT_NATS_URL = "nats://127.0.0.1:4222"


def nats_config(nats_url: str = DEFAULT_NATS_URL, **extra: Any) -> OrpheusConfig:
    """An ``OrpheusConfig`` wired to the NATS backend for e2e tests."""
    data: dict[str, Any] = {
        "mqtt": {"broker_host": "localhost"},
        "event_bus": {"backend": "nats", "nats_url": nats_url},
    }
    data.update(extra)
    return OrpheusConfig.from_dict(data, source="<e2e>")


def broker_reachable(nats_url: str = DEFAULT_NATS_URL, timeout: float = 2.0) -> bool:
    """True iff a NATS broker accepts a connection within ``timeout`` — use to
    ``pytest.skip`` when no broker is running (the established convention)."""
    from orpheus_common.event_bus_nats import NatsBus

    bus = NatsBus(nats_url, client_id="e2e-probe", connect_timeout=timeout)
    try:
        bus.connect()
    except Exception:
        return False
    bus.disconnect()
    return True


class Recorder:
    """Records ``(topic, payload)`` deliveries; ``wait_for(n)`` blocks until at
    least ``n`` have arrived (syncs with the off-loop dispatch thread)."""

    def __init__(self) -> None:
        self.items: List[Tuple[str, Any]] = []
        self._cv = threading.Condition()

    def __call__(self, topic: str, payload: Any) -> None:
        with self._cv:
            self.items.append((topic, payload))
            self._cv.notify_all()

    def wait_for(self, n: int, timeout: float = 5.0) -> bool:
        """Block until ``len(items) >= n`` or ``timeout``. Returns success."""
        end = time.monotonic() + timeout
        with self._cv:
            while len(self.items) < n:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(remaining)
            return True

    def wait_for_match(
        self, predicate: Callable[[Any], bool], timeout: float = 5.0
    ) -> bool:
        """Block until some recorded payload satisfies ``predicate``.

        ``wait_for(n)`` counts arrivals, so on a shared topic it returns on
        somebody else's message; a test that cares WHICH event arrived waits on
        the event itself."""
        end = time.monotonic() + timeout
        with self._cv:
            while not any(self._safe(predicate, p) for _, p in self.items):
                remaining = end - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(remaining)
            return True

    @staticmethod
    def _safe(predicate: Callable[[Any], bool], payload: Any) -> bool:
        # A predicate that trips over an unrelated payload shape means "not a
        # match", never a failed wait.
        try:
            return bool(predicate(payload))
        except Exception:
            return False

    def topics(self) -> List[str]:
        return [t for t, _ in self.items]

    def payloads_on(self, topic: str) -> List[Any]:
        return [p for t, p in self.items if t == topic]


class Observer:
    """A real bus subscribed to one or more topics, recording deliveries into a
    ``Recorder``. Use as a context manager so it connects/disconnects cleanly."""

    def __init__(
        self, nats_url: str, *topics: str, client_id: str = "e2e-observer"
    ) -> None:
        self.bus: EventBus = create_event_bus(nats_config(nats_url), client_id=client_id)
        self.rec = Recorder()
        self._topics = topics

    def __enter__(self) -> Observer:
        # Subscribe before connect (buffered, flushed on connect) so we can't miss
        # an early publish from an agent that comes up at the same time.
        for topic in self._topics:
            self.bus.subscribe(topic, self.rec)
        self.bus.connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.bus.disconnect()

    # Convenience pass-throughs.
    def wait_for(self, n: int, timeout: float = 5.0) -> bool:
        return self.rec.wait_for(n, timeout)

    def wait_for_match(
        self, predicate: Callable[[Any], bool], timeout: float = 5.0
    ) -> bool:
        return self.rec.wait_for_match(predicate, timeout)

    def payloads_on(self, topic: str) -> List[Any]:
        return self.rec.payloads_on(topic)

    def topics(self) -> List[str]:
        return self.rec.topics()


def publish(
    nats_url: str, topic: str, payload: dict, client_id: str = "e2e-producer"
) -> None:
    """One-shot publish of a stimulus to the bus (connect, publish, disconnect)."""
    bus = create_event_bus(nats_config(nats_url), client_id=client_id)
    bus.connect()
    try:
        bus.publish(topic, payload)
    finally:
        bus.disconnect()


class AgentRunner:
    """Run an asyncio agent's ``start()``/``shutdown()`` in-process for an e2e test.

    The agent must expose an ``async start()`` that creates ``self.stop_event``
    (an ``asyncio.Event``) and blocks on it until shutdown — the Orpheus agent
    shape. The runner executes ``start()`` on a background thread with its own
    event loop, no-ops ``loop.add_signal_handler`` (main-thread-only), waits until
    the agent is observably ready, and on exit triggers a graceful shutdown by
    setting ``stop_event`` (the same path a SIGTERM drives).

    ``ready`` defaults to "the agent's bus reports connected"; pass a custom
    predicate (e.g. "the observer saw the startup health message") when needed.
    """

    def __init__(
        self,
        agent: Any,
        *,
        ready: Optional[Callable[[], bool]] = None,
        ready_timeout: float = 15.0,
        shutdown_timeout: float = 15.0,
    ) -> None:
        self._agent = agent
        self._ready = ready or self._bus_connected
        self._ready_timeout = ready_timeout
        self._shutdown_timeout = shutdown_timeout
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()

    def _bus_connected(self) -> bool:
        # `bus` (Actor-based agents) or `mqtt_client` (not-yet-converted agents).
        bus = getattr(self._agent, "bus", None) or getattr(self._agent, "mqtt_client", None)
        return bool(bus is not None and getattr(bus, "is_connected", False))

    def __enter__(self) -> AgentRunner:
        def _run() -> None:
            loop = asyncio.new_event_loop()
            # Signals only work on the main thread; the agent installs handlers via
            # loop.add_signal_handler, so no-op it here. Graceful shutdown is driven
            # by setting stop_event (same code path), not by a real signal.
            loop.add_signal_handler = lambda *a, **k: None  # type: ignore[assignment]
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._loop_ready.set()
            try:
                loop.run_until_complete(self._agent.start())
            finally:
                loop.close()

        self._thread = threading.Thread(target=_run, name="e2e-agent", daemon=True)
        self._thread.start()
        self._loop_ready.wait(5.0)

        end = time.monotonic() + self._ready_timeout
        while time.monotonic() < end:
            if self._ready():
                return self
            time.sleep(0.02)
        self.__exit__(None, None, None)
        raise TimeoutError("agent did not become ready within the timeout")

    def __exit__(self, *exc: Any) -> None:
        ev = getattr(self._agent, "stop_event", None)
        if self._loop is not None and ev is not None:
            try:
                self._loop.call_soon_threadsafe(ev.set)
            except RuntimeError:
                pass  # loop already stopped
        if self._thread is not None:
            self._thread.join(timeout=self._shutdown_timeout)


DEFAULT_NATS_URL = "nats://127.0.0.1:4222"


def reset_orpheus_config_singleton():
    """Body of the autouse fixture every suite needs: OrpheusConfig caches its
    instance, so tests that read config see the previous test's config unless
    the singleton is cleared around each test. Use as
    ``_reset = pytest.fixture(autouse=True)(reset_orpheus_config_singleton)``
    (a generator function, so it plugs straight into ``pytest.fixture``)."""
    from orpheus_common.config import OrpheusConfig

    orig, orig_dotenv = OrpheusConfig._instance, OrpheusConfig._DOTENV_LOADED
    OrpheusConfig._instance = None
    OrpheusConfig._DOTENV_LOADED = False
    yield
    OrpheusConfig._instance = orig
    OrpheusConfig._DOTENV_LOADED = orig_dotenv


def require_broker(
    url: str = DEFAULT_NATS_URL,
    *,
    hint: str = "run a local nats-server or `make sim-up`",
) -> str:
    """Skip the calling test/fixture when no broker answers at ``url``; return
    the url otherwise. The one broker-gate every e2e conftest shares."""
    import pytest

    if not broker_reachable(url):
        pytest.skip(f"no nats-server on {url} ({hint})")
    return url
