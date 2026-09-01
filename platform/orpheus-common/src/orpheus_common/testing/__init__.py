"""Test-support helpers (import only from tests).

``bus_harness`` provides behavior-focused e2e plumbing: stand up a real agent
against a real broker and assert on OBSERVABLE bus behavior (the published
topics/payloads), never on implementation internals. Shared by the Simulacrum
e2e suites across components so the harness lives in one place (DRY).
"""

from orpheus_common.testing.bus_harness import (
    DEFAULT_NATS_URL,
    AgentRunner,
    Observer,
    Recorder,
    broker_reachable,
    nats_config,
    publish,
    require_broker,
    reset_orpheus_config_singleton,
)

__all__ = [
    "AgentRunner",
    "Observer",
    "Recorder",
    "DEFAULT_NATS_URL",
    "broker_reachable",
    "nats_config",
    "require_broker",
    "reset_orpheus_config_singleton",
    "publish",
]
