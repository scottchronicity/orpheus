"""Tests for the /api/weather/latest endpoint (Dashboard weather card)."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from orpheus_common.events import WeatherReading


@pytest.fixture(autouse=True)
def reset_weather_db_cache():
    """Keep the process-wide cached WeatherDB from leaking across tests."""
    from orpheus_ui.api import weather

    original = weather._weather_db
    weather._weather_db = None
    yield
    weather._weather_db = original


class TestWeatherAPI:
    """Tests for the weather API endpoint.

    The endpoint is feature-detected end to end: disabled config, missing
    reading, and config/DB errors all yield ``{"available": false}`` — never a
    500 — so the Dashboard card hides on deploys with no weather station.
    """

    def _mock_config(self, enabled: bool) -> MagicMock:
        mock_config = MagicMock()
        mock_config.weather.enabled = enabled
        return mock_config

    def test_weather_latest_disabled_returns_unavailable(self):
        """weather.enabled=False (the default) → available:false, DB untouched."""
        from orpheus_ui.api.weather import get_weather_latest
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch(
            "orpheus_common.OrpheusConfig.get_instance",
            return_value=self._mock_config(enabled=False),
        ):
            with patch("orpheus_ui.api.weather._get_weather_db") as mock_db:
                result = get_weather_latest(user=mock_user)

        assert result == {"available": False}
        mock_db.assert_not_called()

    def test_weather_latest_default_config_is_unavailable(self):
        """An unmocked (default) config has weather disabled → available:false."""
        from orpheus_ui.api.weather import get_weather_latest
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        result = get_weather_latest(user=mock_user)

        assert result == {"available": False}

    def test_weather_latest_no_reading_returns_unavailable(self):
        """Enabled but nothing ingested yet → available:false."""
        from orpheus_ui.api.weather import get_weather_latest
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch(
            "orpheus_common.OrpheusConfig.get_instance",
            return_value=self._mock_config(enabled=True),
        ):
            with patch("orpheus_ui.api.weather._get_weather_db") as mock_db:
                mock_db.return_value.get_latest.return_value = None
                result = get_weather_latest(user=mock_user)

        assert result == {"available": False}

    def test_weather_latest_happy_path(self):
        """Enabled + a stored reading → available:true with the reading fields."""
        from orpheus_ui.api.weather import get_weather_latest
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)
        reading = WeatherReading(
            temperature_c=12.5,
            humidity_pct=81.0,
            pressure_hpa=1013.2,
            wind_speed_mps=3.4,
            wind_direction_deg=270,
            rainfall_mm=0.2,
            timestamp="2026-07-01T12:00:00+00:00",
        )

        with patch(
            "orpheus_common.OrpheusConfig.get_instance",
            return_value=self._mock_config(enabled=True),
        ):
            with patch("orpheus_ui.api.weather._get_weather_db") as mock_db:
                mock_db.return_value.get_latest.return_value = reading
                result = get_weather_latest(user=mock_user)

        assert result["available"] is True
        assert result["temperature_c"] == 12.5
        assert result["humidity_pct"] == 81.0
        assert result["pressure_hpa"] == 1013.2
        assert result["wind_speed_mps"] == 3.4
        assert result["wind_direction_deg"] == 270
        assert result["rainfall_mm"] == 0.2
        assert result["timestamp"] == "2026-07-01T12:00:00+00:00"

    def test_weather_latest_config_error_returns_unavailable(self):
        """A config load failure degrades to available:false, never a 500."""
        from orpheus_ui.api.weather import get_weather_latest
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch(
            "orpheus_common.OrpheusConfig.get_instance",
            side_effect=RuntimeError("bad config"),
        ):
            result = get_weather_latest(user=mock_user)

        assert result == {"available": False}

    def _replica_cfg(self, staging: str) -> MagicMock:
        cfg = MagicMock()
        cfg.weather.enabled = True
        cfg.ui.read_from_replica = True
        cfg.mirror.staging_path = staging
        return cfg

    def test_replica_routing_reads_replica_not_live(self, tmp_path, monkeypatch):
        """ui.read_from_replica + an existing replica → the weather card reads
        the replica (read-only) instead of creating/locking a live orpheus.db."""
        from orpheus_common.weather import WeatherDB

        from orpheus_ui.api import weather
        from orpheus_ui.auth.models import User

        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        replica = tmp_path / "replica.db"
        WeatherDB(db_path=replica).save(  # the mirror-produced snapshot
            WeatherReading(temperature_c=7.5, timestamp="2026-07-01T00:00:00+00:00")
        )

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_common.OrpheusConfig.get_instance",
            return_value=self._replica_cfg(str(replica)),
        ):
            result = weather.get_weather_latest(user=mock_user)

        assert result["available"] is True
        assert result["temperature_c"] == 7.5
        assert weather._weather_db.read_only is True
        assert weather._weather_db.db_path == replica
        # The live default DB was never created on the replica host.
        assert not (tmp_path / "detections" / "orpheus.db").exists()

    def test_replica_reader_never_writes_schema(self, tmp_path):
        """A replica without the weather table degrades to available:false — the
        reader must NOT create the table (or WAL side-files) on the snapshot."""
        from orpheus_ui.api import weather
        from orpheus_ui.auth.models import User

        replica = tmp_path / "replica.db"
        conn = sqlite3.connect(str(replica))  # a snapshot with no weather table
        conn.execute("CREATE TABLE detections (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        mock_user = MagicMock(spec=User)
        with patch(
            "orpheus_common.OrpheusConfig.get_instance",
            return_value=self._replica_cfg(str(replica)),
        ):
            result = weather.get_weather_latest(user=mock_user)

        assert result == {"available": False}
        conn = sqlite3.connect(str(replica))
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE name='weather_readings'"
            ).fetchall()
        finally:
            conn.close()
        assert rows == []  # no schema write on the replica
        assert not (tmp_path / "replica.db-wal").exists()  # no WAL conversion

    def test_replica_missing_falls_back_to_live(self, tmp_path, monkeypatch):
        """A configured-but-absent replica falls back to the live WeatherDB
        (matching db._build_detection_db's missing-snapshot fallback)."""
        from orpheus_ui.api import weather

        monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
        with patch(
            "orpheus_common.OrpheusConfig.get_instance",
            return_value=self._replica_cfg(str(tmp_path / "not-produced-yet.db")),
        ):
            db = weather._get_weather_db()

        assert db.read_only is False  # the live, writable default

    def test_weather_latest_db_error_returns_unavailable(self):
        """An unreadable weather DB degrades to available:false, never a 500."""
        from orpheus_ui.api.weather import get_weather_latest
        from orpheus_ui.auth.models import User

        mock_user = MagicMock(spec=User)

        with patch(
            "orpheus_common.OrpheusConfig.get_instance",
            return_value=self._mock_config(enabled=True),
        ):
            with patch(
                "orpheus_ui.api.weather._get_weather_db",
                side_effect=RuntimeError("disk gone"),
            ):
                result = get_weather_latest(user=mock_user)

        assert result == {"available": False}
