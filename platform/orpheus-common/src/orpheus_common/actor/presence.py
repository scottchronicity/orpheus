"""KV-TTL presence — the NATS replacement for MQTT's broker-side last-will.

NATS has no LWT, so an agent can't rely on the broker to announce it offline when
it dies. Instead each agent refreshes a key in a ttl'd JetStream KV bucket on every
heartbeat; if the process is kill -9'd it simply stops refreshing, and the key ages
out within the ttl. Consumers see it go offline two ways:

- ``snapshot()`` — the expired key is gone from the live key set (poll / on-demand
  "who's online now?"). Robust across server versions; the queryable advantage a
  broker-side will never had.
- ``watch(cb)`` — fires ``cb(agent_id, None)`` on an explicit ``offline()`` (graceful
  shutdown) and on key delete.

Set the ttl to a small multiple of the heartbeat interval (default 3x) so one
missed beat doesn't flap an agent offline. This is the one-time helper the backlog
asks for: every agent gets presence by constructing a ``Presence`` over its bus —
no per-agent KV plumbing. KV-only, so it requires the JetStream (nats) backend; on
a non-JetStream bus the underlying ``kv_*`` calls raise ``NotImplementedError``
(feature-detect with ``supported()`` before wiring it in).

CAVEAT — the ttl is **bucket-wide and fixed when the bucket is first created**
(NATS KV has no per-key ttl on this client). The default bucket ``orpheus_presence``
persists on the broker across restarts, so a *later* change to ``ttl`` /
``heartbeat_seconds`` is silently ignored — the bus logs a "kv ttl ignored: bucket
already exists" warning, and ``Presence.ttl`` reports the *requested* value, not the
bucket's actual window. To change the window, delete (recreate) the bucket.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from orpheus_common.actor.kv_ttl_bucket import _DEFAULT_HEARTBEAT_SECONDS, KvTtlBucket
from orpheus_common.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_BUCKET = "orpheus_presence"


class Presence(KvTtlBucket):
    """Per-agent KV-TTL presence over an EventBus (JetStream/nats backend). The ttl,
    ``snapshot``, ``watch``, and ``supported`` plumbing lives in ``KvTtlBucket``; here
    we key by ``agent_id`` (``client_id``) with a bare online payload."""

    def __init__(
        self,
        bus: Any,
        *,
        bucket: str = _DEFAULT_BUCKET,
        ttl: Optional[float] = None,
        heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
    ) -> None:
        super().__init__(bus, bucket=bucket, ttl=ttl, heartbeat_seconds=heartbeat_seconds)

    def online(self, agent_id: str, payload: Optional[dict] = None) -> int:
        """Announce/refresh ``agent_id`` as online. Call once per heartbeat; the key
        ages out within ``ttl`` if the agent stops calling (i.e. dies). Returns the
        KV revision."""
        value = payload if payload is not None else {"status": "online"}
        return self._bus.kv_put(self._bucket, agent_id, value, ttl=self._ttl)

    def offline(self, agent_id: str) -> None:
        """Explicit graceful offline (deletes the key now rather than waiting for the
        ttl). Watchers see ``cb(agent_id, None)`` immediately."""
        self._bus.kv_delete(self._bucket, agent_id)

    def watch(self, callback: Callable[[str, Optional[dict]], None]) -> bool:
        """Subscribe to presence changes: ``callback(agent_id, payload)`` on
        online/refresh, ``callback(agent_id, None)`` on offline (delete).

        ``create=False`` (like ``OperationalHealth.watch``): a watcher is a
        read-only consumer, and NATS KV TTL is bucket-wide + fixed at create —
        a consumer watching before any producer has written would otherwise
        CREATE the bucket with NO TTL, permanently breaking presence expiry
        (kill -9'd agents would appear online forever). The watch attaches once
        a producer creates the bucket (callers pair it with a ``snapshot()``
        floor)."""
        return self._watch(callback, create=False)
