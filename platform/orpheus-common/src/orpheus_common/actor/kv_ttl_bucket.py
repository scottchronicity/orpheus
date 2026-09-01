"""``KvTtlBucket`` — the shared KV-TTL substrate under ``Presence`` and
``OperationalHealth``.

Both are the same primitive: a producer refreshes a key in a ttl'd JetStream KV
bucket on every heartbeat; if the process is kill -9'd it stops refreshing and the
key ages out within the ttl (the NATS stand-in for MQTT's broker-side last-will,
which JetStream has no equivalent of). They differ ONLY in what they key by and the
envelope they write — ``Presence`` keys by ``client_id`` with a bare
``{"status": "online"}``; ``OperationalHealth`` keys by the bare UI producer name
with an additive health envelope. Everything mechanical — the ttl derivation, the
``snapshot`` read, the ``supported()`` feature-probe, and the ``watch`` plumbing —
is identical, so it lives here once instead of drifting across two files.

KV-only (the JetStream/nats backend); on a non-JetStream bus the underlying ``kv_*``
calls raise ``NotImplementedError`` — feature-detect with ``supported()`` before
wiring it in so the mqtt fallback stays a no-op.

CAVEAT — the ttl is **bucket-wide and fixed when the bucket is first created** (NATS
KV has no per-key ttl on this client). The bucket persists on the broker across
restarts, so a *later* change to ``ttl`` / ``heartbeat_seconds`` is silently ignored
(the bus logs "kv ttl ignored: bucket already exists") and ``.ttl`` reports the
*requested* value, not the bucket's actual window. To change the window, recreate the
bucket.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

# A small multiple of the heartbeat interval: tolerate one missed beat before a
# producer is considered gone, but still detect a hard kill within ~ttl seconds.
_DEFAULT_HEARTBEAT_SECONDS = 30.0
_DEFAULT_TTL_MULTIPLIER = 3.0


def fleet_ttl_seconds(orpheus_config: Any, override_key: str) -> float:
    """The bucket-wide TTL every agent should request for a SHARED KV-TTL bucket.

    The ttl is fixed by whichever agent creates the bucket FIRST (see the module
    caveat), so deriving it from *this* agent's heartbeat breaks the moment
    per-agent heartbeats diverge (``agents.<name>.heartbeat_seconds``): a
    120s-tick agent refreshing into a bucket a 30s-tick agent created (ttl=90s)
    expires between its own beats and flaps offline forever. Instead every agent
    derives the SAME value from the shared yaml:

    - an explicit ``event_bus.<override_key>`` wins when set to a positive
      number (read via ``getattr`` — a named seam for the config owner; inert
      until ``EventBusConfig`` grows the field);
    - else 3x the LARGEST configured heartbeat across ``agents.*``, floored at
      the 30s default — so the slowest-ticking agent never outlives its key.

    Strict type checks throughout so a mocked config can never leak a Mock into
    the ttl math (matching the Actor base's heartbeat coercion)."""
    eb = getattr(orpheus_config, "event_bus", None)
    override = getattr(eb, override_key, None)
    if isinstance(override, (int, float)) and not isinstance(override, bool) and override > 0:
        return float(override)
    slowest = _DEFAULT_HEARTBEAT_SECONDS
    agents = getattr(orpheus_config, "agents", None)
    if isinstance(agents, dict):
        for tick in agents.values():
            hb = getattr(tick, "heartbeat_seconds", None)
            if isinstance(hb, (int, float)) and not isinstance(hb, bool) and hb > slowest:
                slowest = float(hb)
    return slowest * _DEFAULT_TTL_MULTIPLIER


class KvTtlBucket:
    """A ttl'd KV bucket over an EventBus (JetStream/nats backend). Subclass it and add
    the domain-specific key encoding + write methods; the ttl, snapshot, watch, and
    feature-probe are inherited."""

    def __init__(
        self,
        bus: Any,
        *,
        bucket: str,
        ttl: Optional[float] = None,
        heartbeat_seconds: float = _DEFAULT_HEARTBEAT_SECONDS,
    ) -> None:
        self._bus = bus
        self._bucket = bucket
        # ttl is bucket-wide on NATS KV and fixed at create, so the FIRST write into a
        # fresh bucket sets the window for everyone. Default it from the heartbeat so
        # callers usually pass nothing.
        self._ttl = ttl if ttl is not None else heartbeat_seconds * _DEFAULT_TTL_MULTIPLIER

    @property
    def ttl(self) -> float:
        return self._ttl

    def snapshot(self) -> dict[str, dict]:
        """Every live key: ``{key: value}``. Dead producers have aged out of the bucket
        (TTL), so they're simply absent. Read-only — never creates the bucket."""
        return self._bus.kv_list(self._bucket)

    def _watch(
        self, callback: Callable[[str, Optional[dict]], None], *, create: bool = True
    ) -> bool:
        """Subscribe to key changes over the whole bucket (``callback(key, value)`` on
        update, ``callback(key, None)`` on delete/expiry). When ``create`` is the default
        True we omit the kwarg so the bus applies its own default; a read-only consumer
        passes ``create=False`` so it never creates the bucket (and thus never sets a
        wrong TTL)."""
        if create:
            return bool(self._bus.kv_watch(self._bucket, ">", callback))
        return bool(self._bus.kv_watch(self._bucket, ">", callback, create=False))

    def supported(self) -> bool:
        """True iff the bus backend can serve KV (JetStream). Feature-detect before
        wiring it into an agent so the mqtt fallback stays a no-op."""
        try:
            self._bus.kv_list(self._bucket)
        except (NotImplementedError, AttributeError):
            return False  # backend has no KV surface (mqtt, or a non-EventBus stub)
        except Exception:
            # A transport/broker error is not "unsupported" — the surface exists.
            return True
        return True
