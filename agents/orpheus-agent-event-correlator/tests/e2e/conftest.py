"""Fixtures for the event-correlator e2e bus-contract oracle (consumer side).

Runs the REAL EventCorrelatorAgent against a REAL nats-server with NO model stubs
(the correlator has no model — only SQLite + the bus), so the tests assert the
observable consumer contract: it ingests detection events (incl. the exact
`crow.analyzed` shape the crow agent emits) and fuses them into EntityEvents.
This is the "other side" of the producer contract pinned by the crow oracle.

CI runs this via the correlator job in pr-tests.yml (a dockerized `nats:2 -js`
with a readiness gate, then `make test-e2e`). Locally it needs a nats-server
(`make sim-up`) — otherwise the skip below fires; don't mistake a green unit
gate for coverage of this contract.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from orpheus_common.testing import (
    DEFAULT_NATS_URL,
    nats_config,
    require_broker,
    reset_orpheus_config_singleton,
)

from orpheus_agent_event_correlator import main as corr_main

NATS_URL = DEFAULT_NATS_URL


# Shared body from orpheus_common.testing — one definition, every suite.
_reset_orpheus_config_singleton = pytest.fixture(autouse=True)(
    reset_orpheus_config_singleton
)


@pytest.fixture(scope="session")
def nats_url() -> str:
    return require_broker(NATS_URL)


@pytest.fixture
def correlator(nats_url, tmp_path, monkeypatch):
    """A real EventCorrelatorAgent on NATS with a short cluster window, temp DBs,
    and auto-discovery off — ready to run via AgentRunner."""
    cfg = nats_config(nats_url)
    monkeypatch.setattr(corr_main.OrpheusConfig, "get_instance", MagicMock(return_value=cfg))
    # Entity DB + equivalence graph write under $ORPHEUS_DATA_ROOT — keep them in tmp.
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))

    return corr_main.EventCorrelatorAgent(
        window_seconds=0.5,
        max_cluster_duration_seconds=2.0,
        auto_discovery_enabled=False,
    )


@pytest.fixture
def correlator_no_expiry(nats_url, tmp_path, monkeypatch):
    """A correlator with a long window/duration so a cluster never expires on the
    timer — so ONLY the shutdown flush can emit it (pins the flush-on-shutdown
    path the Actor-base conversion must preserve)."""
    cfg = nats_config(nats_url)
    monkeypatch.setattr(corr_main.OrpheusConfig, "get_instance", MagicMock(return_value=cfg))
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))

    return corr_main.EventCorrelatorAgent(
        window_seconds=30.0,
        max_cluster_duration_seconds=300.0,
        auto_discovery_enabled=False,
    )
