"""Shared event-sourcing shadow helpers (the two-planes design §3 + the determinism
contract). The durable domain log's writers: every agent that OWNS a detection stream
(ADR 0012) ensures the one bounded domain stream at startup and shadow-publishes each
detection to it — in addition to the DB save — keyed by ``Nats-Msg-Id == event_id``.

One stream covers ALL classifier detection topics so the log is complete; every owning
agent calls ``ensure_domain_stream`` with the SAME subject list, so the idempotent
``stream_ensure`` never diverges. The stream binds DEDICATED ``orpheus/domain/...``
subjects (``domain_subject``), never the live topics — a JetStream publish is also a
core publish, so shadowing onto the live subjects would double-deliver every detection
to every live subscriber. Off by default; nats-only; SQLite stays the source of
truth. See docs/designs/event-sourcing-determinism-contract.md §4.
"""

from __future__ import annotations

import time
from typing import Any

from orpheus_common.logging import get_logger

logger = get_logger(__name__)

# The canonical agent-owned detection topics the shadow stream covers (ADR 0006
# hierarchy). Derived ``entities`` are EXCLUDED (correlator-derived, no 1:1 row — see
# the determinism contract §1.2). An operator who renames a topic must widen this list.
DOMAIN_DETECTION_TOPICS = (
    "orpheus/audio/motion/events",
    "orpheus/detection/bird/events",
    "orpheus/detection/crow/events",
    "orpheus/detection/audio/events",
)

# The durable log lives under its OWN subject prefix, never the live topics:
# JetStream ``js.publish`` IS a core publish, so shadowing onto a live subject
# would double-deliver every detection to every live subscriber (the correlator
# counting each observation twice; audio-events re-running inference on every
# shadowed clip event) the moment the flag turns on. Callers keep passing the
# LIVE topic; ``domain_subject`` maps it here, so agents never change.
DOMAIN_SHADOW_PREFIX = "orpheus/domain"

# How long shadow_publish waits for the stream ack. Deliberately far below the
# bus's 5s op default: the shadow rides the detection hot path, and a broker
# brownout must degrade to dropped shadow writes (warned, DB still authoritative),
# not a multi-second stall per detection.
_SHADOW_PUBLISH_TIMEOUT = 1.0

# Topics we've already warned about publishing outside the stream's subject set, so a
# misconfigured agent logs ONCE instead of once per detection.
_WARNED_UNKNOWN_TOPICS: set = set()

# Brownout breaker: after this many CONSECUTIVE stream_publish failures the
# shadow trips open (each failure costs the full JetStream ack timeout ON the
# bus dispatch thread — a multi-hour broker outage would otherwise tax every
# dispatched callback and push the ordered queue toward drop-oldest). While
# open, one publish per probe interval is let through as the re-close probe.
_BREAKER_TRIP_AFTER = 5
_BREAKER_PROBE_EVERY_SECONDS = 30.0
_breaker_failures = 0
_breaker_open_since: float = 0.0
_breaker_last_probe: float = 0.0


def domain_subject(topic: str) -> str:
    """The shadow-stream subject for a live detection topic: the ``orpheus/``
    root is re-rooted under ``orpheus/domain/`` (e.g. ``orpheus/detection/bird/
    events`` -> ``orpheus/domain/detection/bird/events``). Disjoint from every
    live topic by construction — no live consumer subscribes under the prefix —
    and still dot-free, so the durable-log round-trip guard holds."""
    suffix = topic[len("orpheus/"):] if topic.startswith("orpheus/") else topic
    return f"{DOMAIN_SHADOW_PREFIX}/{suffix}"


def ensure_domain_stream(bus: Any, orpheus_config: Any) -> bool:
    """Ensure the bounded durable domain stream (covering every owned detection topic)
    when the shadow is enabled AND the backend serves streams. Idempotent across agents
    (same subject list). Returns whether the caller should shadow-publish. Off by
    default; no-op on mqtt; a failure leaves the shadow off (DB stays source of truth)."""
    es = getattr(orpheus_config, "event_sourcing", None)
    if es is None or not getattr(es, "shadow_publish_enabled", False) or bus is None:
        return False
    try:
        bus.stream_ensure(
            es.stream_name,
            [domain_subject(t) for t in DOMAIN_DETECTION_TOPICS],
            max_age=es.max_age_seconds,
            max_bytes=es.max_bytes,
            discard="old",
        )
    except NotImplementedError:
        logger.info("event-sourcing shadow enabled but backend has no streams; skipping")
        return False
    except Exception as exc:  # never block startup on the shadow
        logger.warning("event-sourcing shadow stream_ensure failed; shadow off", error=str(exc))
        return False
    logger.info("Event-sourcing shadow enabled", stream=es.stream_name)
    return True


def shadow_publish(bus: Any, topic: str, detection: Any) -> None:
    """Best-effort shadow-publish of a detection to the durable domain stream, keyed by
    ``event_id`` (dedup-able). Never raises — a stream hiccup must not stall the agent;
    the DB stays the source of truth. Call AFTER the DB save with the LIVE ``topic``;
    the write lands on ``domain_subject(topic)``, never the live subject (see
    ``DOMAIN_SHADOW_PREFIX`` — live subscribers must not see the shadow copy)."""
    if topic not in DOMAIN_DETECTION_TOPICS:
        # The stream filters on exactly DOMAIN_DETECTION_TOPICS, so a renamed
        # ``output_topic`` would make every publish fail its subject filter and the
        # durable log would silently go incomplete. Skip + warn once, loudly, naming the
        # fix (widen the list) instead of spamming a per-detection failure.
        if topic not in _WARNED_UNKNOWN_TOPICS:
            _WARNED_UNKNOWN_TOPICS.add(topic)
            logger.warning(
                "shadow-publish topic is not in the domain stream's subject set; skipping "
                "(widen DOMAIN_DETECTION_TOPICS if this is a real owned topic)",
                topic=topic,
                known=list(DOMAIN_DETECTION_TOPICS),
            )
        return
    global _breaker_failures, _breaker_open_since, _breaker_last_probe
    now = time.monotonic()
    if _breaker_failures >= _BREAKER_TRIP_AFTER:
        # Open: skip the publish (and its ack-timeout tax) except for one
        # probe per interval that tests whether the broker is back.
        if now - _breaker_last_probe < _BREAKER_PROBE_EVERY_SECONDS:
            return
        _breaker_last_probe = now
    try:
        bus.stream_publish(
            domain_subject(topic),
            detection.model_dump(mode="json"),
            msg_id=detection.event_id,
            timeout=_SHADOW_PUBLISH_TIMEOUT,
        )
    except Exception as exc:  # pylint: disable=broad-except
        _breaker_failures += 1
        if _breaker_failures == _BREAKER_TRIP_AFTER:
            _breaker_open_since = now
            _breaker_last_probe = now
            logger.warning(
                "shadow stream_publish failing repeatedly; PAUSING the shadow "
                "(one probe per interval until the stream recovers — the "
                "durable log is incomplete for this window)",
                topic=topic,
                consecutive_failures=_breaker_failures,
                probe_every_seconds=_BREAKER_PROBE_EVERY_SECONDS,
                error=str(exc),
            )
        elif _breaker_failures < _BREAKER_TRIP_AFTER:
            logger.warning(
                "shadow stream_publish failed",
                topic=topic,
                event_id=getattr(detection, "event_id", None),
                error=str(exc),
            )
        return
    if _breaker_failures >= _BREAKER_TRIP_AFTER:
        logger.warning(
            "shadow stream_publish recovered; resuming the shadow",
            open_seconds=round(now - _breaker_open_since, 1),
        )
    _breaker_failures = 0
