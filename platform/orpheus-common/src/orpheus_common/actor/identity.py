"""Agent identity — the client-id / health-topic / LWT derivation every agent
hand-rolls today, in one place (ADR 0017 actor model).

The conforming agents all derive the same shape from their name:
``orpheus-agent-<name>`` client id, ``orpheus/system/<name>/health`` health topic,
and an ``offline`` last-will. Centralizing it removes the per-agent string
literals and guarantees they agree.

A deployment may run MULTIPLE instances of a type (e.g. audio-motion on 3 hosts ×
4 mics). Pass an ``instance_id`` to keep each instance's client id + health topic
unique (``orpheus-agent-<name>-<instance>`` / ``orpheus/system/<name>/<instance>/
health`` — the per-type prefix stays, so monitoring can group a type's instances
with ``orpheus/system/<name>/+/health``). Single-instance (no id) is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AgentIdentity:
    """The on-bus identity of an agent, derived from its short ``name``
    (e.g. ``"crow-detection"``) and optional ``instance_id``."""

    name: str
    client_id: str
    health_topic: str
    will_payload: Dict[str, Any]
    instance_id: Optional[str] = None

    @property
    def will_topic(self) -> str:
        """Last-will topic — the health topic (an ungraceful exit leaves
        ``offline`` there, once the backend supports LWT)."""
        return self.health_topic


def agent_identity(name: str, instance_id: Optional[str] = None) -> AgentIdentity:
    """Build the canonical identity for an agent named ``name``.

    ``agent_identity("crow-detection")`` -> client_id
    ``orpheus-agent-crow-detection``, health topic
    ``orpheus/system/crow-detection/health`` — matching the literals the agents
    use today, so adopting it is behavior-preserving. With an ``instance_id`` the
    client id + health topic carry it so co-deployed instances don't collide.
    """
    if instance_id:
        client_id = f"orpheus-agent-{name}-{instance_id}"
        health_topic = f"orpheus/system/{name}/{instance_id}/health"
    else:
        client_id = f"orpheus-agent-{name}"
        health_topic = f"orpheus/system/{name}/health"
    return AgentIdentity(
        name=name,
        client_id=client_id,
        health_topic=health_topic,
        will_payload={"status": "offline"},
        instance_id=instance_id,
    )
