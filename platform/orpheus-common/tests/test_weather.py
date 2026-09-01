"""Tests for weather ingestion ([FEATURE] Ecowitt Weather Station Integration)."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from orpheus_common.config import OrpheusConfig, WeatherConfig
from orpheus_common.events import SpatiotemporalContext, WeatherReading
from orpheus_common.weather import (
    WEATHER_TOPIC,
    EcowittProvider,
    WeatherDB,
    WeatherIngestor,
    WeatherProvider,
)


def _reading() -> WeatherReading:
    return WeatherReading(
        temperature_c=12.5,
        humidity_pct=80.0,
        pressure_hpa=1009.2,
        wind_speed_mps=3.1,
        wind_direction_deg=180,
        rainfall_mm=0.0,
        timestamp="2026-03-01T02:00:00Z",
    )


class _StubProvider(WeatherProvider):
    def __init__(self, reading, *, raises=False):
        self._reading = reading
        self._raises = raises
        self._latest = None
        self.fetch_calls = 0

    def fetch(self):
        self.fetch_calls += 1
        if self._raises:
            raise RuntimeError("boom")
        self._latest = self._reading
        return self._reading

    def get_latest(self):
        return self._latest


class TestWeatherReading:
    def test_roundtrip(self) -> None:
        r = _reading()
        again = WeatherReading(**r.model_dump(mode="json"))
        assert again == r

    def test_all_fields_optional(self) -> None:
        # A partial reading (a sensor offline) is representable, not dropped.
        r = WeatherReading(temperature_c=5.0)
        assert r.humidity_pct is None and r.timestamp == ""


class TestSpatiotemporalContextWeather:
    def test_defaults_none(self) -> None:
        assert SpatiotemporalContext(sensor_id="mic-01").weather is None

    def test_nested_weather_roundtrips_through_json(self) -> None:
        ctx = SpatiotemporalContext(sensor_id="mic-01", weather=_reading())
        blob = ctx.model_dump(mode="json")  # the exact persist call in database.py
        rehydrated = SpatiotemporalContext(**blob)  # the exact rehydrate call
        assert isinstance(rehydrated.weather, WeatherReading)
        assert rehydrated.weather.temperature_c == 12.5

    def test_old_blob_without_weather_rehydrates(self) -> None:
        # NEW binary reading an OLD context blob (no weather key) -> None.
        rehydrated = SpatiotemporalContext(**{"sensor_id": "mic-01"})
        assert rehydrated.weather is None

    def test_unknown_key_is_ignored(self) -> None:
        # OLD binary reading a NEW blob: pydantic extra='ignore' drops unknowns,
        # so a previous release never breaks on the added field. (Reversibility.)
        ctx = SpatiotemporalContext(**{"sensor_id": "mic-01", "future_field": 123})
        assert ctx.sensor_id == "mic-01"


class TestEcowittProvider:
    def test_unreachable_degrades_to_none(self) -> None:
        def _boom():
            raise OSError("connection refused")

        provider = EcowittProvider("http://station/x", fetch_raw=_boom)
        assert provider.fetch() is None  # graceful degradation (Scenario 3)
        assert provider.get_latest() is None

    def test_parse_is_ungrounded_seam(self) -> None:
        # Reachable but the field/unit mapping isn't grounded -> loud, actionable.
        provider = EcowittProvider("http://station/x", fetch_raw=lambda: {"tempf": 60})
        with pytest.raises(NotImplementedError, match="ungrounded seam"):
            provider.fetch()


class TestWeatherDB:
    def test_save_and_get_latest_roundtrip(self, tmp_path: Path) -> None:
        db = WeatherDB(db_path=tmp_path / "orpheus.db")
        assert db.get_latest() is None
        db.save(_reading())
        latest = db.get_latest()
        assert latest is not None
        assert latest.temperature_c == 12.5
        assert latest.wind_direction_deg == 180

    def test_get_latest_returns_most_recent(self, tmp_path: Path) -> None:
        db = WeatherDB(db_path=tmp_path / "orpheus.db")
        db.save(WeatherReading(temperature_c=1.0))
        db.save(WeatherReading(temperature_c=2.0))
        assert db.get_latest().temperature_c == 2.0


class TestWeatherIngestor:
    def test_poll_once_persists_and_publishes(self, tmp_path: Path) -> None:
        db = WeatherDB(db_path=tmp_path / "orpheus.db")
        bus = Mock()
        ingestor = WeatherIngestor(_StubProvider(_reading()), db, bus)
        result = ingestor.poll_once()
        assert result is not None
        assert db.get_latest().temperature_c == 12.5
        bus.publish.assert_called_once_with(
            WEATHER_TOPIC, _reading().model_dump(mode="json"), retain=True
        )

    def test_poll_once_noop_when_no_reading(self, tmp_path: Path) -> None:
        db = WeatherDB(db_path=tmp_path / "orpheus.db")
        bus = Mock()
        ingestor = WeatherIngestor(_StubProvider(None), db, bus)
        assert ingestor.poll_once() is None
        assert db.get_latest() is None
        bus.publish.assert_not_called()

    def test_run_loops_and_sleeps_between_cycles(self, tmp_path: Path) -> None:
        db = WeatherDB(db_path=tmp_path / "orpheus.db")
        provider = _StubProvider(_reading())
        sleeps: list = []
        ingestor = WeatherIngestor(provider, db, Mock(), sleep=lambda s: sleeps.append(s))
        cycles = ingestor.run(interval_seconds=300, max_cycles=2)
        assert cycles == 2
        assert provider.fetch_calls == 2
        # slept once between the two polls (not after last) — sliced into <=1s
        # chunks so a stop request is honoured mid-wait (PEP 475: one long
        # sleep resumes straight through a handled SIGINT/SIGTERM)
        assert sum(sleeps) == 300
        assert all(s <= 1.0 for s in sleeps)

    def test_run_stop_interrupts_the_sleep(self, tmp_path: Path) -> None:
        db = WeatherDB(db_path=tmp_path / "orpheus.db")
        stop_flag = {"stop": False}
        sleeps: list = []

        def _sleep(seconds: float) -> None:
            sleeps.append(seconds)
            stop_flag["stop"] = True  # signal arrives during the first slice

        ingestor = WeatherIngestor(_StubProvider(_reading()), db, Mock(), sleep=_sleep)
        cycles = ingestor.run(interval_seconds=900, stop=lambda: stop_flag["stop"])
        assert cycles == 1
        assert sleeps == [1.0]  # one slice, then the stop flag was honoured

    def test_run_survives_a_failing_cycle(self, tmp_path: Path) -> None:
        db = WeatherDB(db_path=tmp_path / "orpheus.db")
        bus = Mock()
        ingestor = WeatherIngestor(
            _StubProvider(_reading(), raises=True), db, bus, sleep=lambda s: None
        )
        # A provider that always raises must not crash the loop.
        assert ingestor.run(interval_seconds=1, max_cycles=2) == 2
        bus.publish.assert_not_called()

    def test_run_propagates_the_ungrounded_seam(self, tmp_path: Path) -> None:
        # NotImplementedError from EcowittProvider._parse is the DESIGNED loud
        # signal that the field/unit mapping isn't grounded (rule #7) — the
        # resilient per-cycle handler must re-raise it, not absorb it forever.
        class _UngroundedProvider(WeatherProvider):
            def fetch(self):
                raise NotImplementedError("ungrounded seam")

            def get_latest(self):
                return None

        db = WeatherDB(db_path=tmp_path / "orpheus.db")
        ingestor = WeatherIngestor(_UngroundedProvider(), db, Mock(), sleep=lambda s: None)
        with pytest.raises(NotImplementedError, match="ungrounded seam"):
            ingestor.run(interval_seconds=1, max_cycles=2)


class TestWeatherConfig:
    def test_defaults_disabled(self) -> None:
        c = WeatherConfig.from_dict({})
        assert c.enabled is False and c.url == "" and c.poll_interval_seconds == 300.0

    def test_from_dict_values(self) -> None:
        c = WeatherConfig.from_dict(
            {"enabled": True, "url": "http://s/x", "poll_interval_seconds": 60}
        )
        assert c.enabled is True and c.url == "http://s/x" and c.poll_interval_seconds == 60.0

    def test_absent_section_yields_disabled(self) -> None:
        cfg = OrpheusConfig.from_dict({"mqtt": {"broker_host": "localhost"}}, source="<test>")
        assert cfg.weather.enabled is False

    def test_to_dict_includes_weather(self) -> None:
        cfg = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}, "weather": {"enabled": True}},
            source="<test>",
        )
        assert cfg.to_dict()["weather"]["enabled"] is True
