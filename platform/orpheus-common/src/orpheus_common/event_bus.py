"""Pluggable event-transport abstraction (Epic 4 — Event Bus Evolution).

Defines the ``EventBus`` ABC every Orpheus component publishes/subscribes
through, plus ``create_event_bus()`` which picks the backend from config.

Backends register in ``_BACKENDS``: ``nats`` (NATS + JetStream — the default
messaging backplane) and ``mqtt`` (mosquitto — the fallback). Components select
via ``config.event_bus.backend`` and never construct a client directly, so the
transport can change without touching a call site.

See ``docs/adr/0015-event-bus-abstraction.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

# A subscriber callback receives (topic, decoded-JSON-payload).
EventCallback = Callable[[str, dict], None]


class EventBus(ABC):
    """Transport-agnostic publish/subscribe interface.

    The contract mirrors the long-standing ``MQTTClient`` surface so adopting
    it is a no-op for existing code. Connection lifecycle (connect/disconnect,
    auto-reconnect) is the implementation's responsibility.
    """

    @abstractmethod
    def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        qos: Optional[int] = None,
        retain: bool = False,
    ) -> None:
        """Publish ``payload`` (JSON-serialisable dict) to ``topic``.

        Signature is a true superset of the MQTT implementation so callers can
        rely on ``retain`` (e.g. retained state topics) and any future backend
        must honour it. ``qos=None`` defers to the backend's default.
        """

    @abstractmethod
    def subscribe(self, topic_pattern: str, callback: EventCallback) -> None:
        """Register ``callback`` for messages on ``topic_pattern`` (wildcards
        allowed)."""

    @abstractmethod
    def unsubscribe(self, topic_pattern: str) -> None:
        """Drop all callbacks for ``topic_pattern`` and stop receiving it."""

    @abstractmethod
    def connect(self) -> None:
        """Connect to the broker/backend."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect cleanly."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True iff currently connected. A property to match the existing
        ``MQTTClient`` surface (callers access ``bus.is_connected``)."""

    # --- Optional JetStream surfaces (ADR 0017) ----------------------------- #
    # Additive + optional: backends that can't serve a surface (mqtt) raise
    # NotImplementedError, so existing call sites are untouched and a caller can
    # feature-detect. The nats backend implements them via JetStream.

    def request(self, topic: str, payload: dict[str, Any], timeout: Optional[float] = None) -> dict:
        """Request-reply: publish ``payload`` to ``topic`` and await one reply
        (JSON dict). For point-to-point actor queries."""
        raise NotImplementedError(
            "request-reply requires a JetStream backend (event_bus.backend: nats)"
        )

    def kv_get(self, bucket: str, key: str) -> Optional[dict]:
        """Read a value from a KV bucket. Returns None iff the bucket/key is
        absent ("not set"); a disconnect/broker error raises rather than masking
        an outage as an unset value. For hot shared state."""
        raise NotImplementedError("kv requires a JetStream backend (event_bus.backend: nats)")

    def kv_put(self, bucket: str, key: str, value: dict, ttl: Optional[float] = None) -> int:
        """Write a value to a KV bucket; returns the new revision. ``ttl`` (s) is
        the bucket-wide time-to-live and is applied only when this call *creates*
        the bucket (NATS KV ttl is fixed at create); pass it on the first write to
        a dedicated bucket. For presence, give heartbeats their own ttl'd bucket."""
        raise NotImplementedError("kv requires a JetStream backend (event_bus.backend: nats)")

    def kv_delete(self, bucket: str, key: str) -> None:
        """Delete a key from a KV bucket."""
        raise NotImplementedError("kv requires a JetStream backend (event_bus.backend: nats)")

    def kv_watch(
        self, bucket: str, key_pattern: str, callback: EventCallback, *, create: bool = True
    ) -> None:
        """Watch a KV bucket; ``callback(key, value)`` fires on change
        (value is None on delete/expiry). For hot-reload + presence. ``create=False``
        means a read-only consumer that won't create an absent bucket (so it can't set
        the wrong bucket-wide TTL) — it no-ops until a writer creates it."""
        raise NotImplementedError("kv requires a JetStream backend (event_bus.backend: nats)")

    def kv_list(self, bucket: str) -> dict[str, dict]:
        """Snapshot every live key→value in a KV bucket (deleted/expired keys
        excluded). Returns ``{}`` for an absent bucket. The queryable side of
        presence ("who's online now?") — see ``orpheus_common.actor.Presence``."""
        raise NotImplementedError("kv requires a JetStream backend (event_bus.backend: nats)")

    def stream_ensure(
        self,
        stream: str,
        subjects: list[str],
        *,
        max_age: Optional[float] = None,
        max_bytes: Optional[int] = None,
        discard: Optional[str] = None,
    ) -> None:
        """Idempotently ensure a durable JetStream stream exists over ``subjects``.

        Optional bounded retention (``max_age`` seconds / ``max_bytes`` / ``discard``
        ``"old"``|``"new"``) caps a domain shadow stream well under the account-level
        store so it never pins the account and reverts by ageing out — see
        docs/designs/event-sourcing-determinism-contract.md §4.4."""
        raise NotImplementedError("streams require a JetStream backend (event_bus.backend: nats)")

    def stream_publish(
        self,
        subject: str,
        payload: dict[str, Any],
        *,
        msg_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        """Publish to a durable stream (acked, persisted) — the event-source log.
        ``msg_id`` sets ``Nats-Msg-Id`` so JetStream dedups a re-published message
        (idempotent shadow on a lost ack); see the determinism contract §4.1.
        ``timeout`` (seconds) caps the wait for the stream ack — a hot-path caller
        passes a short budget so a broker brownout can't stall it for the full bus
        op timeout; None = the backend default."""
        raise NotImplementedError("streams require a JetStream backend (event_bus.backend: nats)")

    def stream_replay(
        self, stream: str, callback: EventCallback, *, subject: Optional[str] = None
    ) -> int:
        """One-shot replay of a stream's history oldest-first into ``callback``
        (for event-sourcing rebuild). Returns the count replayed."""
        raise NotImplementedError("streams require a JetStream backend (event_bus.backend: nats)")


def _make_mqtt_bus(
    config: Any,
    *,
    client_id: Optional[str],
    topics: Optional[list[str]],
    will_topic: Optional[str],
    will_payload: Optional[dict[str, Any]],
    qos: Optional[int] = None,
) -> EventBus:
    # Imported lazily so this module has no import-time dependency on mqtt.py
    # (mqtt.py imports EventBus from here — the lazy import keeps it acyclic).
    from .mqtt import MQTTClient

    mqtt_cfg = config.mqtt
    kwargs: dict[str, Any] = dict(
        broker_host=mqtt_cfg.broker_host,
        broker_port=mqtt_cfg.broker_port,
        client_id=client_id,
        topics=topics,
        keepalive=getattr(mqtt_cfg, "keepalive", 60),
        will_topic=will_topic,
        will_payload=will_payload,
    )
    # Only override the client's default qos when a caller asks for a specific
    # one — callers with explicit MQTT qos semantics keep them exactly through
    # the factory.
    if qos is not None:
        kwargs["qos"] = qos
    return MQTTClient(**kwargs)


def _make_nats_bus(
    config: Any,
    *,
    client_id: Optional[str],
    topics: Optional[list[str]],
    will_topic: Optional[str],
    will_payload: Optional[dict[str, Any]],
    qos: Optional[int] = None,
) -> EventBus:
    # Lazy import to keep the factory module acyclic + off the mqtt fallback path
    # (nats-py is a core dependency).
    from .event_bus_nats import NatsBus

    eb_cfg = getattr(config, "event_bus", None)
    url = getattr(eb_cfg, "nats_url", None) or "nats://127.0.0.1:4222"
    # Is a cold broker at connect() fatal? Default NO: come up disconnected and
    # retry the broker in the background (the documented cold-broker hardening),
    # so an agent that restarts before the broker is up — the common case during
    # a single-host upgrade — self-heals instead of crash-looping. Set
    # event_bus.connect_required: true to hard-fail on a missing broker instead
    # (e.g. when you want systemd to surface it loudly). verify-deploy's broker
    # probe is what catches a genuinely-absent broker at deploy time.
    configured = getattr(eb_cfg, "connect_required", None)
    connect_required = bool(configured) if configured is not None else False
    # qos/topics/retain have no NATS analogue here (pub/sub parity only); the
    # NatsBus warns on retain and falls back for LWT. See its docstring.
    return NatsBus(
        url,
        client_id=client_id,
        will_topic=will_topic,
        will_payload=will_payload,
        connect_required=connect_required,
    )


# Backend registry. New transports add an entry here; nothing else changes.
_BACKENDS: dict[str, Callable[..., EventBus]] = {
    "mqtt": _make_mqtt_bus,
    "nats": _make_nats_bus,
}


def create_event_bus(
    config: Any,
    *,
    client_id: Optional[str] = None,
    topics: Optional[list[str]] = None,
    will_topic: Optional[str] = None,
    will_payload: Optional[dict[str, Any]] = None,
    qos: Optional[int] = None,
) -> EventBus:
    """Build the configured EventBus backend.

    Reads ``config.event_bus.backend`` (default ``"nats"`` — the messaging
    backplane; ``"mqtt"`` is the fallback). A config with no ``event_bus:``
    section gets the nats default. Passes broker settings through from
    ``config.mqtt`` for the mqtt backend. ``qos``
    overrides the backend's default QoS when provided, so callers with
    explicit MQTT qos semantics keep them.

    Raises ``ValueError`` for an unknown backend name.
    """
    backend = getattr(getattr(config, "event_bus", None), "backend", None) or "nats"
    try:
        factory = _BACKENDS[backend]
    except KeyError:
        known = ", ".join(sorted(_BACKENDS))
        raise ValueError(
            f"Unknown event_bus.backend {backend!r}; known backends: {known}"
        ) from None
    return factory(
        config,
        client_id=client_id,
        topics=topics,
        will_topic=will_topic,
        will_payload=will_payload,
        qos=qos,
    )
