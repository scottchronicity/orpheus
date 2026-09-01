"""Ambient-weather context join ([FEATURE] Ecowitt, Scenario 2).

When the weather ingestor is on, each emitted entity's context gains the
freshest reading (additive `context.weather`; old binaries drop it via
SpatiotemporalContext's extra="ignore") so weather/wildlife correlation is
answerable straight from the entities table. Gated by the EXISTING
`weather.enabled` knob — off (the default) attaches nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from orpheus_common.config import OrpheusConfig
from orpheus_common.detection.database import open_connection
from orpheus_common.events import SpatiotemporalContext, WeatherReading
from orpheus_common.weather import WeatherDB

from orpheus_agent_event_correlator.main import EventCorrelatorAgent


def _agent(*, weather_enabled: bool) -> EventCorrelatorAgent:
    cfg = OrpheusConfig.from_dict(
        {
            "mqtt": {"broker_host": "localhost"},
            "weather": {"enabled": weather_enabled, "url": "http://station.local"},
        },
        source="<test>",
    )
    with patch("orpheus_agent_event_correlator.main.OrpheusConfig") as mock_cfg:
        mock_cfg.get_instance.return_value = cfg
        agent = EventCorrelatorAgent()
    agent.bus = Mock()
    agent.db = None  # skip persistence; we exercise the context join only
    return agent


def _reading(*, age_seconds: float = 30.0) -> WeatherReading:
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return WeatherReading(
        temperature_c=4.5, humidity_pct=81.0, wind_speed_mps=6.2,
        timestamp=ts.isoformat(),
    )


def _entity() -> dict:
    return {
        "entity_id": "e1",
        "species_code": "amecro",
        "common_name": "American Crow",
        "confidence": 0.9,
        "evidence": [],
        "entity_type": "Animal.Bird.Crow",
        "context": {"timestamp": "2026-07-01T00:00:00+00:00"},
        "timestamp": "2026-07-01T00:00:00+00:00",
        "is_self_generated": False,
    }


class TestWeatherContextJoin:
    def test_disabled_by_default_attaches_nothing(self) -> None:
        agent = _agent(weather_enabled=False)
        assert agent.weather_enabled is False
        assert agent._weather_db is None  # never constructed when off
        entity = _entity()
        agent._on_entity_ready(entity)
        assert "weather" not in entity["context"]

    def test_fresh_reading_attached_to_context(self) -> None:
        agent = _agent(weather_enabled=True)
        agent._weather_db = Mock()
        agent._weather_db.latest_row.return_value = (_reading(age_seconds=30.0), "")
        entity = _entity()
        agent._on_entity_ready(entity)
        weather = entity["context"]["weather"]
        assert weather["temperature_c"] == 4.5
        assert weather["wind_speed_mps"] == 6.2
        assert agent.entities_weather_tagged == 1

    def test_stale_reading_not_attached(self) -> None:
        # Older than 2x the poll interval (default 300s -> 600s bound): the
        # ingestor is down; attaching would claim weather we don't know.
        agent = _agent(weather_enabled=True)
        agent._weather_db = Mock()
        agent._weather_db.latest_row.return_value = (_reading(age_seconds=700.0), "")
        entity = _entity()
        agent._on_entity_ready(entity)
        assert "weather" not in entity["context"]
        assert agent.entities_weather_tagged == 0

    def test_no_reading_yet_attaches_nothing(self) -> None:
        agent = _agent(weather_enabled=True)
        agent._weather_db = Mock()
        agent._weather_db.latest_row.return_value = None
        entity = _entity()
        agent._on_entity_ready(entity)
        assert "weather" not in entity["context"]

    def test_db_error_never_blocks_the_entity(self) -> None:
        agent = _agent(weather_enabled=True)
        agent._weather_db = Mock()
        agent._weather_db.latest_row.side_effect = RuntimeError("db locked")
        entity = _entity()
        agent._on_entity_ready(entity)  # no raise
        assert "weather" not in entity["context"]

    def test_reading_is_memoized_across_entities(self) -> None:
        # Readings change every poll interval; a dawn-chorus burst of entities
        # must not hit SQLite once per entity.
        agent = _agent(weather_enabled=True)
        agent._weather_db = Mock()
        agent._weather_db.latest_row.return_value = (_reading(), "")
        for _ in range(5):
            agent._on_entity_ready(_entity())
        assert agent._weather_db.latest_row.call_count == 1
        assert agent.entities_weather_tagged == 5

    def test_timestampless_reading_falls_back_to_recorded_at(self, tmp_path) -> None:
        # WeatherReading allows PARTIAL readings (timestamp defaults to "") and
        # no production provider is forced to set it — freshness must fall back
        # to the ingest-side recorded_at instead of silently killing the join.
        agent = _agent(weather_enabled=True)
        db = WeatherDB(db_path=tmp_path / "weather.db")
        db.save(WeatherReading(temperature_c=4.5))  # timestamp="" — partial
        agent._weather_db = db
        entity = _entity()
        agent._on_entity_ready(entity)
        assert entity["context"]["weather"]["temperature_c"] == 4.5
        assert agent.entities_weather_tagged == 1

    def test_unparseable_timestamp_falls_back_to_recorded_at(self, tmp_path) -> None:
        agent = _agent(weather_enabled=True)
        db = WeatherDB(db_path=tmp_path / "weather.db")
        db.save(WeatherReading(temperature_c=1.5, timestamp="not-a-timestamp"))
        agent._weather_db = db
        entity = _entity()
        agent._on_entity_ready(entity)
        assert entity["context"]["weather"]["temperature_c"] == 1.5

    def test_timestampless_reading_with_stale_recorded_at_not_attached(
        self, tmp_path
    ) -> None:
        # The fallback keeps the staleness guard honest: a timestamp-less row
        # ingested long ago (ingestor down since) still attaches nothing.
        agent = _agent(weather_enabled=True)
        db = WeatherDB(db_path=tmp_path / "weather.db")
        db.save(WeatherReading(temperature_c=4.5))
        old = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        conn = open_connection(db.db_path)
        try:
            conn.execute("UPDATE weather_readings SET recorded_at = ?", (old,))
            conn.commit()
        finally:
            conn.close()
        agent._weather_db = db
        entity = _entity()
        agent._on_entity_ready(entity)
        assert "weather" not in entity["context"]
        assert agent.entities_weather_tagged == 0

    def test_stale_rejection_warning_is_rate_limited(self) -> None:
        # The dead path must be visible on Diagnostics — exactly one warning
        # per 5-minute window, not one per entity in a chorus.
        agent = _agent(weather_enabled=True)
        agent._weather_db = Mock()
        agent._weather_db.latest_row.return_value = (_reading(age_seconds=700.0), "")
        with patch("orpheus_agent_event_correlator.main.logger") as mock_logger:
            for _ in range(3):
                agent._on_entity_ready(_entity())
        stale_warnings = [
            c for c in mock_logger.warning.call_args_list
            if "rejected" in c.args[0]
        ]
        assert len(stale_warnings) == 1

    def test_typed_round_trip_through_spatiotemporal_context(self) -> None:
        # The attached dict rehydrates into the typed model — the seam the UI
        # and future consumers read through.
        agent = _agent(weather_enabled=True)
        agent._weather_db = Mock()
        agent._weather_db.latest_row.return_value = (_reading(), "")
        entity = _entity()
        agent._on_entity_ready(entity)
        ctx = SpatiotemporalContext(
            timestamp=datetime.now(timezone.utc), **{
                k: v for k, v in entity["context"].items() if k != "timestamp"
            }
        )
        assert ctx.weather is not None
        assert ctx.weather.temperature_c == 4.5
