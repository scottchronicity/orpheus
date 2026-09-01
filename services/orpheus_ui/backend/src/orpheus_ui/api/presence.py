"""Agent-presence API endpoint — the first consumer of the KV-TTL presence plane.

``orpheus_common.actor.Presence`` producers (behind the off-by-default
``event_bus.presence_enabled`` flag) refresh a key in a ttl'd JetStream KV bucket
on every heartbeat; a dead agent stops refreshing and ages out. This endpoint
snapshots that bucket so the Diagnostics page can list who is live *right now*.

Presence is KV-only (the nats/JetStream backend). On the mqtt backend — or when
the UI has no bus at all — the endpoint reports ``{"supported": false}`` rather
than erroring, and the frontend shows a muted "not available" note. Transport
errors likewise degrade to ``supported: false``; this endpoint never 500s the
Diagnostics poll.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from orpheus_common.actor import Presence
from orpheus_common.logging import get_logger

from orpheus_ui.auth.backend import current_active_user
from orpheus_ui.auth.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["diagnostics"])

# Reference to the UI's event bus (set by main.py, like diagnostics.set_mqtt_client).
_bus: Optional[Any] = None


def set_bus(bus: Optional[Any]) -> None:
    """Set the event-bus reference used to read the presence bucket."""
    global _bus
    _bus = bus


@router.get("/diagnostics/presence")
def get_presence(user: User = Depends(current_active_user)) -> Dict[str, Any]:
    """Snapshot of live agents from the KV-TTL presence bucket.

    Returns ``{"supported": true, "agents": {agent_id: payload, ...}}`` when the
    bus backend serves KV (JetStream). Dead agents have aged out of the bucket,
    so they're simply absent. On a KV-less backend (mqtt), with no bus, or on a
    transport error, returns ``{"supported": false, "agents": {}}``.

    One KV round-trip per poll: ``supported()`` is itself a ``kv_list`` probe, so
    probing before ``snapshot()`` doubled the broker traffic for every Diagnostics
    poll. Instead we snapshot directly and map the no-KV-surface exceptions
    (``NotImplementedError``/``AttributeError`` — the same pair ``supported()``
    feature-detects on) to ``supported: false``.
    """
    if _bus is None:
        return {"supported": False, "agents": {}}
    try:
        return {"supported": True, "agents": Presence(_bus).snapshot()}
    except (NotImplementedError, AttributeError):
        # Backend has no KV surface (mqtt, or a non-EventBus stub) — not an error.
        return {"supported": False, "agents": {}}
    except Exception as e:
        # A broker/transport blip is "presence unavailable", never a 500.
        logger.warning("Presence snapshot failed; reporting unsupported", error=str(e))
        return {"supported": False, "agents": {}}
