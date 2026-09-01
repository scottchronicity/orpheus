"""Actor-model substrate (ADR 0017) — thin helpers Orpheus owns, on the EventBus.

Starts with the tick/clock seam: a ``Clock`` (WallClock / ManualClock) and a
``PeriodicTask`` so agents tick at configurable, testable frequencies. The
lifecycle helpers (agent_identity / signal handling / graceful shutdown /
ActorStats / HeartbeatPublisher) and the thin ``Actor`` base land here next, then
agents migrate onto them one at a time (crow first), guarded by the e2e oracles.
"""

from orpheus_common.actor.base import Actor
from orpheus_common.actor.clock import Clock, ManualClock, WallClock
from orpheus_common.actor.heartbeat import HeartbeatPublisher
from orpheus_common.actor.identity import AgentIdentity, agent_identity
from orpheus_common.actor.kv_ttl_bucket import KvTtlBucket
from orpheus_common.actor.lifecycle import install_signal_handlers
from orpheus_common.actor.operational_health import (
    ENVELOPE_FIELDS,
    HEALTH_BUCKET,
    HEALTH_STALE_AFTER_SECONDS,
    OperationalHealth,
    build_operational_health,
    health_on_bus_active,
    kv_publish_best_effort,
)
from orpheus_common.actor.periodic import PeriodicTask
from orpheus_common.actor.presence import Presence
from orpheus_common.actor.stats import ActorStats

__all__ = [
    "Actor",
    "ActorStats",
    "AgentIdentity",
    "Clock",
    "HeartbeatPublisher",
    "KvTtlBucket",
    "ManualClock",
    "OperationalHealth",
    "PeriodicTask",
    "Presence",
    "WallClock",
    "agent_identity",
    "ENVELOPE_FIELDS",
    "HEALTH_BUCKET",
    "HEALTH_STALE_AFTER_SECONDS",
    "build_operational_health",
    "health_on_bus_active",
    "kv_publish_best_effort",
    "install_signal_handlers",
]
