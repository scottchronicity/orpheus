"""HeartbeatPublisher — the agents' periodic health pulse, consolidated.

Every conforming agent runs a ``while True: sleep(30); publish(health)`` loop. This
replaces it with a ``PeriodicTask`` whose interval + clock are injectable (30s on
WallClock in prod, instant on a ManualClock in tests/sim). The payload is supplied
per-tick by ``payload_fn`` so each agent keeps its EXACT health shape (model_loaded
vs models_loaded, detections_found vs entities_emitted, …) — the divergences the
e2e oracles pin.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from orpheus_common.actor.clock import Clock
from orpheus_common.actor.periodic import PeriodicTask

HealthPayloadFn = Callable[[], Dict[str, Any]]


class HeartbeatPublisher:
    """Publish ``payload_fn()`` to ``topic`` every ``interval`` seconds via ``bus``."""

    def __init__(
        self,
        bus: Any,
        topic: str,
        payload_fn: HealthPayloadFn,
        *,
        interval: float = 30.0,
        clock: Optional[Clock] = None,
        name: Optional[str] = None,
        publish_predicate: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._bus = bus
        self._topic = topic
        self._payload_fn = payload_fn
        # Gate ONLY the bus publish (§11 Phase 5a: stop bus health when health_on_bus
        # is off). The tick still calls payload_fn() every interval so the side effects
        # it carries (presence + operational-health KV refresh) keep running. Default
        # None ⇒ always publish (byte-identical).
        self._publish_predicate = publish_predicate
        self._task = PeriodicTask(
            interval, self._publish, clock=clock, name=name or f"heartbeat:{topic}"
        )

    def _publish(self) -> None:
        # PeriodicTask isolates exceptions; bus.publish is best-effort when
        # disconnected (matches the agents' current heartbeat semantics).
        payload = self._payload_fn()  # always — drives presence/op-health refresh
        if self._publish_predicate is None or self._publish_predicate():
            self._bus.publish(self._topic, payload)

    def start(self) -> None:
        self._task.start()

    async def stop(self) -> None:
        await self._task.stop()

    @property
    def running(self) -> bool:
        return self._task.running
