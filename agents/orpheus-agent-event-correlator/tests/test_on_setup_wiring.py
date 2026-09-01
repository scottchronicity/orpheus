"""Flag-on ``on_setup`` wiring — the one place each correlation flag becomes
behavior.

Every other unit suite bypasses ``on_setup`` (ClusterManager built directly,
``_weather_db``/``state_space`` injected as mocks), and the e2e fixtures run
flags-off — so a wiring regression in ``on_setup`` (e.g. dropping
``enrich_late_arrivals=...`` from the ClusterManager call) previously passed
every gate. These tests run the REAL ``on_setup`` from a flag-on config with
``ORPHEUS_DATA_ROOT`` pointed at tmp, assert the wiring, then drive one
observation end-to-end through cluster → entity → DB (+ a late arrival through
the enrich path) so each flag is proven to move real behavior.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from orpheus_common.config import OrpheusConfig
from orpheus_common.detection import Detection
from orpheus_common.events import WeatherReading

from orpheus_agent_event_correlator.main import (
    ENTITY_UPDATED_TOPIC,
    EventCorrelatorAgent,
)

DETECTION_TOPIC = "orpheus/detection/bird/events"


def _flag_on_config() -> OrpheusConfig:
    return OrpheusConfig.from_dict(
        {
            "mqtt": {"broker_host": "localhost"},
            "weather": {"enabled": True, "url": "http://station.local"},
            "correlation": {
                "state_space_memory_enabled": True,
                "late_enrichment": {
                    "enabled": True,
                    "ttl_seconds": 123.0,
                    "max_tracked_roots": 77,
                },
            },
        },
        source="<test>",
    )


def _agent() -> EventCorrelatorAgent:
    with patch("orpheus_agent_event_correlator.main.OrpheusConfig") as mock_cfg:
        mock_cfg.get_instance.return_value = _flag_on_config()
        agent = EventCorrelatorAgent(window_seconds=3.0)
    agent.bus = Mock()
    return agent


def _detection(event_id: str, root: str, confidence: float) -> dict:
    return Detection(
        event_id=event_id,
        timestamp=datetime.now(timezone.utc),
        detection_type="species.detected",
        species_code="amecro",
        species_common="American Crow",
        confidence=confidence,
        root_event_id=root,
        source_event_id=root,
        context={"sensor_id": "mic-1"},
    ).model_dump(mode="json")


class TestFlagOnSetupWiring:
    async def test_on_setup_wires_every_flag_into_real_objects(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        agent = _agent()
        await agent.on_setup()

        # Late enrichment: flag + ttl/cap from config, callback bound.
        assert agent.cluster_manager._enrich_late_arrivals is True
        assert agent.cluster_manager._late_ttl_seconds == 123.0
        assert agent.cluster_manager._late_max_tracked_roots == 77
        assert agent.cluster_manager.on_entity_enrich == agent._on_entity_enrich
        # Weather join: a real WeatherDB, constructed once at setup.
        assert agent._weather_db is not None
        # State space: a real memory instance.
        assert agent.state_space is not None
        # Entity persistence under $ORPHEUS_DATA_ROOT.
        assert agent.db is not None
        assert str(tmp_path) in str(agent.db.db_path)

    async def test_flag_on_observation_flows_end_to_end(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        agent = _agent()
        await agent.on_setup()
        # A fresh reading in the REAL weather DB — the join must attach it.
        agent._weather_db.save(
            WeatherReading(
                temperature_c=4.5,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

        agent._on_detection_event(DETECTION_TOPIC, _detection("evt-1", "AM-001", 0.6))
        await asyncio.sleep(0)  # let call_soon_threadsafe deliver to the loop
        agent.cluster_manager._expire_cluster()  # force-emit deterministically

        assert agent.entities_emitted == 1
        assert agent.state_space_recorded == 1  # state-space flag moved behavior
        assert agent.entities_weather_tagged == 1  # weather flag moved behavior
        create_calls = [
            c for c in agent.bus.publish.call_args_list
            if c.args[0] == "orpheus/entities/animal"
        ]
        assert len(create_calls) == 1
        emitted = create_calls[0].args[1]
        assert emitted["context"]["weather"]["temperature_c"] == 4.5
        rows = agent.db.get_entities()
        assert len(rows) == 1
        assert rows[0].species == "amecro"

        # Late arrival on the same root: the enrich wiring (not a duplicate
        # entity) — real _on_entity_enrich against the real SQLite row.
        agent._on_detection_event(DETECTION_TOPIC, _detection("evt-2", "AM-001", 0.9))
        await asyncio.sleep(0)
        assert agent.entities_emitted == 1  # no second entity
        assert agent.entities_enriched == 1
        update_topics = [c.args[0] for c in agent.bus.publish.call_args_list]
        assert ENTITY_UPDATED_TOPIC in update_topics
        enriched_row = agent.db.get_entities()[0]
        assert enriched_row.confidence == 0.9  # the update actually persisted
