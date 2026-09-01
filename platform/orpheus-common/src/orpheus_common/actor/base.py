"""The thin Actor base (ADR 0017) — the agent lifecycle, composed once.

The 4 conforming bus agents hand-roll the same ``start()``/``shutdown()``: derive
identity, create the bus, subscribe, connect, install signal handlers, publish a
startup health, run a 30s heartbeat, wait for stop, then publish offline +
disconnect. ``Actor`` is that skeleton; a subclass fills the agent-specific parts
via hooks:

- ``on_setup()``     — load models / open DBs (async).
- ``subscriptions()``— the ``[(topic, callback), …]`` to subscribe.
- ``health_payload(phase)`` — the EXACT health dict for ``"startup"`` /
  ``"heartbeat"`` / ``"shutdown"`` (so per-agent divergences are preserved).
- ``on_shutdown()``  — agent-specific teardown (async, optional).
- ``enabled()``      — gate start (default True).

``self.bus`` is the EventBus, ``self.stop_event`` the shutdown trigger,
``self.stats`` an ActorStats, ``self.identity`` the derived AgentIdentity. The
clock + heartbeat interval are injectable (WallClock/30s default = today's
behavior; a ManualClock makes sim/test ticks instant). systemd still supervises;
this is in-process lifecycle only.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple

from orpheus_common.actor.clock import Clock, WallClock
from orpheus_common.actor.heartbeat import HeartbeatPublisher
from orpheus_common.actor.identity import AgentIdentity, agent_identity
from orpheus_common.actor.kv_ttl_bucket import fleet_ttl_seconds
from orpheus_common.actor.lifecycle import install_signal_handlers
from orpheus_common.actor.operational_health import (
    OperationalHealth,
    build_operational_health,
    health_on_bus_active,
    kv_publish_best_effort,
)
from orpheus_common.actor.presence import Presence
from orpheus_common.actor.stats import ActorStats
from orpheus_common.event_bus import EventBus, EventCallback, create_event_bus
from orpheus_common.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_HEARTBEAT_SECONDS = 30.0


class Actor:
    """Base class for an Orpheus bus agent. Subclass + implement the hooks."""

    def __init__(
        self,
        name: str,
        orpheus_config: Any,
        *,
        instance_id: Optional[str] = None,
        clock: Optional[Clock] = None,
        heartbeat_seconds: Optional[float] = None,
    ) -> None:
        self.name = name
        # The loaded OrpheusConfig — used to build the bus (event_bus.backend etc.).
        # A subclass keeps its own agent-specific config under a different name.
        self.orpheus_config = orpheus_config
        # instance_id distinguishes co-deployed instances of a type (3 hosts × 4
        # mics). Explicit arg wins; otherwise it's read from the deploy env
        # (ORPHEUS_AGENT_INSTANCE_ID), so multi-instance is a deploy-time setting
        # with NO per-agent code. Absent ⇒ None ⇒ single instance (unchanged).
        instance_id = instance_id or os.environ.get("ORPHEUS_AGENT_INSTANCE_ID") or None
        self.identity: AgentIdentity = agent_identity(name, instance_id)
        self.stats = ActorStats()
        self.clock: Clock = clock or WallClock()
        # Tick cadence resolution: explicit constructor arg (tests/sim) >
        # agents.<name>.heartbeat_seconds in orpheus.yaml > the 30s default.
        # Strict float coercion so a mocked config can never leak a Mock into
        # the timer math.
        if heartbeat_seconds is None:
            try:
                configured = orpheus_config.agent_tick(name).heartbeat_seconds
                heartbeat_seconds = (
                    float(configured)
                    if isinstance(configured, (int, float)) and configured > 0
                    else _DEFAULT_HEARTBEAT_SECONDS
                )
            except Exception:
                heartbeat_seconds = _DEFAULT_HEARTBEAT_SECONDS
        self.heartbeat_seconds = heartbeat_seconds

        self.bus: Optional[EventBus] = None
        self.stop_event: Optional[asyncio.Event] = None
        self._heartbeat: Optional[HeartbeatPublisher] = None
        # KV-TTL presence emitter — set in start() iff enabled in config AND the
        # backend serves KV (nats). None ⇒ no-op (default; mqtt keeps native LWT).
        self._presence: Optional[Presence] = None
        # Operational-health KV writer (§11 migration, Phase 1) — set iff
        # event_bus.health_kv_enabled AND KV-capable backend. Dual-writes the health
        # payload to the orpheus_health bucket IN ADDITION to the bus publish (which
        # is untouched this phase). None ⇒ no-op. Keyed by the bare agent name.
        self._op_health: Optional[OperationalHealth] = None
        # §11 Phase 5a: publish health to the bus? Default True (today's behavior);
        # flipped off only after the UI is confirmed on KV + soaked. On mqtt it stays
        # True regardless (the bus is the only health plane there). Resolved in start().
        self._health_on_bus: bool = True

    # --- lifecycle --------------------------------------------------------- #

    async def start(self) -> None:
        """Run the agent until SIGINT/SIGTERM (or ``stop_event``), then shut down."""
        self.stop_event = asyncio.Event()
        if not self.enabled():
            logger.warning("Agent disabled in configuration; not starting", agent=self.name)
            return

        await self.on_setup()

        self.bus = create_event_bus(
            self.orpheus_config,
            client_id=self.identity.client_id,
            will_topic=self.identity.will_topic,
            will_payload=self.identity.will_payload,
        )
        for topic, callback in self.subscriptions():
            self.bus.subscribe(topic, callback)
        self.bus.connect()
        logger.info("Connected to event bus (backplane)", agent=self.name)

        install_signal_handlers(asyncio.get_running_loop(), self.stop_event)

        self._presence = self._make_presence()
        self._op_health = self._make_operational_health()
        # Bus health stays on unless explicitly turned off AND the KV plane can carry
        # it (never blank health: on mqtt, or when KV dual-write isn't active, keep
        # publishing to the bus regardless of the flag).
        self._health_on_bus = self._resolve_health_on_bus()
        if self._health_on_bus:
            self.bus.publish(self.identity.health_topic, self.health_payload("startup"))
        self._presence_refresh(self.health_payload("startup"))
        self._health_kv_publish(self.health_payload("startup"), "startup")
        self._heartbeat = HeartbeatPublisher(
            self.bus,
            self.identity.health_topic,
            self._heartbeat_payload,
            interval=self.heartbeat_seconds,
            clock=self.clock,
            publish_predicate=lambda: self._health_on_bus,
        )
        self._heartbeat.start()

        # Post-connect background work (e.g. a periodic discovery worker).
        await self.on_started()

        await self.stop_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        """Stop the heartbeat, announce offline, disconnect, then agent teardown."""
        logger.info("Shutting down", agent=self.name)
        # Stop the heartbeat BEFORE disconnecting so its next tick can't publish to
        # a half-closed bus (the agents' established ordering).
        if self._heartbeat is not None:
            await self._heartbeat.stop()
            self._heartbeat = None
        # Pre-disconnect hook: final work that must PUBLISH while the bus is still
        # connected (e.g. flushing open clusters). Runs before offline + disconnect.
        await self.on_stopping()
        # Graceful presence offline (delete the key now rather than waiting out the
        # ttl) — while the bus is still connected, like the offline health publish.
        if self._presence is not None:
            try:
                self._presence.offline(self.identity.client_id)
            except Exception as e:
                logger.debug("presence offline failed", agent=self.name, error=str(e))
            self._presence = None
        # Graceful operational-health offline (delete the key; UI sees absence ⇒ offline).
        if self._op_health is not None:
            try:
                self._op_health.offline(self.name, self.identity.instance_id)
            except Exception as e:
                logger.debug("operational-health offline failed", agent=self.name, error=str(e))
            self._op_health = None
        if self.bus is not None:
            if self._health_on_bus:
                self.bus.publish(self.identity.health_topic, self.health_payload("shutdown"))
            self.bus.disconnect()
        await self.on_shutdown()

    # --- presence (KV-TTL, opt-in) ----------------------------------------- #

    def _make_presence(self) -> Optional[Presence]:
        """Build a presence emitter iff ``event_bus.presence_enabled`` is set AND the
        backend serves KV (nats). Default OFF — emitting presence for every agent is
        new broad behavior, so it stays behind a flag; mqtt keeps its native LWT.
        Returns None (a no-op) when disabled or unsupported.

        The ttl is FLEET-derived (``fleet_ttl_seconds``), not 3x this agent's
        heartbeat: the bucket is shared and its ttl is fixed by the first creator,
        so a per-agent derivation flaps any agent whose heartbeat is slower than
        the creator's (per-agent ticks via ``agents.<name>.heartbeat_seconds``)."""
        eb = getattr(self.orpheus_config, "event_bus", None)
        if not getattr(eb, "presence_enabled", False):
            return None
        presence = Presence(
            self.bus,
            ttl=fleet_ttl_seconds(self.orpheus_config, "presence_ttl_seconds"),
            heartbeat_seconds=self.heartbeat_seconds,
        )
        if not presence.supported():
            logger.info(
                "Presence enabled but backend has no KV; skipping (mqtt uses LWT)",
                agent=self.name,
            )
            return None
        logger.info("Presence enabled (KV-TTL)", agent=self.name, ttl=presence.ttl)
        return presence

    def _make_operational_health(self) -> Optional[OperationalHealth]:
        """Build the operational-health KV writer via the shared gate (§11 Phase 1):
        on iff ``event_bus.health_kv_enabled`` AND the backend serves KV. Default OFF
        ⇒ None (the bus publish is the only path, as today; mqtt keeps bus-borne
        health)."""
        oh = build_operational_health(
            self.bus, self.orpheus_config, heartbeat_seconds=self.heartbeat_seconds
        )
        if oh is not None:
            logger.info("Operational health dual-writing to KV", agent=self.name, ttl=oh.ttl)
        return oh

    def _resolve_health_on_bus(self) -> bool:
        """Whether to publish health to the bus (§11 Phase 5a). Default True. Honor a
        configured ``health_on_bus=false`` ONLY when the KV health plane is actually
        carrying health (``_op_health`` active) — otherwise keep the bus publish so the
        UI is never left with no health source (mqtt / KV-not-enabled stay on the bus).
        This is the anti-skew guard from §11.6."""
        return health_on_bus_active(self.orpheus_config, self._op_health, agent=self.name)

    def _heartbeat_payload(self) -> Dict[str, Any]:
        """The heartbeat callback: build the payload, refresh presence + dual-write
        health to KV, and return it for the bus health publish (one tick drives all)."""
        payload = self.health_payload("heartbeat")
        self._presence_refresh(payload)
        self._health_kv_publish(payload, "heartbeat")
        return payload

    def _health_kv_publish(self, payload: Dict[str, Any], phase: str) -> None:
        """Dual-write the health payload to the operational KV (best-effort — a KV
        hiccup must never disturb the bus publish or the heartbeat). Keyed by the bare
        agent name (what the UI expects)."""
        kv_publish_best_effort(
            self._op_health,
            self.name,
            payload,
            phase=phase,
            instance_id=self.identity.instance_id,
        )

    def _presence_refresh(self, payload: Dict[str, Any]) -> None:
        """Refresh the agent's presence key (best-effort — a KV hiccup must not take
        down the heartbeat/health publish)."""
        if self._presence is None:
            return
        try:
            self._presence.online(self.identity.client_id, payload)
        except Exception as e:
            logger.warning("presence refresh failed", agent=self.name, error=str(e))

    # --- hooks (override in subclasses) ------------------------------------ #

    def enabled(self) -> bool:
        """Whether to start. Override to honor a config flag."""
        return True

    async def on_setup(self) -> None:
        """Load models / open databases. Override; default no-op."""

    async def on_started(self) -> None:
        """Start post-connect background work (e.g. a discovery worker), after the
        bus is connected + the heartbeat is running. Override; default no-op."""

    async def on_stopping(self) -> None:
        """Final work that must PUBLISH while the bus is still connected (e.g.
        flush open clusters), run on shutdown BEFORE offline + disconnect.
        Override; default no-op."""

    def subscriptions(self) -> List[Tuple[str, EventCallback]]:
        """The ``[(topic, callback), …]`` to subscribe at connect. Override."""
        return []

    def health_payload(self, phase: str) -> Dict[str, Any]:
        """The health dict for ``phase`` (``startup``/``heartbeat``/``shutdown``).

        Default: ``status`` (online for startup/heartbeat, offline for shutdown)
        plus ``ActorStats``. Override to match an agent's exact shape."""
        status = "offline" if phase == "shutdown" else "online"
        payload = {"status": status, **self.stats.as_dict()}
        # Backpressure visibility: drop-oldest shedding is otherwise only a
        # rate-limited journald line. Additive; absent on backends without it.
        stats_fn = getattr(self.bus, "dispatch_stats", None)
        if callable(stats_fn):
            try:
                payload["bus_dispatch"] = stats_fn()
            except Exception:  # noqa: S110 - health must never fail on a stats read
                pass
        return payload

    async def on_shutdown(self) -> None:
        """Agent-specific teardown. Override; default no-op."""
