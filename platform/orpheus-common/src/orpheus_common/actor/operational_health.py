"""Operational-health KV substrate — the named-key health writer/reader the UI uses.

The migration target for operational health (agent liveness, error feed, latency
summaries, audio levels, scan summaries) as it moves OFF the domain message bus onto
a zero-dependency NATS KV plane. See docs/designs/observability-and-event-sourcing.md
§11. This is distinct from ``Presence``: ``Presence`` is the LWT/liveness primitive
keyed by ``client_id`` (off by default); ``OperationalHealth`` is the UI-facing health
*value*, keyed by the **bare producer name the UI already expects** (``audio-events``,
``audio``, ``video``, ``auto-discovery``, …), so the consumer side is a drop-in for the
old ``orpheus/system/<name>/health`` topics.

Producer side: ``publish(key, payload)`` writes the producer's existing health payload
verbatim plus an additive envelope, into the ``orpheus_health`` bucket. The FIRST
publish creates the bucket with the intended TTL (NATS KV TTL is fixed at create), so
producers own bucket creation. Consumer side: ``snapshot()`` / ``watch(create=False)``
never create the bucket, so a read-only consumer can never set the wrong TTL.

KV-only (the JetStream/nats backend); on a non-JetStream bus the calls raise
``NotImplementedError`` — feature-detect with ``supported()`` before wiring it in, so
the mqtt fallback keeps its native bus-borne health path (§11.1 backend caveat).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from orpheus_common.actor.kv_ttl_bucket import (
    _DEFAULT_HEARTBEAT_SECONDS,
    KvTtlBucket,
    fleet_ttl_seconds,
)
from orpheus_common.logging import get_logger
from orpheus_common.utils.time import utc_now_iso

logger = get_logger(__name__)

# The consumer-facing contract, exported so UI readers import it instead of
# re-declaring (a re-typed bucket name or envelope list silently forks the
# health plane): the bucket, the envelope keys publish() adds around the
# producer's payload, and the shared staleness floor consumers apply.
HEALTH_BUCKET = "orpheus_health"
ENVELOPE_FIELDS = ("agent", "instance_id", "phase", "emitted_at", "schema")
HEALTH_STALE_AFTER_SECONDS = 90.0

_DEFAULT_BUCKET = HEALTH_BUCKET
_SCHEMA = 1


class OperationalHealth(KvTtlBucket):
    """Per-producer operational health over an EventBus KV bucket (nats backend). The
    ttl, ``snapshot``, ``watch``, and ``supported`` plumbing lives in ``KvTtlBucket``;
    here we key by the bare UI producer name and write an additive health envelope."""

    def __init__(
        self,
        bus: Any,
        *,
        bucket: str = _DEFAULT_BUCKET,
        ttl: Optional[float] = None,
        heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
    ) -> None:
        super().__init__(bus, bucket=bucket, ttl=ttl, heartbeat_seconds=heartbeat_seconds)

    @staticmethod
    def key_for(name: str, instance_id: Optional[str] = None) -> str:
        """The canonical bucket key: the bare producer name, with a flat
        ``<name>__<instance_id>`` encoding for co-deployed instances (no reliance on
        nested-``/`` KV keys)."""
        return f"{name}__{instance_id}" if instance_id else name

    def publish(
        self,
        name: str,
        payload: dict,
        *,
        instance_id: Optional[str] = None,
        phase: str = "heartbeat",
    ) -> int:
        """Write ``payload`` (the producer's existing health dict, verbatim) under the
        producer's key, wrapped in an ADDITIVE envelope so the consumer sees a superset
        of the old shape. The first publish creates the bucket with the TTL. Returns the
        KV revision."""
        envelope = {
            **payload,
            "agent": name,
            "instance_id": instance_id,
            "phase": phase,
            "emitted_at": utc_now_iso(),  # additive DISPLAY field — never the staleness source
            "schema": _SCHEMA,
        }
        return self._bus.kv_put(
            self._bucket, self.key_for(name, instance_id), envelope, ttl=self._ttl
        )

    def offline(self, name: str, instance_id: Optional[str] = None) -> None:
        """Explicit graceful offline (delete the key now rather than waiting out the
        TTL). Absence ⇒ offline on the consumer side."""
        self._bus.kv_delete(self._bucket, self.key_for(name, instance_id))

    def watch(self, callback: Callable[[str, Optional[dict]], None]) -> bool:
        """Subscribe to health changes: ``callback(key, envelope)`` on update,
        ``callback(key, None)`` on offline (delete/expiry). ``create=False`` so a
        read-only consumer never creates the bucket (and thus never sets a wrong TTL);
        it attaches once a producer has created it (pair with a periodic ``snapshot``
        floor + re-establish, per §11.6 Phase 2)."""
        return self._watch(callback, create=False)


def build_operational_health(
    bus: Any,
    orpheus_config: Any,
    *,
    heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
) -> Optional[OperationalHealth]:
    """The ONE shared gate for the health dual-write (Actor base + the hand-rolled
    agents — DRY). Returns an ``OperationalHealth`` iff ``event_bus.health_kv_enabled``
    is set AND the backend serves KV; otherwise ``None`` (so the caller's dual-write is
    a no-op and the bus health path is unchanged — the default, and the mqtt fallback).

    The ttl is FLEET-derived (``fleet_ttl_seconds``): the bucket is shared and its
    ttl is fixed by the first creator, so deriving it from the calling agent's own
    heartbeat would flap any slower-ticking agent (see the KvTtlBucket caveat)."""
    eb = getattr(orpheus_config, "event_bus", None)
    if bus is None or not getattr(eb, "health_kv_enabled", False):
        return None
    oh = OperationalHealth(
        bus,
        ttl=fleet_ttl_seconds(orpheus_config, "health_ttl_seconds"),
        heartbeat_seconds=heartbeat_seconds,
    )
    return oh if oh.supported() else None


def health_on_bus_active(orpheus_config, op_health, *, agent: str) -> bool:
    """§11 Phase 5a gate, shared by the Actor base and the non-Actor agents so
    the migration flag has ONE semantics: publish health to the bus by default;
    honor a configured ``health_on_bus=false`` ONLY while the KV plane is
    actually carrying health — otherwise keep the bus publish (with the
    anti-skew warning) so the UI is never left without a health source."""
    eb = getattr(orpheus_config, "event_bus", None)
    if getattr(eb, "health_on_bus", True):
        return True
    if op_health is None:
        logger.warning(
            "health_on_bus=false but KV health is not active; keeping bus health",
            agent=agent,
        )
        return True
    logger.info("health_on_bus=false; serving health from KV only", agent=agent)
    return False


def kv_publish_best_effort(
    op_health,
    name: str,
    payload: dict,
    *,
    phase: str = "heartbeat",
    instance_id: Optional[str] = None,
) -> None:
    """Dual-write ``payload`` to the operational KV, best-effort: a KV hiccup
    must never disturb the bus publish or the caller's loop. No-op when the KV
    plane is off (``op_health is None``)."""
    if op_health is None:
        return
    try:
        op_health.publish(name, payload, instance_id=instance_id, phase=phase)
    except Exception as e:
        logger.warning("operational-health KV write failed", agent=name, error=str(e))
